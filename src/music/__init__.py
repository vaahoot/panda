import discord
import wavelink


class PandaPlayer(wavelink.Player):
    home: (
        discord.TextChannel
        | discord.VoiceChannel
        | discord.StageChannel
        | discord.Thread
        | discord.PartialMessageable
        | None
    ) = None
