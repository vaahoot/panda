import asyncio
import io
from collections.abc import Awaitable, Callable

import discord

import log
from clash.profile_view import clan_link, player_link
from config import settings

from . import generate_image
DECK_IMAGE_FILENAME = "deck.png"


def with_tag(name: str, tag_link: str | None) -> str:
    name = f"**{discord.utils.escape_markdown(name)}**"
    return f"{name} {tag_link}" if tag_link else name


def player_text(name: str, name_tag: str | None, clan: str | None, clan_tag: str | None) -> str:
    """Name and clan, with their tags linking to their RoyaleAPI pages."""
    name_text = with_tag(name, player_link(name_tag) if name_tag else None)
    clan_text = with_tag(clan, clan_link(clan_tag) if clan_tag else None) if clan else "**No clan**"
    return f"-# Name\n{name_text}\n-# Clan\n{clan_text}"


def first_mode(decks: dict[str, list[list[dict]]]) -> str:
    """The first mode the player has a deck for: 20 wins, then ranked, then ladder."""
    return next(iter(decks))


class DeckModeSelect(discord.ui.Select):
    def __init__(self, modes: list[str], current: str):
        options = [discord.SelectOption(label=mode, default=mode == current) for mode in modes]
        super().__init__(placeholder="Choose a mode", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: DeckView = self.view  # type: ignore
        await view.show(interaction, self.values[0], 0)


class DeckPageButton(discord.ui.Button):
    def __init__(self, label: str, step: int, disabled: bool):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.step = step

    async def callback(self, interaction: discord.Interaction) -> None:
        view: DeckView = self.view  # type: ignore
        await view.show(interaction, view.mode, view.index + self.step)


class ProfileButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Profile", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: DeckView = self.view  # type: ignore
        await view.send_profile(interaction)


# Builds the profile of the player with this tag, None if there's no such player
ProfileBuilder = Callable[[str], Awaitable[discord.ui.LayoutView | None]]


class DeckView(discord.ui.LayoutView):
    """The player's name and clan with the deck image below. When they have decks for more
    than one mode (20 wins, ranked, ladder), a menu switches between them, and when a mode has
    more than one deck, arrows above the menu page through them, next to a button that sends the
    player's profile as a new message. Images are built the first time a deck is shown and
    reused after that."""

    def __init__(
        self,
        decks: dict[str, list[list[dict]]],
        current: str,
        current_image: bytes,
        name: str,
        name_tag: str | None,
        clan: str | None,
        clan_tag: str | None,
        profile: ProfileBuilder | None = None,
    ):
        super().__init__(timeout=300)
        self.decks = decks
        self.name_tag = name_tag
        # Without the player's tag there's no profile to show
        self.profile = profile if name_tag else None
        self.mode = current
        self.index = 0
        self.images: dict[tuple[str, int], bytes] = {(current, 0): current_image}
        self.message: discord.Message | None = None
        self.prebuild_task: asyncio.Task | None = None

        self.text = discord.ui.TextDisplay(player_text(name, name_tag, clan, clan_tag))
        self.gallery = discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{DECK_IMAGE_FILENAME}"))
        self.container = discord.ui.Container(accent_colour=settings.MAIN_COLOR)
        self.add_item(self.container)
        self.render()

    def render(self, controls: bool = True) -> None:
        """Rebuilds the container for the deck showing. Without controls, only the text and image."""
        self.container.clear_items()
        self.container.add_item(self.text)
        self.container.add_item(self.gallery)
        count = len(self.decks[self.mode])
        if count > 1:
            self.container.add_item(discord.ui.TextDisplay(f"-# {self.mode} deck {self.index + 1}/{count}"))
        if not controls:
            return
        buttons: list[discord.ui.Button] = []
        if count > 1:
            # Labels can't be bold, these heavy brackets read like a bold < and >
            buttons += [
                DeckPageButton("❮", -1, self.index == 0),
                DeckPageButton("❯", 1, self.index == count - 1),
            ]
        if self.profile is not None:
            buttons.append(ProfileButton())
        if buttons:
            self.container.add_item(discord.ui.ActionRow(*buttons))
        if len(self.decks) > 1:
            self.container.add_item(discord.ui.ActionRow(DeckModeSelect(list(self.decks), self.mode)))

    def has_other_decks(self) -> bool:
        return len(self.decks) > 1 or any(len(mode_decks) > 1 for mode_decks in self.decks.values())

    def has_controls(self) -> bool:
        return self.has_other_decks() or self.profile is not None

    async def send_profile(self, interaction: discord.Interaction) -> None:
        """Sends the player's profile as a new message, leaving the deck as it is."""
        assert self.profile is not None and self.name_tag is not None
        # Acknowledges the click without changing this message, fetching can take a moment
        await interaction.response.defer()
        profile = await self.profile(self.name_tag)
        if profile is None:
            embed = discord.Embed(
                description=f"No player found with the tag `{self.name_tag}`.",
                color=settings.ERROR_COLOR,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        await interaction.followup.send(view=profile)

    async def show(self, interaction: discord.Interaction, mode: str, index: int) -> None:
        file = await self.image_file(mode, index)
        self.mode, self.index = mode, index
        self.render()
        # The gallery shows attachment://deck.png, so replacing the file switches the image
        await interaction.response.edit_message(attachments=[file], view=self)

    def prebuild(self) -> None:
        """Builds the other decks' images in the background, so a switch only waits for Discord."""
        self.prebuild_task = asyncio.create_task(self._prebuild())

    async def _prebuild(self) -> None:
        # Each mode's first deck first, the one a mode switch shows, then the rest
        decks = sorted(
            ((mode, index) for mode, mode_decks in self.decks.items() for index in range(len(mode_decks))),
            key=lambda deck: deck[1],
        )
        for mode, index in decks:
            try:
                await self.image_file(mode, index)
            except Exception as e:
                # Not fatal, image_file builds it again when the deck is shown
                await log.warning(f"Couldn't prebuild {mode} deck {index + 1}'s image: {type(e).__name__}: {e}")

    async def image_file(self, mode: str, index: int) -> discord.File:
        if (mode, index) not in self.images:
            buffer = await generate_image.build_deck_image(self.decks[mode][index])
            self.images[(mode, index)] = buffer.getvalue()
        return discord.File(io.BytesIO(self.images[(mode, index)]), filename=DECK_IMAGE_FILENAME)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        # The bot's command error handler doesn't see errors from menus, so report them here
        await log.error(f"Deck menu failed: {type(error).__name__}: {error}")
        failed = "get the profile" if isinstance(item, ProfileButton) else "switch the deck"
        embed = discord.Embed(
            description=f"Couldn't {failed}. Try again!", color=settings.ERROR_COLOR
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_timeout(self) -> None:
        # Keep whichever deck is showing, just drop the buttons and menu. The text and image are
        # part of the view too, so it can't be removed altogether
        if self.message is not None and self.has_controls():
            self.render(controls=False)
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass  # Message deleted, nothing to clean up
