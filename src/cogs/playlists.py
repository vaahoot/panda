import asyncio
import copy
import re
from collections.abc import Awaitable, Callable

import discord
import wavelink
from discord.ext import commands

import core
import log
from config import settings
from database import Playlist
from music import get_player
from music.views import (
    PERSONAL_EMOJI,
    SELECT_OPTION_LIMIT,
    SERVER_EMOJI,
    ChoiceView,
    PagesView,
    PlaylistPagesView,
    PlaylistView,
    TabbedPagesView,
    TrackView,
)

PLAYLIST_LINK = re.compile(
    r"^((https?://)?((www|m|music)\.)?(youtube\.com|youtu\.be)/"
    r"|(https?://)?open\.spotify\.com/"
    r"|spotify:)",
    re.IGNORECASE,
)
PLAYLIST_NAME_LIMIT = 100  # Discord's limit for a select option label
# Lavalink lookups at once when loading a playlist, so big playlists don't flood it
PLAYLIST_LOAD_CONCURRENCY = 10
SERVER_PLAYLIST_LIMIT = 50
BUTTON_LABEL_LIMIT = 80  # Discord's limit for a button label

# Which playlists a command works on
ALL, PERSONAL, SERVER = "all", "personal", "server"
# Typed before a playlist name to pick the server's or your own, e.g. `view !party`
SERVER_PREFIX, PERSONAL_PREFIX = "!", "."


def is_mod(user: discord.abc.User) -> bool:
    return isinstance(user, discord.Member) and user.guild_permissions.manage_guild


def can_manage(user: discord.abc.User, playlist: Playlist) -> bool:
    """Whether the user can delete, rename, lock or unlock the playlist: their own, or a
    server playlist they created or they're a mod in."""
    return playlist.user_id == user.id or (
        playlist.guild_id is not None and is_mod(user)
    )


def can_edit(user: discord.abc.User, playlist: Playlist) -> bool:
    """Whether the user can save or remove tracks: anyone can in an unlocked server playlist."""
    return (playlist.guild_id is not None and not playlist.locked) or can_manage(
        user, playlist
    )


def split_prefix(name: str) -> tuple[str | None, str]:
    """The scope a name's prefix asks for, None without one, and the name without it."""
    if name.startswith(SERVER_PREFIX):
        return SERVER, name[len(SERVER_PREFIX) :].strip()
    if name.startswith(PERSONAL_PREFIX):
        return PERSONAL, name[len(PERSONAL_PREFIX) :].strip()
    return None, name


def in_scope(playlist: Playlist, scope: str) -> bool:
    if scope == PERSONAL:
        return playlist.guild_id is None
    if scope == SERVER:
        return playlist.guild_id is not None
    return True


def find_named(playlists: list[Playlist], name: str) -> list[Playlist]:
    """The playlists called name, only the server's or your own when it has a prefix.
    A name that only matches with its prefix, from before prefixes, still finds that one."""
    scope, bare = split_prefix(name)
    matches = [
        p
        for p in playlists
        if p.name.casefold() == bare.casefold() and in_scope(p, scope or ALL)
    ]
    return matches or [p for p in playlists if p.name.casefold() == name.casefold()]


def bold_name(playlist: Playlist) -> str:
    """The playlist's name for messages, marked when it's a server playlist."""
    if playlist.guild_id is None:
        return f"**{playlist.name}**"
    return f"{SERVER_EMOJI} **{playlist.name}**"


def error_embed(description: str) -> discord.Embed:
    return discord.Embed(description=description, color=settings.ERROR_COLOR)


class Playlists(commands.Cog, name="💿 Playlists"):
    """Your own playlists work in every server, server playlists are shared by everyone in
    one server. Commands work on both, you'll be asked when a name matches one of each.
    Start a name with ! for the server's playlist or . for your own, e.g. `view !party`."""

    def __init__(self, bot: core.Panda):
        self.bot: core.Panda = bot
        # Marks locked server playlists in the list, the bot's "locked" emoji once loaded
        self.locked_emoji = "🔒"

    async def cog_load(self) -> None:
        try:
            emojis = await self.bot.fetch_application_emojis()
        except discord.HTTPException as e:
            await log.warning(f"Couldn't fetch the application emojis: {e}")
            return
        emoji = discord.utils.get(emojis, name="locked")
        if emoji is None:
            await log.warning("The bot has no \"locked\" emoji, using 🔒 instead")
            return
        self.locked_emoji = str(emoji)

    async def choose_playlist(
        self,
        ctx: commands.Context,
        name: str | None,
        description: str,
        on_select: Callable[[Playlist], Awaitable[None]],
        scope: str = ALL,
        usable: Callable[[Playlist], bool] | None = None,
        none_usable: str | None = None,
    ) -> None:
        """Run on_select with the author's or the server's playlist called name. Without a
        name, or when both have one called that, send a dropdown to pick from.
        The dropdown only offers playlists that pass usable, none_usable is the error when
        none do. A typed name skips that check, so on_select can say why it can't be used."""
        playlists = [
            p
            for p in await self.bot.db.get_playlists(ctx.author, ctx.guild)
            if in_scope(p, scope)
        ]

        if name is not None:
            name = name.strip()
            matches = find_named(playlists, name)
            if not matches:
                prefix_scope, bare = split_prefix(name)
                if prefix_scope is not None and scope not in (ALL, prefix_scope):
                    # e.g. share, which only takes your own playlists, with #name
                    kind = "your own" if scope == PERSONAL else "server"
                    message = f"This command only works on {kind} playlists."
                elif prefix_scope == SERVER and ctx.guild is None:
                    message = "Server playlists only work in a server."
                else:
                    message = self.not_found(ctx, bare, prefix_scope or scope)
                await ctx.reply(embed=error_embed(message))
                return
            if len(matches) == 1:
                await on_select(matches[0])
                return
            embed = discord.Embed(
                title=matches[0].name,
                description=(
                    "You and this server both have a playlist with this name, "
                    "which one do you mean?\n\n"
                    f"Skip this next time with `{SERVER_PREFIX}{matches[0].name}` "
                    f"for the server's or `{PERSONAL_PREFIX}{matches[0].name}` for yours."
                ),
                color=settings.MAIN_COLOR,
            )
            view = PlaylistView(ctx, matches, on_select)
            view.message = await ctx.send(embed=embed, view=view)
            return

        if usable is not None:
            playlists = [p for p in playlists if usable(p)]
        if not playlists:
            await ctx.reply(
                embed=error_embed(none_usable or self.no_playlists(ctx, scope))
            )
            return

        embed = discord.Embed(
            title="Playlists", description=description, color=settings.MAIN_COLOR
        )
        if len(playlists) > SELECT_OPTION_LIMIT:
            embed.set_footer(
                text=f"Showing the first {SELECT_OPTION_LIMIT}, "
                "type the playlist name to use the rest."
            )
        view = PlaylistView(ctx, playlists, on_select)
        view.message = await ctx.send(embed=embed, view=view)

    def not_found(self, ctx: commands.Context, name: str, scope: str) -> str:
        if scope == SERVER:
            return f"This server doesn't have a playlist called **{name}**."
        if scope == PERSONAL or ctx.guild is None:
            return f"You don't have a playlist called **{name}**."
        return f"Neither you nor this server have a playlist called **{name}**."

    def no_playlists(self, ctx: commands.Context, scope: str) -> str:
        create = f"Create one with `{ctx.clean_prefix}create <name>`."
        if scope == SERVER:
            return f"This server doesn't have any playlists yet. {create}"
        if scope == PERSONAL or ctx.guild is None:
            return f"You don't have any playlists yet. {create}"
        return f"Neither you nor this server have any playlists yet. {create}"

    async def refresh(
        self, ctx: commands.Context, playlist: Playlist
    ) -> Playlist | None:
        """The playlist as it is now, it may have been locked or deleted since a menu showed it."""
        current = await self.bot.db.get_playlist(playlist.playlist_id)
        if current is None:
            await ctx.reply(
                embed=error_embed(f"{bold_name(playlist)} doesn't exist anymore.")
            )
        return current

    async def check_edit(self, ctx: commands.Context, playlist: Playlist) -> bool:
        if can_edit(ctx.author, playlist):
            return True
        await ctx.reply(
            embed=error_embed(
                f"{bold_name(playlist)} is locked, only its creator and members "
                "with Manage Server can change it."
            )
        )
        return False

    async def check_manage(
        self, ctx: commands.Context, playlist: Playlist, action: str
    ) -> bool:
        if can_manage(ctx.author, playlist):
            return True
        await ctx.reply(
            embed=error_embed(
                f"Only the creator of {bold_name(playlist)} and members with "
                f"Manage Server can {action} it."
            )
        )
        return False

    async def check_server_create(self, ctx: commands.Context) -> bool:
        """Whether the author can add another playlist to the server, replies if not."""
        assert ctx.guild is not None
        if await self.bot.db.get_mods_create_playlists(ctx.guild) and not is_mod(ctx.author):
            await ctx.reply(
                embed=error_embed(
                    "Only members with Manage Server can create server playlists here."
                )
            )
            return False
        if await self.bot.db.count_guild_playlists(ctx.guild) >= SERVER_PLAYLIST_LIMIT:
            await ctx.reply(
                embed=error_embed(
                    f"This server already has {SERVER_PLAYLIST_LIMIT} playlists, "
                    "delete one to make room."
                )
            )
            return False
        return True

    async def check_name(self, ctx: commands.Context, name: str) -> bool:
        """Whether a new playlist name can be used, replies if not."""
        if not name:
            message = "Give the playlist a name."
        elif len(name) > PLAYLIST_NAME_LIMIT:
            message = f"Playlist names can be at most {PLAYLIST_NAME_LIMIT} characters."
        elif name.startswith((SERVER_PREFIX, PERSONAL_PREFIX)):
            message = (
                f"Playlist names can't start with `{SERVER_PREFIX}` or `{PERSONAL_PREFIX}`, "
                "those pick a server playlist or your own."
            )
        else:
            return True
        await ctx.reply(embed=error_embed(message))
        return False

    async def save_to_playlist(
        self, ctx: commands.Context, playlist: Playlist, link: str
    ) -> None:
        """Save the track(s) behind a link to the playlist."""
        current = await self.refresh(ctx, playlist)
        if current is None or not await self.check_edit(ctx, current):
            return
        name = bold_name(current)
        embed = discord.Embed(color=settings.ERROR_COLOR)

        try:
            async with ctx.typing():
                result: wavelink.Search = await wavelink.Playable.search(link)
        except wavelink.exceptions.LavalinkLoadException:
            embed.description = "Couldn't load that link, try something else."
            await ctx.reply(embed=embed)
            return

        if not result:
            embed.description = "Couldn't find anything at that link."
            await ctx.reply(embed=embed)
            return

        tracks = result.tracks if isinstance(result, wavelink.Playlist) else [result[0]]
        added = await self.bot.db.add_playlist_tracks(
            current.playlist_id,
            [(track.uri or link, track.title, track.author) for track in tracks],
            ctx.author,
        )

        if added == 0:
            if isinstance(result, wavelink.Playlist):
                embed.description = (
                    f"Every track from **`{result.name}`** is already in {name}."
                )
            else:
                embed.description = (
                    f"**{tracks[0].title}** by **{tracks[0].author}** "
                    f"is already in {name}."
                )
            await ctx.reply(embed=embed)
            return

        embed.color = settings.MAIN_COLOR
        if isinstance(result, wavelink.Playlist):
            embed.description = (
                f"Added **{added}** tracks from **`{result.name}`** to {name}."
            )
            if added < len(tracks):
                embed.description += f" Skipped {len(tracks) - added} already in it."
        else:
            embed.description = (
                f"Added **{tracks[0].title}** by **{tracks[0].author}** to {name}."
            )
        await ctx.send(embed=embed)

    async def remove_playlist(self, ctx: commands.Context, playlist: Playlist) -> None:
        """Ask to confirm, then delete the playlist along with its tracks."""
        current = await self.refresh(ctx, playlist)
        if current is None or not await self.check_manage(ctx, current, "delete"):
            return

        async def on_delete() -> None:
            # Checked again, it may have changed while the question was open
            latest = await self.refresh(ctx, current)
            if latest is None or not await self.check_manage(ctx, latest, "delete"):
                return
            await self.bot.db.delete_playlist(latest.playlist_id)
            embed = discord.Embed(
                description=f"Deleted the playlist {bold_name(latest)}.",
                color=settings.MAIN_COLOR,
            )
            await ctx.send(embed=embed)

        async def on_cancel() -> None:
            embed = discord.Embed(
                description=f"Kept the playlist {bold_name(current)}.",
                color=settings.MAIN_COLOR,
            )
            await ctx.send(embed=embed)

        count = len(await self.bot.db.get_playlist_urls(current.playlist_id))
        description = (
            f"This deletes {bold_name(current)} and its {count} "
            f"{'track' if count == 1 else 'tracks'}, it can't be undone."
        )
        if current.guild_id is not None:
            description += " Everyone in this server will lose it."
        view = ChoiceView(
            ctx,
            [
                ("Delete", None, discord.ButtonStyle.danger, False, on_delete),
                ("Cancel", None, discord.ButtonStyle.secondary, False, on_cancel),
            ],
            timeout_message="Delete timed out, the playlist was kept.",
        )
        view.message = await ctx.send(
            embed=discord.Embed(
                title=f"Delete {current.name}?",
                description=description,
                color=settings.ERROR_COLOR,
            ),
            view=view,
        )

    async def load_playlist(self, ctx: commands.Context, playlist: Playlist) -> None:
        """Add every track of the playlist to the queue."""
        current = await self.refresh(ctx, playlist)
        if current is None:
            return
        embed = discord.Embed(color=settings.ERROR_COLOR)

        urls = await self.bot.db.get_playlist_urls(current.playlist_id)
        if not urls:
            embed.description = (
                f"{bold_name(current)} is empty. Add tracks with "
                f"`{ctx.clean_prefix}save {current.name} <link>`."
            )
            await ctx.reply(embed=embed)
            return

        player = await get_player(ctx, embed)
        if player is None:
            return

        semaphore = asyncio.Semaphore(PLAYLIST_LOAD_CONCURRENCY)

        async def search(url: str) -> wavelink.Search:
            async with semaphore:
                return await wavelink.Playable.search(url)

        async with ctx.typing():
            # Keeps the playlist's order, failed tracks come back as exceptions
            results = await asyncio.gather(
                *(search(url) for url in urls), return_exceptions=True
            )

        tracks: list[wavelink.Playable] = []
        failed = 0
        for result in results:
            if isinstance(result, BaseException) or not result:
                failed += 1
                continue
            if isinstance(result, wavelink.Playlist):
                tracks.extend(result.tracks)
            else:
                tracks.append(result[0])

        if not tracks:
            embed.description = f"Couldn't load any tracks from {bold_name(current)}."
            await ctx.reply(embed=embed)
            return

        added: int = await player.queue.put_wait(tracks)

        embed.color = settings.MAIN_COLOR
        embed.description = (
            f"Added the playlist {bold_name(current)} ({added} songs) to the queue."
        )
        if failed:
            embed.set_footer(text=f"{failed} track(s) couldn't be loaded.")
        await ctx.send(embed=embed)

        if not player.playing:
            await player.play(player.queue.get())

    def user_name(self, ctx: commands.Context, user_id: int) -> str | None:
        member = ctx.guild.get_member(user_id) if ctx.guild else None
        user = member or self.bot.get_user(user_id)
        return user.display_name if user else None

    async def send_track_menu(self, ctx: commands.Context, playlist: Playlist) -> None:
        """Send a dropdown of the tracks in the playlist, deleting the chosen one."""
        current = await self.refresh(ctx, playlist)
        if current is None or not await self.check_edit(ctx, current):
            return
        name = bold_name(current)
        embed = discord.Embed(color=settings.ERROR_COLOR)

        tracks = await self.bot.db.get_playlist_tracks(current.playlist_id)
        if not tracks:
            embed.description = f"{name} doesn't have any tracks."
            await ctx.reply(embed=embed)
            return

        # Everything in your own playlist was added by you, only server playlists show who
        adders: dict[int, str] = {}
        if current.guild_id is not None:
            for track_id, user_id in (
                await self.bot.db.get_track_adders(current.playlist_id)
            ).items():
                if (user_name := self.user_name(ctx, user_id)) is not None:
                    adders[track_id] = user_name

        async def on_select(track_id: int, title: str) -> None:
            # It may have been locked while the menu was open
            latest = await self.refresh(ctx, current)
            if latest is None or not await self.check_edit(ctx, latest):
                return
            deleted = await self.bot.db.delete_playlist_track(
                current.playlist_id, track_id
            )
            if deleted:
                embed.color = settings.MAIN_COLOR
                embed.description = f"Removed **{title}** from {name}."
            else:
                embed.description = f"**{title}** is no longer in {name}."
            await ctx.send(embed=embed)

        view = TrackView(ctx, tracks, on_select, adders)
        view.message = await ctx.send(
            embed=discord.Embed(
                title=current.name,
                description="Pick a track to remove from the playlist.",
                color=settings.MAIN_COLOR,
            ),
            view=view,
        )

    async def show_tracks(self, ctx: commands.Context, playlist: Playlist) -> None:
        """Send the tracks of the playlist as pages of links."""
        current = await self.refresh(ctx, playlist)
        if current is None:
            return

        tracks = await self.bot.db.get_playlist_tracks(current.playlist_id)
        if not tracks:
            await ctx.reply(
                embed=error_embed(f"{bold_name(current)} doesn't have any tracks.")
            )
            return

        async def on_play(user: discord.abc.User) -> None:
            # Anyone can press Play, the playlist goes to the voice channel of whoever did
            play_ctx = ctx
            if user.id != ctx.author.id:
                play_ctx = copy.copy(ctx)
                play_ctx.author = user  # type: ignore
            await self.load_playlist(play_ctx, current)

        async def on_lock(interaction: discord.Interaction) -> bool | None:
            latest = await self.bot.db.get_playlist(current.playlist_id)
            if latest is None:
                description = f"{bold_name(current)} doesn't exist anymore."
            elif not can_manage(interaction.user, latest):
                action = "unlock" if latest.locked else "lock"
                description = (
                    f"Only the creator of {bold_name(latest)} and members with "
                    f"Manage Server can {action} it."
                )
            else:
                await self.bot.db.set_playlist_locked(latest.playlist_id, not latest.locked)
                return not latest.locked
            await interaction.response.send_message(
                embed=error_embed(description), ephemeral=True
            )
            return None

        server = current.guild_id is not None
        heading = f"{SERVER_EMOJI} {current.name}" if server else current.name
        # Playing needs a voice channel, so there's no Play button in DMs
        view = PlaylistPagesView(
            ctx,
            heading,
            tracks,
            on_play if ctx.guild else None,
            locked=current.locked,
            on_lock=on_lock if server else None,
        )
        if view.children:
            view.message = await ctx.send(embed=view.embed(), view=view)
        else:
            view.stop()
            await ctx.send(embed=view.embed())

    async def create_personal(self, ctx: commands.Context, name: str) -> None:
        if await self.bot.db.create_playlist(ctx.author, name) is None:
            await ctx.reply(
                embed=error_embed(f"You already have a playlist called **{name}**.")
            )
            return
        embed = discord.Embed(
            description=(
                f"Created your playlist **{name}**. Add tracks with "
                f"`{ctx.clean_prefix}save {name} <link>`."
            ),
            color=settings.MAIN_COLOR,
        )
        await ctx.send(embed=embed)

    async def create_server(self, ctx: commands.Context, name: str) -> None:
        assert ctx.guild is not None
        if not await self.check_server_create(ctx):
            return
        if await self.bot.db.create_playlist(ctx.author, name, ctx.guild) is None:
            await ctx.reply(
                embed=error_embed(f"This server already has a playlist called **{name}**.")
            )
            return
        embed = discord.Embed(
            description=(
                f"Created the server playlist {SERVER_EMOJI} **{name}**. Anyone here can "
                f"add tracks with `{ctx.clean_prefix}save {name} <link>`, you or a mod "
                f"can stop that with `{ctx.clean_prefix}lock {name}`."
            ),
            color=settings.MAIN_COLOR,
        )
        await ctx.send(embed=embed)

    async def set_locked(
        self, ctx: commands.Context, playlist: Playlist, locked: bool
    ) -> None:
        current = await self.refresh(ctx, playlist)
        action = "lock" if locked else "unlock"
        if current is None or not await self.check_manage(ctx, current, action):
            return
        if current.locked == locked:
            await ctx.reply(
                embed=error_embed(f"{bold_name(current)} is already {action}ed.")
            )
            return

        await self.bot.db.set_playlist_locked(current.playlist_id, locked)
        if locked:
            description = (
                f"Locked {bold_name(current)}, only its creator and members with "
                "Manage Server can change it now."
            )
        else:
            description = f"Unlocked {bold_name(current)}, anyone here can change it now."
        await ctx.send(
            embed=discord.Embed(description=description, color=settings.MAIN_COLOR)
        )

    async def share_playlist(self, ctx: commands.Context, playlist: Playlist) -> None:
        """Copy the author's playlist into a new server playlist."""
        assert ctx.guild is not None
        current = await self.refresh(ctx, playlist)
        if current is None or not await self.check_server_create(ctx):
            return
        new_id = await self.bot.db.copy_playlist(
            current.playlist_id, ctx.author, current.name, ctx.guild
        )
        if new_id is None:
            await ctx.reply(
                embed=error_embed(
                    f"This server already has a playlist called **{current.name}**."
                )
            )
            return
        embed = discord.Embed(
            description=(
                f"Shared **{current.name}** with the server as {SERVER_EMOJI} "
                f"**{current.name}**. It's a copy, changes to one don't affect the other."
            ),
            color=settings.MAIN_COLOR,
        )
        await ctx.send(embed=embed)

    async def copy_playlist(self, ctx: commands.Context, playlist: Playlist) -> None:
        """Copy a server playlist into a new playlist of the author's."""
        current = await self.refresh(ctx, playlist)
        if current is None:
            return
        new_id = await self.bot.db.copy_playlist(
            current.playlist_id, ctx.author, current.name
        )
        if new_id is None:
            await ctx.reply(
                embed=error_embed(f"You already have a playlist called **{current.name}**.")
            )
            return
        embed = discord.Embed(
            description=(
                f"Copied {bold_name(current)} to your playlists as **{current.name}**, "
                "you can play it in any server now."
            ),
            color=settings.MAIN_COLOR,
        )
        await ctx.send(embed=embed)

    async def rename_playlist(
        self,
        ctx: commands.Context,
        playlist: Playlist,
        new_name: str,
        new_scope: str | None,
    ) -> None:
        """new_scope is what a prefix on the new name asked for, renaming can't change it."""
        current = await self.refresh(ctx, playlist)
        if current is None or not await self.check_manage(ctx, current, "rename"):
            return
        if new_scope is not None and not in_scope(current, new_scope):
            kind = "a server" if current.guild_id is not None else "your own"
            await ctx.reply(
                embed=error_embed(
                    f"{bold_name(current)} is {kind} playlist, renaming can't change that. "
                    f"Use `{ctx.clean_prefix}share` or `{ctx.clean_prefix}copy` instead."
                )
            )
            return
        if current.name == new_name:
            await ctx.reply(
                embed=error_embed(f"{bold_name(current)} is already called that.")
            )
            return
        if not await self.bot.db.rename_playlist(current.playlist_id, new_name):
            owner = (
                "You already have" if current.guild_id is None else "This server already has"
            )
            await ctx.reply(
                embed=error_embed(f"{owner} a playlist called **{new_name}**.")
            )
            return
        embed = discord.Embed(
            description=(
                f"Renamed {bold_name(current)} to "
                f"{bold_name(current._replace(name=new_name))}."
            ),
            color=settings.MAIN_COLOR,
        )
        await ctx.send(embed=embed)

    @commands.command(brief="<name> Create a new playlist.")
    async def create(self, ctx: commands.Context, *, name: str) -> None:
        """Create a new playlist with the given name.
        In a server you choose whether it's just yours, playable in any server,
        or a server playlist everyone here can play and add to.
        Start the name with ! for a server playlist or . for your own to skip the question."""
        scope, name = split_prefix(name.strip())
        if not await self.check_name(ctx, name):
            return

        guild = ctx.guild
        if scope == SERVER:
            if guild is None:
                await ctx.reply(
                    embed=error_embed("Server playlists can only be created in a server.")
                )
                return
            await self.create_server(ctx, name)
            return
        if scope == PERSONAL:
            await self.create_personal(ctx, name)
            return

        if guild is None or (
            await self.bot.db.get_mods_create_playlists(guild) and not is_mod(ctx.author)
        ):
            await self.create_personal(ctx, name)
            return

        taken = await self.bot.db.find_playlists(ctx.author, guild, name)
        personal_taken = any(p.guild_id is None for p in taken)
        server_taken = any(p.guild_id is not None for p in taken)
        if personal_taken and server_taken:
            await ctx.reply(
                embed=error_embed(
                    f"You and this server both have a playlist called **{name}** already."
                )
            )
            return

        async def on_personal() -> None:
            await self.create_personal(ctx, name)

        async def on_server() -> None:
            await self.create_server(ctx, name)

        description = (
            f"**Just me**: yours only, play it in any server.\n"
            f"**Everyone**: anyone in this server can play it and add tracks."
        )
        if personal_taken:
            description += f"\n\nYou already have a playlist called **{name}**."
        elif server_taken:
            description += f"\n\nThis server already has a playlist called **{name}**."
        view = ChoiceView(
            ctx,
            [
                (
                    "Just me",
                    PERSONAL_EMOJI,
                    discord.ButtonStyle.primary,
                    personal_taken,
                    on_personal,
                ),
                (
                    f"Everyone in {guild.name}"[:BUTTON_LABEL_LIMIT],
                    SERVER_EMOJI,
                    discord.ButtonStyle.primary,
                    server_taken,
                    on_server,
                ),
            ],
        )
        view.message = await ctx.send(
            embed=discord.Embed(
                title=f"Who is {name} for?",
                description=description,
                color=settings.MAIN_COLOR,
            ),
            view=view,
        )

    @commands.command(brief="[name] <link> Save a track to a playlist.")
    async def save(self, ctx: commands.Context, *, args: str) -> None:
        """Save a YouTube or Spotify link to a playlist.
        The link goes last, e.g. `save my playlist <link>`.
        Without a name you'll get a menu to pick from your playlists and the server's.
        Playlist and album links save every track in them."""
        parts = args.rsplit(maxsplit=1)
        name = parts[0].strip() if len(parts) > 1 else None
        link = parts[-1].strip("<>")

        if not PLAYLIST_LINK.match(link):
            await ctx.reply(
                embed=error_embed("I can only save YouTube or Spotify links.")
            )
            return

        async def on_select(playlist: Playlist) -> None:
            await self.save_to_playlist(ctx, playlist, link)

        await self.choose_playlist(
            ctx,
            name,
            "Pick a playlist to save the track to.",
            on_select,
            usable=lambda p: can_edit(ctx.author, p),
        )

    @commands.command(brief="[name] Remove a track from a playlist.")
    async def unsave(
        self, ctx: commands.Context, *, name: str | None = None
    ) -> None:
        """Remove a track from a playlist.
        Without a name you'll get a menu to pick from your playlists and the server's,
        then a menu to pick the track to remove."""

        async def on_select(playlist: Playlist) -> None:
            await self.send_track_menu(ctx, playlist)

        await self.choose_playlist(
            ctx,
            name,
            "Pick a playlist to remove a track from.",
            on_select,
            usable=lambda p: can_edit(ctx.author, p),
        )

    @commands.command(aliases=["pl"], brief="[name] Play a playlist.")
    @commands.guild_only()
    async def playlist(self, ctx: commands.Context, *, name: str | None = None) -> None:
        """Add one of your playlists or one of the server's to the queue.
        Without a name you'll get a menu to pick from."""
        if isinstance(ctx.channel, (discord.DMChannel, discord.GroupChannel)):
            return

        async def on_select(playlist: Playlist) -> None:
            await self.load_playlist(ctx, playlist)

        await self.choose_playlist(
            ctx, name, "Pick a playlist to add to the queue.", on_select
        )

    @commands.command(brief="[name] Show the tracks in a playlist.")
    async def view(
        self, ctx: commands.Context, *, name: str | None = None
    ) -> None:
        """Show every track in a playlist, 20 per page.
        In a server anyone can press Play to add the playlist to the queue, and server
        playlists have a button for their creator and mods to lock or unlock them.
        Without a name you'll get a menu to pick from your playlists and the server's."""

        async def on_select(playlist: Playlist) -> None:
            await self.show_tracks(ctx, playlist)

        await self.choose_playlist(ctx, name, "Pick a playlist to show.", on_select)

    @commands.command(aliases=["pls"], brief="List your playlists and the server's.")
    async def playlists(self, ctx: commands.Context) -> None:
        """List your playlists and, in a server, the server's playlists,
        with how many tracks each one has."""
        personal = await self.bot.db.get_playlist_summaries(user=ctx.author)
        personal_lines = [
            rf"{counter}\. **{p.name}** - {count} {'track' if count == 1 else 'tracks'}"
            for counter, (p, count) in enumerate(personal, start=1)
        ]

        if ctx.guild is None:
            if not personal_lines:
                await ctx.reply(embed=error_embed(self.no_playlists(ctx, PERSONAL)))
                return
            view = PagesView(
                ctx, "Your playlists", personal_lines, ("playlist", "playlists")
            )
            if view.children:
                view.message = await ctx.send(embed=view.embed(), view=view)
            else:
                view.stop()
                await ctx.send(embed=view.embed())
            return

        server = await self.bot.db.get_playlist_summaries(guild=ctx.guild)
        server_lines = [
            rf"{counter}\. **{p.name}**{f' {self.locked_emoji}' if p.locked else ''} - "
            f"{count} {'track' if count == 1 else 'tracks'} · <@{p.user_id}>"
            for counter, (p, count) in enumerate(server, start=1)
        ]
        if not personal_lines and not server_lines:
            await ctx.reply(embed=error_embed(self.no_playlists(ctx, ALL)))
            return

        create = f"Create one with `{ctx.clean_prefix}create <name>`."
        view = TabbedPagesView(
            ctx,
            [
                (
                    "Mine",
                    PERSONAL_EMOJI,
                    "Your playlists",
                    personal_lines,
                    f"You don't have any playlists yet. {create}",
                ),
                (
                    "Server",
                    SERVER_EMOJI,
                    f"{ctx.guild.name} playlists",
                    server_lines,
                    f"This server doesn't have any playlists yet. {create}",
                ),
            ],
            ("playlist", "playlists"),
            # The server's list unless it's empty and yours isn't
            tab=1 if server_lines or not personal_lines else 0,
        )
        view.message = await ctx.send(embed=view.embed(), view=view)

    @commands.command(aliases=["del"], brief="[name] Delete a playlist.")
    async def delete(
        self, ctx: commands.Context, *, name: str | None = None
    ) -> None:
        """Delete a playlist and all the tracks saved in it, after you confirm.
        Server playlists can be deleted by their creator and members with Manage Server.
        Without a name you'll get a menu to pick from."""

        async def on_select(playlist: Playlist) -> None:
            await self.remove_playlist(ctx, playlist)

        await self.choose_playlist(
            ctx,
            name,
            "Pick a playlist to delete.",
            on_select,
            usable=lambda p: can_manage(ctx.author, p),
        )

    @commands.command(brief="[name] Stop others changing a server playlist.")
    @commands.guild_only()
    async def lock(self, ctx: commands.Context, *, name: str | None = None) -> None:
        """Lock a server playlist so only its creator and members with Manage Server
        can save or remove tracks. Everyone can still play it.
        Only the creator and members with Manage Server can lock it.
        Without a name you'll get a menu to pick from."""

        async def on_select(playlist: Playlist) -> None:
            await self.set_locked(ctx, playlist, True)

        await self.choose_playlist(
            ctx,
            name,
            "Pick a server playlist to lock.",
            on_select,
            scope=SERVER,
            usable=lambda p: can_manage(ctx.author, p) and not p.locked,
            none_usable="There are no server playlists you can lock.",
        )

    @commands.command(brief="[name] Let everyone change a server playlist again.")
    @commands.guild_only()
    async def unlock(self, ctx: commands.Context, *, name: str | None = None) -> None:
        """Unlock a server playlist so anyone in the server can save or remove tracks.
        Only the creator and members with Manage Server can unlock it.
        Without a name you'll get a menu to pick from."""

        async def on_select(playlist: Playlist) -> None:
            await self.set_locked(ctx, playlist, False)

        await self.choose_playlist(
            ctx,
            name,
            "Pick a server playlist to unlock.",
            on_select,
            scope=SERVER,
            usable=lambda p: can_manage(ctx.author, p) and p.locked,
            none_usable="There are no locked server playlists you can unlock.",
        )

    @commands.command(brief="[name] Copy one of your playlists to the server.")
    @commands.guild_only()
    async def share(self, ctx: commands.Context, *, name: str | None = None) -> None:
        """Copy one of your playlists into a new server playlist with the same name,
        so everyone here can play it and add to it. Your playlist stays as it is.
        Without a name you'll get a menu to pick from your playlists."""

        async def on_select(playlist: Playlist) -> None:
            await self.share_playlist(ctx, playlist)

        await self.choose_playlist(
            ctx,
            name,
            "Pick one of your playlists to share with the server.",
            on_select,
            scope=PERSONAL,
        )

    @commands.command(brief="[name] Copy a server playlist to your playlists.")
    @commands.guild_only()
    async def copy(self, ctx: commands.Context, *, name: str | None = None) -> None:
        """Copy a server playlist into your own playlists with the same name,
        so you can play it in any server.
        Without a name you'll get a menu to pick from the server's playlists."""

        async def on_select(playlist: Playlist) -> None:
            await self.copy_playlist(ctx, playlist)

        await self.choose_playlist(
            ctx,
            name,
            "Pick a server playlist to copy to your playlists.",
            on_select,
            scope=SERVER,
        )

    @commands.command(brief="[name] to <new name> Rename a playlist.")
    async def rename(self, ctx: commands.Context, *, args: str) -> None:
        """Rename a playlist, e.g. `rename old name to new name`.
        Server playlists can be renamed by their creator and members with Manage Server.
        Without the old name, e.g. `rename to new name`, you'll get a menu to pick from."""
        # Names can contain " to " themselves, so split where the old name is a playlist
        name, new_name = None, args.strip()
        if new_name.casefold().startswith("to "):
            new_name = new_name[3:]
        else:
            playlists = await self.bot.db.get_playlists(ctx.author, ctx.guild)
            splits = [
                (args[: m.start()].strip(), args[m.end() :])
                for m in re.finditer(r"\s+to\s+", args, re.IGNORECASE)
            ]
            if not splits:
                await ctx.reply(
                    embed=error_embed(
                        f"Use `{ctx.clean_prefix}rename <name> to <new name>`."
                    )
                )
                return
            # The first split with an existing playlist, else the first one says it's not found
            name, new_name = next(
                (s for s in splits if find_named(playlists, s[0])), splits[0]
            )
        new_scope, new_name = split_prefix(new_name.strip())
        if not await self.check_name(ctx, new_name):
            return

        async def on_select(playlist: Playlist) -> None:
            await self.rename_playlist(ctx, playlist, new_name, new_scope)

        await self.choose_playlist(
            ctx,
            name,
            f"Pick a playlist to rename to **{new_name}**.",
            on_select,
            scope=new_scope or ALL,
            usable=lambda p: can_manage(ctx.author, p),
        )


async def setup(bot):
    await bot.add_cog(Playlists(bot))
