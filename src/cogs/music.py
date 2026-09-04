from typing import cast

import discord
import wavelink
from discord.ext import commands

import log
from music import PandaPlayer


class Music(commands.Cog, name="🎶 Music"):
    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        await log.info(
            f"Wavelink Node connected: {payload.node} | Resumed: {payload.resumed}"
        )

    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        player: wavelink.Player | None = payload.player
        if not player:
            return

        player = cast("PandaPlayer", player)

        original: wavelink.Playable | None = payload.original
        track: wavelink.Playable = payload.track

        embed: discord.Embed = discord.Embed(title="Now Playing")
        embed.description = f"**{track.title}** by `{track.author}`"

        if track.artwork:
            embed.set_image(url=track.artwork)

        if original and original.recommended:
            embed.description += f"\n\n`This track was recommended via {track.source}`"

        if track.album.name:
            embed.add_field(name="Album", value=track.album.name)

        if player.home is None:
            return

        await player.home.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        if ctx.guild is None:
            return

        player: PandaPlayer = cast("PandaPlayer", ctx.voice_client)
        if player is None:
            try:
                player = await ctx.author.voice.channel.connect(cls=PandaPlayer)
            except AttributeError:
                await ctx.send(
                    "At least join a voice channel man."
                )
                return
            except discord.ClientException:
                await ctx.send(
                    "I couldn't join the voice channel. Try again!"
                )
                return

        player.autoplay = wavelink.AutoPlayMode.enabled

        # Lock the player to this voice channel
        if player.home is None:
            player.home = ctx.channel
        elif player.home != ctx.channel:
            await ctx.send(f"I'm already playing in {ctx.channel.mention}")
            return

        tracks: wavelink.Search = await wavelink.Playable.search(query, source="ytsearch")
        if not tracks:
            await ctx.reply("Couldn't find any songs with that query. Please try again.")
            return

        if isinstance(tracks, wavelink.Playlist):
            # tracks is a playlist...
            added: int = await player.queue.put_wait(tracks)
            await ctx.send(f"Added the playlist **`{tracks.name}`** ({added} songs) to the queue.")
        else:
            track: wavelink.Playable = tracks[0]
            await player.queue.put_wait(track)
            await ctx.send(f"Added **`{track}`** to the queue.")

        if not player.playing:
            # Play now since we aren't playing anything...
            await player.play(player.queue.get())


async def setup(bot):
    await bot.add_cog(Music(bot))
