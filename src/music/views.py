from collections.abc import Awaitable, Callable

import discord
from discord.ext import commands

import log
from config import settings

SELECT_OPTION_LIMIT = 25  # Discord's limit for options in a select menu
SELECT_TEXT_LIMIT = 100  # Discord's limit for a select option label or description

Track = tuple[int, str | None, str | None]  # (track id, title, author)


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


class TrackSelect(discord.ui.Select):
    def __init__(
        self,
        tracks: list[Track],
        start: int,
        placeholder: str,
        on_select: Callable[[int, str], Awaitable[None]],
    ):
        page = tracks[start : start + SELECT_OPTION_LIMIT]
        self.titles = {
            track_id: title or "Unknown track" for track_id, title, _ in page
        }
        options = [
            discord.SelectOption(
                label=f"{number}. {self.titles[track_id]}"[:SELECT_TEXT_LIMIT],
                value=str(track_id),
                description=author[:SELECT_TEXT_LIMIT] if author else None,
            )
            for number, (track_id, _, author) in enumerate(page, start=start + 1)
        ]
        super().__init__(placeholder=placeholder, options=options)
        self.on_select = on_select

    async def callback(self, interaction: discord.Interaction) -> None:
        track_id = int(self.values[0])
        title = self.titles[track_id]
        embed = discord.Embed(
            description=f"Picked **{title}**...", color=settings.MAIN_COLOR
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.view.stop()  # type: ignore
        await self.on_select(track_id, title)


class PageButton(discord.ui.Button):
    def __init__(self, label: str, step: int, disabled: bool):
        super().__init__(
            label=label, style=discord.ButtonStyle.secondary, disabled=disabled
        )
        self.step = step

    async def callback(self, interaction: discord.Interaction) -> None:
        view: TrackView = self.view  # type: ignore
        view.page += self.step
        view.render()
        await interaction.response.edit_message(view=view)


class AuthorMenuView(discord.ui.View):
    """Base for menus only the command's author can use."""

    timeout_message = "Selection timed out."

    def __init__(self, ctx: commands.Context):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.message: discord.Message | None = None

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
                description=self.timeout_message, color=settings.ERROR_COLOR
            )
            await self.message.edit(embed=embed, view=None)


class PlaylistView(AuthorMenuView):
    """Dropdown of the author's playlists, on_select is called with the chosen name."""

    timeout_message = "Playlist selection timed out."

    def __init__(
        self,
        ctx: commands.Context,
        names: list[str],
        on_select: Callable[[str], Awaitable[None]],
    ):
        super().__init__(ctx)
        self.add_item(PlaylistSelect(names, on_select))


class TrackView(AuthorMenuView):
    """Dropdown of a playlist's tracks, paged when there are more than fit in one menu.
    on_select is called with the chosen track's id and title."""

    timeout_message = "Track selection timed out."

    def __init__(
        self,
        ctx: commands.Context,
        tracks: list[Track],
        on_select: Callable[[int, str], Awaitable[None]],
    ):
        super().__init__(ctx)
        self.tracks = tracks
        self.on_select = on_select
        self.page = 0
        self.pages = -(-len(tracks) // SELECT_OPTION_LIMIT)
        self.render()

    def render(self) -> None:
        self.clear_items()
        placeholder = "Choose a track"
        if self.pages > 1:
            placeholder += f" (page {self.page + 1}/{self.pages})"
        self.add_item(
            TrackSelect(
                self.tracks,
                self.page * SELECT_OPTION_LIMIT,
                placeholder,
                self.on_select,
            )
        )
        if self.pages > 1:
            self.add_item(PageButton("Previous", -1, self.page == 0))
            self.add_item(PageButton("Next", 1, self.page == self.pages - 1))
