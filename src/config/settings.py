import discord

MAIN_COLOR = discord.Color.from_rgb(210, 140, 125)
ERROR_COLOR = discord.Color.from_rgb(250, 100, 120)

DEFAULT_PREFIX = "p!"

SCREENSHOT_COOLDOWN = 180  # seconds per user

# Event tags of 20-win challenges. A tag is shared by everyone playing that challenge, and every
# new 20-win challenge gets a new one: add it here (from a battle log's "eventTag") when it starts
TWENTY_WIN_EVENT_TAGS = {"#2CJUG2VL"}
