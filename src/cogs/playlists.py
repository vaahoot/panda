import asyncio
import re
from collections.abc import Awaitable, Callable

import discord
import wavelink
from discord.ext import commands

import core
from config import settings
from music import get_player
from music.views import (
    SELECT_OPTION_LIMIT,
    PagesView,
    PlaylistPagesView,
    PlaylistView,
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


class Playlists(commands.Cog, name="💿 Playlists"):
    def __init__(self, bot: core.Panda):
        self.bot: core.Panda = bot

    async def send_playlist_menu(
        self,
        ctx: commands.Context,
        description: str,
        on_select: Callable[[str], Awaitable[None]],
    ) -> None:
        """Send a dropdown of the author's playlists, or an error if they have none."""
        names = await self.bot.db.get_playlists(ctx.author)
        if not names:
            embed = discord.Embed(
                description=(
                    "You don't have any playlists yet. Create one with "
                    f"`{ctx.clean_prefix}create <name>`."
                ),
                color=settings.ERROR_COLOR,
            )
            await ctx.reply(embed=embed)
            return

        embed = discord.Embed(
            title="Your playlists", description=description, color=settings.MAIN_COLOR
        )
        if len(names) > SELECT_OPTION_LIMIT:
            embed.set_footer(
                text=f"Showing the first {SELECT_OPTION_LIMIT}, "
                "type the playlist name to use the rest."
            )

        view = PlaylistView(ctx, names, on_select)
        view.message = await ctx.send(embed=embed, view=view)

    async def save_to_playlist(
        self, ctx: commands.Context, name: str, link: str
    ) -> None:
        """Save the track(s) behind a link to the author's playlist."""
        embed = discord.Embed(color=settings.ERROR_COLOR)

        playlist_id = await self.bot.db.get_playlist_id(ctx.author, name)
        if playlist_id is None:
            embed.description = f"You don't have a playlist called **{name}**."
            await ctx.reply(embed=embed)
            return

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
            playlist_id,
            [(track.uri or link, track.title, track.author) for track in tracks],
        )

        if added == 0:
            if isinstance(result, wavelink.Playlist):
                embed.description = (
                    f"Every track from **`{result.name}`** is already in **{name}**."
                )
            else:
                embed.description = (
                    f"**{tracks[0].title}** by **{tracks[0].author}** "
                    f"is already in **{name}**."
                )
            await ctx.reply(embed=embed)
            return

        embed.color = settings.MAIN_COLOR
        if isinstance(result, wavelink.Playlist):
            embed.description = (
                f"Added **{added}** tracks from **`{result.name}`** to **{name}**."
            )
            if added < len(tracks):
                embed.description += f" Skipped {len(tracks) - added} already in it."
        else:
            embed.description = (
                f"Added **{tracks[0].title}** by **{tracks[0].author}** to **{name}**."
            )
        await ctx.send(embed=embed)

    async def remove_playlist(self, ctx: commands.Context, name: str) -> None:
        """Delete the author's playlist along with its tracks."""
        deleted = await self.bot.db.delete_playlist(ctx.author, name)
        if not deleted:
            embed = discord.Embed(
                description=f"You don't have a playlist called **{name}**.",
                color=settings.ERROR_COLOR,
            )
            await ctx.reply(embed=embed)
            return

        embed = discord.Embed(
            description=f"Deleted the playlist **{name}**.", color=settings.MAIN_COLOR
        )
        await ctx.send(embed=embed)

    async def load_playlist(self, ctx: commands.Context, name: str) -> None:
        """Add every track of the author's playlist to the queue."""
        embed = discord.Embed(color=settings.ERROR_COLOR)

        playlist_id = await self.bot.db.get_playlist_id(ctx.author, name)
        if playlist_id is None:
            embed.description = f"You don't have a playlist called **{name}**."
            await ctx.reply(embed=embed)
            return

        urls = await self.bot.db.get_playlist_urls(playlist_id)
        if not urls:
            embed.description = (
                f"**{name}** is empty. Add tracks with "
                f"`{ctx.clean_prefix}save {name} <link>`."
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
            embed.description = f"Couldn't load any tracks from **{name}**."
            await ctx.reply(embed=embed)
            return

        added: int = await player.queue.put_wait(tracks)

        embed.color = settings.MAIN_COLOR
        embed.description = f"Added the playlist **`{name}`** ({added} songs) to the queue."
        if failed:
            embed.set_footer(text=f"{failed} track(s) couldn't be loaded.")
        await ctx.send(embed=embed)

        if not player.playing:
            await player.play(player.queue.get())

    async def send_track_menu(self, ctx: commands.Context, name: str) -> None:
        """Send a dropdown of the tracks in the author's playlist, deleting the chosen one."""
        embed = discord.Embed(color=settings.ERROR_COLOR)

        playlist_id = await self.bot.db.get_playlist_id(ctx.author, name)
        if playlist_id is None:
            embed.description = f"You don't have a playlist called **{name}**."
            await ctx.reply(embed=embed)
            return

        tracks = await self.bot.db.get_playlist_tracks(playlist_id)
        if not tracks:
            embed.description = f"**{name}** doesn't have any tracks."
            await ctx.reply(embed=embed)
            return

        async def on_select(track_id: int, title: str) -> None:
            deleted = await self.bot.db.delete_playlist_track(playlist_id, track_id)
            if deleted:
                embed.color = settings.MAIN_COLOR
                embed.description = f"Removed **{title}** from **{name}**."
            else:
                embed.description = f"**{title}** is no longer in **{name}**."
            await ctx.send(embed=embed)

        view = TrackView(ctx, tracks, on_select)
        view.message = await ctx.send(
            embed=discord.Embed(
                title=name,
                description="Pick a track to remove from the playlist.",
                color=settings.MAIN_COLOR,
            ),
            view=view,
        )

    async def show_tracks(self, ctx: commands.Context, name: str) -> None:
        """Send the tracks of the author's playlist as pages of links."""
        embed = discord.Embed(color=settings.ERROR_COLOR)

        playlist_id = await self.bot.db.get_playlist_id(ctx.author, name)
        if playlist_id is None:
            embed.description = f"You don't have a playlist called **{name}**."
            await ctx.reply(embed=embed)
            return

        tracks = await self.bot.db.get_playlist_tracks(playlist_id)
        if not tracks:
            embed.description = f"**{name}** doesn't have any tracks."
            await ctx.reply(embed=embed)
            return

        async def on_play() -> None:
            await self.load_playlist(ctx, name)

        # Playing needs a voice channel, so there's no Play button in DMs
        view = PlaylistPagesView(ctx, name, tracks, on_play if ctx.guild else None)
        if view.children:
            view.message = await ctx.send(embed=view.embed(), view=view)
        else:
            view.stop()
            await ctx.send(embed=view.embed())

    @commands.command(brief="<name> Create a new playlist.")
    async def create(self, ctx: commands.Context, *, name: str) -> None:
        """Create a new playlist with the given name.
        Playlists belong to you and can be played in any server."""
        embed = discord.Embed(color=settings.ERROR_COLOR)
        name = name.strip()

        if len(name) > PLAYLIST_NAME_LIMIT:
            embed.description = (
                f"Playlist names can be at most {PLAYLIST_NAME_LIMIT} characters."
            )
            await ctx.reply(embed=embed)
            return

        created = await self.bot.db.create_playlist(ctx.author, name)
        if not created:
            embed.description = f"You already have a playlist called **{name}**."
            await ctx.reply(embed=embed)
            return

        embed.color = settings.MAIN_COLOR
        embed.description = (
            f"Created the playlist **{name}**. Add tracks with "
            f"`{ctx.clean_prefix}save {name} <link>`."
        )
        await ctx.send(embed=embed)

    @commands.command(brief="[name] <link> Save a track to a playlist.")
    async def save(self, ctx: commands.Context, *, args: str) -> None:
        """Save a YouTube or Spotify link to one of your playlists.
        The link goes last, e.g. `save my playlist <link>`.
        Without a name you'll get a menu to pick from your playlists.
        Playlist and album links save every track in them."""
        parts = args.rsplit(maxsplit=1)
        name = parts[0].strip() if len(parts) > 1 else None
        link = parts[-1].strip("<>")

        if not PLAYLIST_LINK.match(link):
            embed = discord.Embed(
                description="I can only save YouTube or Spotify links.",
                color=settings.ERROR_COLOR,
            )
            await ctx.reply(embed=embed)
            return

        if name is not None:
            await self.save_to_playlist(ctx, name, link)
            return

        async def on_select(chosen: str) -> None:
            await self.save_to_playlist(ctx, chosen, link)

        await self.send_playlist_menu(
            ctx, "Pick a playlist to save the track to.", on_select
        )

    @commands.command(brief="[name] Remove a track from a playlist.")
    async def unsave(
        self, ctx: commands.Context, *, name: str | None = None
    ) -> None:
        """Remove a track from one of your playlists.
        Without a name you'll get a menu to pick from your playlists,
        then a menu to pick the track to remove."""
        if name is not None:
            await self.send_track_menu(ctx, name.strip())
            return

        async def on_select(chosen: str) -> None:
            await self.send_track_menu(ctx, chosen)

        await self.send_playlist_menu(
            ctx, "Pick a playlist to remove a track from.", on_select
        )

    @commands.command(aliases=["pl"], brief="[name] Play one of your playlists.")
    @commands.guild_only()
    async def playlist(self, ctx: commands.Context, *, name: str | None = None) -> None:
        """Add one of your playlists to the queue.
        Without a name you'll get a menu to pick from your playlists."""
        if isinstance(ctx.channel, (discord.DMChannel, discord.GroupChannel)):
            return

        if name is not None:
            await self.load_playlist(ctx, name.strip())
            return

        async def on_select(chosen: str) -> None:
            await self.load_playlist(ctx, chosen)

        await self.send_playlist_menu(
            ctx, "Pick a playlist to add to the queue.", on_select
        )

    @commands.command(brief="[name] Show the tracks in a playlist.")
    async def view(
        self, ctx: commands.Context, *, name: str | None = None
    ) -> None:
        """Show every track in one of your playlists, 20 per page.
        In a server there's a Play button to add the playlist to the queue.
        Without a name you'll get a menu to pick from your playlists."""
        if name is not None:
            await self.show_tracks(ctx, name.strip())
            return

        async def on_select(chosen: str) -> None:
            await self.show_tracks(ctx, chosen)

        await self.send_playlist_menu(ctx, "Pick a playlist to show.", on_select)

    @commands.command(aliases=["pls"], brief="List your playlists.")
    async def playlists(self, ctx: commands.Context) -> None:
        """List all of your playlists and how many tracks each one has."""
        playlists = await self.bot.db.get_playlist_summaries(ctx.author)
        if not playlists:
            embed = discord.Embed(
                description=(
                    "You don't have any playlists yet. Create one with "
                    f"`{ctx.clean_prefix}create <name>`."
                ),
                color=settings.ERROR_COLOR,
            )
            await ctx.reply(embed=embed)
            return

        lines = [
            rf"{counter}\. **{name}** - {count} {'track' if count == 1 else 'tracks'}"
            for counter, (name, count) in enumerate(playlists, start=1)
        ]
        view = PagesView(ctx, "Your playlists", lines, ("playlist", "playlists"))
        if view.children:
            view.message = await ctx.send(embed=view.embed(), view=view)
        else:
            view.stop()
            await ctx.send(embed=view.embed())

    @commands.command(aliases=["del"], brief="[name] Delete one of your playlists.")
    async def delete(
        self, ctx: commands.Context, *, name: str | None = None
    ) -> None:
        """Delete one of your playlists and all the tracks saved in it.
        Without a name you'll get a menu to pick from your playlists."""
        if name is not None:
            await self.remove_playlist(ctx, name.strip())
            return

        async def on_select(chosen: str) -> None:
            await self.remove_playlist(ctx, chosen)

        await self.send_playlist_menu(ctx, "Pick a playlist to delete.", on_select)


async def setup(bot):
    await bot.add_cog(Playlists(bot))
