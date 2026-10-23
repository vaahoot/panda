from typing import cast

import discord
import wavelink
from discord.ext import commands


class PandaPlayer(wavelink.Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.home: (
            discord.TextChannel
            | discord.VoiceChannel
            | discord.StageChannel
            | discord.Thread
            | discord.PartialMessageable
            | None
        ) = None

        self.last_track: wavelink.Playable | None = None


async def get_player(
    ctx: commands.Context, embed: discord.Embed
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
