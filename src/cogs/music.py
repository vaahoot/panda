import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import cast

import discord
import wavelink
from discord.ext import commands

import core
import log
from config import settings
from music import PandaPlayer
from music.views import SELECT_OPTION_LIMIT, PlaylistView, TrackView

PLAYLIST_LINK = re.compile(
    r"^((https?://)?((www|m|music)\.)?(youtube\.com|youtu\.be)/"
    r"|(https?://)?open\.spotify\.com/"
    r"|spotify:)",
    re.IGNORECASE,
)
PLAYLIST_NAME_LIMIT = 100  # Discord's limit for a select option label
# Lavalink lookups at once when loading a playlist, so big playlists don't flood it
PLAYLIST_LOAD_CONCURRENCY = 10
EMBED_DESCRIPTION_LIMIT = 4096


class Music(commands.Cog, name="🎶 Music"):
    def __init__(self, bot: core.Panda):
        self.bot: core.Panda = bot

    async def get_player(
        self, ctx: commands.Context, embed: discord.Embed
    ) -> PandaPlayer | None:
        """Get the guild's player, joining the author's voice channel if needed.
        Replies with the error embed and returns None on failure."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if player is None:
            try:
                player = await ctx.author.voice.channel.connect(cls=PandaPlayer)  # type: ignore
            except AttributeError:
                embed.description = "At least join a voice channel man."
                await ctx.reply(embed=embed)
                return None
            except discord.ClientException:
                embed.description = "I couldn't join the voice channel. Try again!"
                await ctx.reply(embed=embed)
                return None

        player.autoplay = wavelink.AutoPlayMode.enabled

        # Lock the player to this voice channel
        if player.home is None:
            player.home = ctx.channel  # type: ignore

        return player

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
                    f"`{ctx.clean_prefix}new_playlist <name>`."
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
        await self.bot.db.add_playlist_tracks(
            playlist_id,
            [(track.uri or link, track.title, track.author) for track in tracks],
        )

        embed.color = settings.MAIN_COLOR
        if isinstance(result, wavelink.Playlist):
            embed.description = (
                f"Added **{len(tracks)}** tracks from **`{result.name}`** to **{name}**."
            )
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

        player = await self.get_player(ctx, embed)
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

    @commands.Cog.listener()
    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        await log.info(
            f"Wavelink Node connected: {payload.node} | Resumed: {payload.resumed}"
        )

    @commands.Cog.listener()
    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        player: wavelink.Player | None = payload.player
        if not player:
            return

        player = cast("PandaPlayer", player)
        if player.home is None:
            return

        track: wavelink.Playable = payload.track
        if track == player.last_track:  # Do not re-announce the song if it's looped.
            return

        player.last_track = track

        embed: discord.Embed = discord.Embed(color=settings.MAIN_COLOR)
        embed.description = f"Now playing [**{track.title}**]({track.uri}) by **{track.author}**"

        await player.home.send(embed=embed)

    @commands.command(aliases=["p", "P"], brief="Play a track.")
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Play a given song. Can provide a song name or a url."""
        if ctx.guild is None:
            return
        if isinstance(ctx.channel, (discord.DMChannel, discord.GroupChannel)):
            return

        embed = discord.Embed(color=settings.ERROR_COLOR)

        player = await self.get_player(ctx, embed)
        if player is None:
            return

        try:
            tracks: wavelink.Search = await wavelink.Playable.search(
                query, source=wavelink.TrackSource.YouTube
            )
        except wavelink.exceptions.LavalinkLoadException:
            embed.description = "Couldn't load that track, try something else."            
            await ctx.reply(embed=embed)
            return

        if not tracks:
            embed.description = (
                "Couldn't find any songs with that query. Please try again."
            )
            await ctx.reply(embed=embed)
            return

        # If we got to this point, the play should be successful, change the color to main.
        embed.color = settings.MAIN_COLOR

        if isinstance(tracks, wavelink.Playlist):
            # tracks is a playlist...
            added: int = await player.queue.put_wait(tracks)
            embed.description = (
                f"Added the playlist **`{tracks.name}`** ({added} songs) to the queue."
            )
            await ctx.send(embed=embed)
        else:
            track: wavelink.Playable = tracks[0]
            await player.queue.put_wait(track)
            embed.description = f"Added **{track}** by **{track.author}** to the queue."
            await ctx.send(embed=embed)

        if not player.playing:
            # Play now since we aren't playing anything...
            await player.play(player.queue.get())

    @commands.command(aliases=["s", "S"], brief="Skip current track.")
    @commands.guild_only()
    async def skip(self, ctx: commands.Context) -> None:
        """Skip current track."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if not player:
            await ctx.reply("I'm not even playing anything.")
            return

        await player.skip(force=True)
        await ctx.message.add_reaction("\u2705")

    @commands.command(name="toggle", aliases=["pause", "resume"], brief="Toggle pause.")
    @commands.guild_only()
    async def toggle_pause(self, ctx: commands.Context) -> None:
        """Pause or Resume the Player depending on its current state."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if not player:
            await ctx.reply("I'm not even playing anything.")
            return

        await player.pause(not player.paused)
        await ctx.message.add_reaction("\u2705")

    @commands.command(aliases=["dc"], brief="Disconnect from the voice channel.")
    @commands.guild_only()
    async def disconnect(self, ctx: commands.Context) -> None:
        """Disconnect the Player."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if player is None:
            await ctx.reply("Wasn't in the channel anyways.")
            return

        await player.disconnect()
        await ctx.message.add_reaction("\u2705")

    @commands.command(aliases=["q", "Q"], brief="Get the track queue.")
    @commands.guild_only()
    async def queue(self, ctx: commands.Context) -> None:
        """Get the track queue."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if player is None:
            await ctx.reply("Not playing anything right now.")
            return

        embed: discord.Embed = discord.Embed(title="Queue", color=settings.MAIN_COLOR)
        queue: wavelink.Queue

        if len(player.queue) > 0:
            queue = player.queue
        else:
            queue = player.auto_queue

        if len(queue) <= 0 and player.current is None:
            embed.title = ""
            embed.description = "Nothing in the queue"
            await ctx.send(embed=embed)
            return

        counter = 0
        if player.current is not None:
            embed.add_field(
                name="",
                value=rf"{counter}\. [**{player.current.title}**]({player.current.uri}) by **{player.current.author}**",
                inline=False
            )
            counter += 1

        for track in queue:
            if counter > 10:
                break

            embed.add_field(
                name="",
                value=rf"{counter}\. [**{track.title}**]({track.uri}) by **{track.author}**",
                inline=False,
            )
            counter += 1

        await ctx.send(embed=embed)

    @commands.command(aliases=["repeat"], brief="Loop track/queue/off.")
    @commands.guild_only()
    async def loop(self, ctx: commands.Context, mode: str = "track"):
        """Loop track/queue/off.
        Not providing an option will turn on track loop."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if player is None:
            await ctx.reply("Not playing anything right now.")
            return

        embed: discord.Embed = discord.Embed(color=settings.MAIN_COLOR)
        if mode == "track":
            player.queue.mode = wavelink.QueueMode.loop
            embed.description = "Current track will now loop."
        elif mode == "queue":
            player.queue.mode = wavelink.QueueMode.loop_all
            embed.description = "Your queue will now loop."
        elif mode == "off":
            player.queue.mode = wavelink.QueueMode.normal
            embed.description = "Looping disabled."
        else:
            embed.color = settings.ERROR_COLOR
            embed.description = "Invalid option. I need `track`, `queue` or `off`."

        await ctx.send(embed=embed)

    @commands.command(brief="Shuffle the queue.")
    @commands.guild_only()
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

    async def shuffle(self, ctx: commands.Context):
        """Shuffle the queue."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if player is None:
            await ctx.reply("Not playing anything right now.")
            return

        player.queue.shuffle()
        embed = discord.Embed(
            description="Shuffled your queue.", color=settings.MAIN_COLOR
        )
        await ctx.send(embed=embed)

    @commands.command(aliases=["np"], brief="<name> Create a new playlist.")
    async def new_playlist(self, ctx: commands.Context, *, name: str) -> None:
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

    @commands.command(aliases=["ap"], brief="[name] <link> Save a track to a playlist.")
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

    @commands.command(aliases=["rt"], brief="[name] Remove a track from a playlist.")
    async def remove_track(
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

    @commands.command(aliases=["lp"], brief="List your playlists.")
    async def list_playlists(self, ctx: commands.Context) -> None:
        """List all of your playlists and how many tracks each one has."""
        playlists = await self.bot.db.get_playlist_summaries(ctx.author)
        if not playlists:
            embed = discord.Embed(
                description=(
                    "You don't have any playlists yet. Create one with "
                    f"`{ctx.clean_prefix}new_playlist <name>`."
                ),
                color=settings.ERROR_COLOR,
            )
            await ctx.reply(embed=embed)
            return

        lines: list[str] = []
        length = 0
        for counter, (name, count) in enumerate(playlists, start=1):
            line = rf"{counter}\. **{name}** - {count} {'track' if count == 1 else 'tracks'}"
            length += len(line) + 1
            if length > EMBED_DESCRIPTION_LIMIT:
                break
            lines.append(line)

        embed = discord.Embed(
            title="Your playlists",
            description="\n".join(lines),
            color=settings.MAIN_COLOR,
        )
        if len(lines) < len(playlists):
            embed.set_footer(text=f"Showing {len(lines)} of {len(playlists)} playlists.")
        await ctx.send(embed=embed)

    @commands.command(aliases=["dp"], brief="[name] Delete one of your playlists.")
    async def delete_playlist(
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
    await bot.add_cog(Music(bot))
