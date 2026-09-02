import anthropic
import discord

import core
from config import tokens

if not tokens.DISCORD_API_KEY:
    raise ValueError("API key not found")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

claude_client = anthropic.AsyncAnthropic()

bot = core.Panda(
    intents=intents, claude_client=claude_client, help_command=core.CustomHelp()
)
bot.run(tokens.DISCORD_API_KEY)
