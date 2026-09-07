import discord
import wavelink


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
