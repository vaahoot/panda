import discord
import wavelink


class PandaPlayer(wavelink.Player):
    home: discord.TextChannel | None = None
