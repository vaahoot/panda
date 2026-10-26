import asyncio
import io

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


def first_mode(decks: dict[str, list[dict]]) -> str:
    """The first mode the player has a deck for: 20 wins, then ranked, then ladder."""
    return next(iter(decks))


class DeckModeSelect(discord.ui.Select):
    def __init__(self, modes: list[str], current: str):
        options = [discord.SelectOption(label=mode, default=mode == current) for mode in modes]
        super().__init__(placeholder="Choose a mode", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: DeckView = self.view  # type: ignore
        mode = self.values[0]
        for option in self.options:
            option.default = option.label == mode

        # The gallery shows attachment://deck.png, so replacing the file switches the image
        await interaction.response.edit_message(attachments=[await view.image_file(mode)], view=view)


class DeckView(discord.ui.LayoutView):
    """The player's name and clan with the deck image below. When they have decks for more
    than one mode (20 wins, ranked, ladder), a menu switches between them. Images are built the first time a mode is
    picked and reused after that."""

    def __init__(
        self,
        decks: dict[str, list[dict]],
        current: str,
        current_image: bytes,
        name: str,
        name_tag: str | None,
        clan: str | None,
        clan_tag: str | None,
    ):
        super().__init__(timeout=300)
        self.decks = decks
        self.images: dict[str, bytes] = {current: current_image}
        self.message: discord.Message | None = None
        self.prebuild_task: asyncio.Task | None = None

        self.menu: discord.ui.ActionRow | None = None
        if len(decks) > 1:
            self.menu = discord.ui.ActionRow(DeckModeSelect(list(decks), current))
        self.container = discord.ui.Container(
            discord.ui.TextDisplay(player_text(name, name_tag, clan, clan_tag)),
            discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{DECK_IMAGE_FILENAME}")),
            *([self.menu] if self.menu else []),
            accent_colour=settings.MAIN_COLOR,
        )
        self.add_item(self.container)

    def prebuild(self) -> None:
        """Builds the other modes' images in the background, so a switch only waits for Discord."""
        self.prebuild_task = asyncio.create_task(self._prebuild())

    async def _prebuild(self) -> None:
        for mode in self.decks:
            try:
                await self.image_file(mode)
            except Exception as e:
                # Not fatal, image_file builds it again when the mode is picked
                await log.warning(f"Couldn't prebuild the {mode} deck image: {type(e).__name__}: {e}")

    async def image_file(self, mode: str) -> discord.File:
        if mode not in self.images:
            buffer = await generate_image.build_deck_image(self.decks[mode])
            self.images[mode] = buffer.getvalue()
        return discord.File(io.BytesIO(self.images[mode]), filename=DECK_IMAGE_FILENAME)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        # The bot's command error handler doesn't see errors from menus, so report them here
        await log.error(f"Deck mode menu failed: {type(error).__name__}: {error}")
        embed = discord.Embed(
            description="Couldn't switch the deck. Try again!", color=settings.ERROR_COLOR
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_timeout(self) -> None:
        # Keep whichever deck is showing, just drop the menu. The text and image are part of
        # the view too, so it can't be removed altogether
        if self.message is not None and self.menu is not None:
            self.container.remove_item(self.menu)
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass  # Message deleted, nothing to clean up
