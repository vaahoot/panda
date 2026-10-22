import asyncio
import io

import discord

import log
from config import settings

from . import generate_image
from .get_deck import RANKED

DECK_IMAGE_FILENAME = "deck.png"


def deck_message(name: str, clan: str | None) -> str:
    return f"Name: {name}\nClan: {clan}"


def first_mode(decks: dict[str, list[dict]]) -> str:
    """Ranked when the player has a ranked deck, otherwise whatever they do have."""
    return RANKED if RANKED in decks else next(iter(decks))


class DeckModeSelect(discord.ui.Select):
    def __init__(self, modes: list[str], current: str):
        options = [discord.SelectOption(label=mode, default=mode == current) for mode in modes]
        super().__init__(placeholder="Choose a mode", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: DeckModeView = self.view  # type: ignore
        mode = self.values[0]
        for option in self.options:
            option.default = option.label == mode

        await interaction.response.edit_message(attachments=[await view.image_file(mode)], view=view)


class DeckModeView(discord.ui.View):
    """Switches the deck image between the player's ranked and ladder decks. Images are built
    the first time a mode is picked and reused after that."""

    def __init__(self, decks: dict[str, list[dict]], current: str, current_image: bytes):
        super().__init__(timeout=300)
        self.decks = decks
        self.images: dict[str, bytes] = {current: current_image}
        self.message: discord.Message | None = None
        self.add_item(DeckModeSelect(list(decks), current))
        self.prebuild_task: asyncio.Task | None = None

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
        # Keep whichever deck is showing, just drop the menu
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass  # Message deleted, nothing to clean up
