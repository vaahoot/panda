from collections.abc import Awaitable, Callable

import discord
from discord.ext import commands

import log
from config import settings

SELECT_OPTION_LIMIT = 25  # Discord's limit for options in a select menu


class PlaylistSelect(discord.ui.Select):
    def __init__(
        self, names: list[str], on_select: Callable[[str], Awaitable[None]]
    ):
        options = [
            discord.SelectOption(label=name) for name in names[:SELECT_OPTION_LIMIT]
        ]
        super().__init__(placeholder="Choose a playlist", options=options)
        self.on_select = on_select

    async def callback(self, interaction: discord.Interaction) -> None:
        name = self.values[0]
        embed = discord.Embed(
            description=f"Picked **{name}**...", color=settings.MAIN_COLOR
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.view.stop()  # type: ignore
        await self.on_select(name)


class PlaylistView(discord.ui.View):
    """Dropdown of the author's playlists, on_select is called with the chosen name."""

    def __init__(
        self,
        ctx: commands.Context,
        names: list[str],
        on_select: Callable[[str], Awaitable[None]],
    ):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.message: discord.Message | None = None
        self.add_item(PlaylistSelect(names, on_select))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True

        embed = discord.Embed(
            description="This isn't your playlist menu.", color=settings.ERROR_COLOR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        # The bot's command error handler doesn't see errors from menus, so report them here
        await log.error(f"Playlist menu failed: {type(error).__name__}: {error}")
        embed = discord.Embed(
            description="Something went wrong with that playlist. Try again!",
            color=settings.ERROR_COLOR,
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_timeout(self) -> None:
        if self.message is not None:
            embed = discord.Embed(
                description="Playlist selection timed out.",
                color=settings.ERROR_COLOR,
            )
            await self.message.edit(embed=embed, view=None)
