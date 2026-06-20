import discord
from openai import AsyncOpenAI

from config import DISCORD_API_KEY
from CRBot import CRBot
from CustomHelp import CustomHelp

if not DISCORD_API_KEY:
    raise ValueError("API key not found")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

ai_client = AsyncOpenAI()

bot = CRBot(intents=intents, gpt_client=ai_client, help_command=CustomHelp())
bot.run(DISCORD_API_KEY)
