from typing import cast

import discord
import wavelink
from discord.ext import commands

import core
import log
from config import settings
from music import PandaPlayer, get_player


class Music(commands.Cog, name="🎶 Music"):
    def __init__(self, bot: core.Panda):
        self.bot: core.Panda = bot

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

        player = await get_player(ctx, embed)
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
            embed.description = f"Added [**{track.title}**]({track.uri}) by **{track.author}** to the queue."
            await ctx.send(embed=embed)

        if not player.playing:
            # Play now since we aren't playing anything...
            await player.play(player.queue.get())

    @commands.command(aliases=["s", "S"], brief="[n] Skip the current track, or n tracks.")
    @commands.guild_only()
    async def skip(self, ctx: commands.Context, n: int = 1) -> None:
        """Skip the current track, or with n the current track and the next n - 1 in the queue.
        Skipping more tracks than are queued skips them all."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if not player:
            await ctx.reply("I'm not even playing anything.")
            return

        if n < 1:
            await ctx.reply("I can only skip 1 track or more.")
            return

        # The current track counts as one, the rest come off the front of the queue
        del player.queue[: n - 1]
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


async def setup(bot):
    await bot.add_cog(Music(bot))
