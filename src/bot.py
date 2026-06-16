import asyncio

import discord
from openai import AsyncOpenAI
from pyvirtualdisplay.display import Display

from config import DISCORD_API_KEY, GPT_DEFAULT_VERSION
from CRBot import CRBot
from helper import print_error, print_info

if not DISCORD_API_KEY:
    raise ValueError("API key not found")

browser = None

intents = discord.Intents.default()
intents.message_content = True

try:
    display = Display(visible=False, size=(1920, 1080))
    display.start()
    asyncio.run(print_info(f"Virtual Display: {display}"))
except FileNotFoundError:
    asyncio.run(print_info("Xvfb not available, using built in screen"))

ai_client = AsyncOpenAI()
bot = CRBot(command_prefix="!", intents=intents, gpt_client=ai_client)


# Command to find player's deck by name and clan
@bot.command(aliases=["d"])
async def deck(ctx):
    if not bot.browser:
        await print_error("No browser is initialized")
        await ctx.reply("Internal Error")
        return

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
    if not bot.browser:
        await print_error("No browser is initialized")
        await ctx.reply("Internal Error")
        return

    await bot.search_by_image(ctx.message)


# Command to set the channel in which !i is not needed for the bot to start searching by screenshot.
@bot.command()
async def image_channel(ctx, state: str | None = None):
    guild_preferences = bot.get_preferences(ctx.guild.id)
    channels = guild_preferences.setdefault("imageChannels", [])

    channel = ctx.channel

    if not state:
        if channel.id in channels:
            await ctx.send(f"{channel.name} is an image channel")
        else:
            await ctx.send(f"{channel.name} is not an image channel")

        return

    if state.lower() == "on":
        if channel.id in channels:
            await ctx.reply(f"{channel.name} is already an image channel")
            return

        channels.append(channel.id)
        await bot.save_preferences()
        await print_info(
            f"Channel: {channel.name}, ID: {channel.id} was added to the image channels list"
        )
        await ctx.reply(f"Channel {channel.name} set as image channel")

    elif state.lower() == "off":
        if channel.id not in channels:
            await ctx.reply(f"Channel {channel.name} wasn't an image channel")
            return

        channels.remove(channel.id)
        await bot.save_preferences()
        await print_info(
            f"Channel: {channel.name}, ID: {channel.id} was removed from the image channels list"
        )
        await ctx.send(f"Channel {channel.name} is no longer an image channel")

    else:
        await ctx.reply("Invalid state")


@bot.command()
async def gpt(ctx, version: str | None = None):
    guild_preferences = bot.get_preferences(ctx.guild.id)
    current_version = guild_preferences.setdefault("gptVersion", GPT_DEFAULT_VERSION)

    if not version:
        await ctx.send(f"You are using: {current_version}")
    else:
        guild_preferences["gptVersion"] = version

        await bot.save_preferences()
        await ctx.send(f"GPT version set to: {version}")


bot.run(DISCORD_API_KEY)
