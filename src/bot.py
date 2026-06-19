import discord
from discord.ext import commands
from openai import AsyncOpenAI

from config import DISCORD_API_KEY
from CRBot import CRBot

if not DISCORD_API_KEY:
    raise ValueError("API key not found")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

ai_client = AsyncOpenAI()
bot = CRBot(command_prefix="!", intents=intents, gpt_client=ai_client)


# Command to find player's deck by name and clan
@bot.command(aliases=["d"])
async def deck(ctx):
    message = ctx.message.content
    message_without_command = message[2:]

    args = message_without_command.split(",")

    if len(args) == 2:
        name = args[0].strip()
        clan = args[1].strip()
    elif len(args) == 1:
        name = args[0].strip()
        clan = None
    else:
        await ctx.reply("Invalid number of arguments")
        return

    await bot.search_by_info(name, clan, ctx.message)


# Command to find player's deck by an image
@bot.command(aliases=["i"])
async def image(ctx):
    await bot.search_by_image(ctx.message)


@bot.command(aliases=["ic"])
@commands.guild_only()
async def image_channel(ctx, state: str | None = None):
    guild = ctx.guild
    channel = ctx.channel

    if not state:
        image_channel = await bot.db.is_image_channel(channel, guild)
        if image_channel:
            await ctx.send(f"Channel {channel.name} is an image channel")
        else:
            await ctx.send(f"Channel {channel.name} is not an image channel")

        return

    if state.lower() == "on":
        add = await bot.db.add_image_channel(guild, channel)
        if add:
            await ctx.send(f"Channel {channel.name} is now an image channel")
        else:
            await ctx.send(f"Channel {channel.name} was already an image channel")
    elif state.lower() == "off":
        remove = await bot.db.remove_image_channel(guild, channel)
        if remove:
            await ctx.send(f"Channel {channel.name} is no longer an image channel")
        else:
            await ctx.send(f"Channel {channel.name} wasn't an image channel")
    else:
        await ctx.reply(f"Invalid state {state}")


bot.run(DISCORD_API_KEY)
