import contextlib
from collections.abc import Awaitable, Callable

import discord
from discord.ext import commands

import log
from config import settings

SELECT_OPTION_LIMIT = 25  # Discord's limit for options in a select menu
SELECT_TEXT_LIMIT = 100  # Discord's limit for a select option label or description
PAGE_SIZE = 20  # Lines per page in a paged list
# Keep a full page of links under the embed description limit
TRACK_TITLE_LIMIT = 80
TRACK_AUTHOR_LIMIT = 40
EMBED_DESCRIPTION_LIMIT = 4096

Track = tuple[int, str | None, str | None, str]  # (track id, title, author, url)


async def run_pick(
    select: discord.ui.Select,
    interaction: discord.Interaction,
    embed: discord.Embed,
    action: Awaitable[None],
) -> None:
    """Show the "Picked..." embed in place of the menu while action runs, then delete
    it so only the action's own reply is left."""
    await interaction.response.edit_message(embed=embed, view=None)
    select.view.stop()  # type: ignore
    try:
        await action
    finally:
        with contextlib.suppress(discord.HTTPException):
            await interaction.delete_original_response()


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
        await run_pick(self, interaction, embed, self.on_select(name))


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
            track_id: title or "Unknown track" for track_id, title, *_ in page
        }
        options = [
            discord.SelectOption(
                label=f"{number}. {self.titles[track_id]}"[:SELECT_TEXT_LIMIT],
                value=str(track_id),
                description=author[:SELECT_TEXT_LIMIT] if author else None,
            )
            for number, (track_id, _, author, _) in enumerate(page, start=start + 1)
        ]
        super().__init__(placeholder=placeholder, options=options)
        self.on_select = on_select

    async def callback(self, interaction: discord.Interaction) -> None:
        track_id = int(self.values[0])
        title = self.titles[track_id]
        embed = discord.Embed(
            description=f"Picked **{title}**...", color=settings.MAIN_COLOR
        )
        await run_pick(self, interaction, embed, self.on_select(track_id, title))


class PageButton(discord.ui.Button):
    def __init__(self, label: str, step: int, disabled: bool):
        super().__init__(
            label=label, style=discord.ButtonStyle.secondary, disabled=disabled
        )
        self.step = step

    async def callback(self, interaction: discord.Interaction) -> None:
        view: TrackView | PagesView = self.view  # type: ignore
        view.page += self.step
        await view.show_page(interaction)


class PlayButton(discord.ui.Button):
    def __init__(self, disabled: bool):
        super().__init__(
            label="Play", style=discord.ButtonStyle.primary, disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: PlaylistPagesView = self.view  # type: ignore
        # Set before any await so a quick second click can't queue the playlist twice
        if view.played or view.on_play is None:
            await interaction.response.defer()
            return
        view.played = True
        self.disabled = True
        await interaction.response.edit_message(view=view)
        await view.on_play()


class AuthorMenuView(discord.ui.View):
    """Base for menus only the command's author can use."""

    timeout_message = "Selection timed out."

    def __init__(self, ctx: commands.Context, timeout: float = 60):
        super().__init__(timeout=timeout)
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

    async def show_page(self, interaction: discord.Interaction) -> None:
        self.render()
        await interaction.response.edit_message(view=self)


def escape_text(text: str, limit: int) -> str:
    """Escape markdown and brackets, then shorten to limit characters."""
    text = discord.utils.escape_markdown(text).replace("[", "\\[").replace("]", "\\]")
    if len(text) <= limit:
        return text
    # A cut escape would leave a lone backslash that escapes whatever follows
    return text[: limit - 1].rstrip("\\") + "…"


def track_line(number: int, track: Track) -> str:
    """Numbered markdown link to a track, followed by its author."""
    _, title, author, url = track
    line = (
        rf"{number}\. [{escape_text(title or 'Unknown track', TRACK_TITLE_LIMIT)}]"
        f"({url.replace(')', '%29')})"
    )
    if author:
        line += f" - {escape_text(author, TRACK_AUTHOR_LIMIT)}"
    return line


class PagesView(AuthorMenuView):
    """Numbered lines in an embed, PAGE_SIZE per page with buttons to page through.
    noun is the (singular, plural) name of what's listed, for the count in the footer."""

    def __init__(
        self,
        ctx: commands.Context,
        heading: str,
        lines: list[str],
        noun: tuple[str, str],
    ):
        super().__init__(ctx, timeout=300)
        self.heading = heading
        self.lines = lines
        self.noun = noun
        self.page = 0
        self.pages = -(-len(lines) // PAGE_SIZE)
        self.render()

    def embed(self) -> discord.Embed:
        start = self.page * PAGE_SIZE
        lines: list[str] = []
        length = 0
        for line in self.lines[start : start + PAGE_SIZE]:
            length += len(line) + 1
            if length > EMBED_DESCRIPTION_LIMIT:
                break
            lines.append(line)
        count = len(self.lines)
        footer = f"{count} {self.noun[0] if count == 1 else self.noun[1]}"
        if self.pages > 1:
            footer = f"Page {self.page + 1}/{self.pages} · {footer}"
        embed = discord.Embed(
            title=self.heading, description="\n".join(lines), color=settings.MAIN_COLOR
        )
        embed.set_footer(text=footer)
        return embed

    def render(self) -> None:
        self.clear_items()
        if self.pages > 1:
            # Labels can't be bold, these heavy brackets read like a bold < and >
            self.add_item(PageButton("❮", -1, self.page == 0))
            self.add_item(PageButton("❯", 1, self.page == self.pages - 1))

    async def show_page(self, interaction: discord.Interaction) -> None:
        self.render()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def on_timeout(self) -> None:
        # Keep the list, only the buttons stop working
        if self.message is not None:
            await self.message.edit(view=None)


class PlaylistPagesView(PagesView):
    """A playlist's tracks as links, in pages.
    With on_play there's also a button that queues the playlist."""

    def __init__(
        self,
        ctx: commands.Context,
        name: str,
        tracks: list[Track],
        on_play: Callable[[], Awaitable[None]] | None = None,
    ):
        # Set before super().__init__, which renders the buttons
        self.on_play = on_play
        self.played = False
        super().__init__(
            ctx,
            name,
            [track_line(number, track) for number, track in enumerate(tracks, start=1)],
            ("track", "tracks"),
        )

    def render(self) -> None:
        super().render()
        if self.on_play is not None:
            self.add_item(PlayButton(self.played))
