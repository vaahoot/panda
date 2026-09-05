from typing import cast

import discord
import wavelink
from discord.ext import commands

from config import settings
from music import PandaPlayer


class Music(commands.Cog, name="🎶 Music"):
    @commands.command(aliases=["p"])
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Play a given song"""
        if ctx.guild is None:
            return
        if isinstance(ctx.channel, (discord.DMChannel, discord.GroupChannel)):
            return

        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if player is None:
            try:
                player = await ctx.author.voice.channel.connect(cls=PandaPlayer)
            except AttributeError:
                await ctx.send("At least join a voice channel man.")
                return
            except discord.ClientException:
                await ctx.send("I couldn't join the voice channel. Try again!")
                return

        player.autoplay = wavelink.AutoPlayMode.enabled

        # Lock the player to this voice channel
        if player.home is None:
            player.home = ctx.channel
        elif player.home != ctx.channel:
            await ctx.send(f"I'm already playing in {ctx.channel.mention}")
            return

        tracks: wavelink.Search = await wavelink.Playable.search(query)
        if not tracks:
            await ctx.reply(
                "Couldn't find any songs with that query. Please try again."
            )
            return

        if isinstance(tracks, wavelink.Playlist):
            # tracks is a playlist...
            added: int = await player.queue.put_wait(tracks)
            await ctx.send(
                f"Added the playlist **`{tracks.name}`** ({added} songs) to the queue."
            )
        else:
            track: wavelink.Playable = tracks[0]
            await player.queue.put_wait(track)
            await ctx.send(f"Added **`{track}`** to the queue.")

        if not player.playing:
            # Play now since we aren't playing anything...
            await player.play(player.queue.get())

    @commands.command()
    @commands.guild_only()
    async def skip(self, ctx: commands.Context) -> None:
        """Skip the current song."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if not player:
            await ctx.reply("I'm not even playing anything.")
            return

        await player.skip(force=True)
        await ctx.message.add_reaction("\u2705")

    @commands.command(name="toggle", aliases=["pause", "resume"])
    @commands.guild_only()
    async def toggle_pause(self, ctx: commands.Context) -> None:
        """Pause or Resume the Player depending on its current state."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if not player:
            await ctx.reply("I'm not even playing anything.")
            return

        await player.pause(not player.paused)
        await ctx.message.add_reaction("\u2705")

    @commands.command(aliases=["dc"])
    @commands.guild_only()
    async def disconnect(self, ctx: commands.Context) -> None:
        """Disconnect the Player."""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if player is None:
            await ctx.reply("Wasn't in the channel anyways.")
            return

        await player.disconnect()
        await ctx.message.add_reaction("\u2705")

    @commands.command(aliases=["q"])
    @commands.guild_only()
    async def queue(self, ctx: commands.Context) -> None:
        """Output the current queue"""
        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if player is None:
            await ctx.reply("Not playing anything right now.")
            return

        counter = 1
        embed: discord.Embed = discord.Embed(title="", color=settings.MAIN_COLOR)

        for track in player.queue:
            embed.add_field(
                name="",
                value=f"{counter}. **{track.title}** by **{track.author}**",
                inline=False,
            )
            counter += 1

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Music(bot))
