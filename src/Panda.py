import io
import os
import time

import discord
from discord.ext.commands import Bot, Context
from discord.ext.commands import errors

import search
from config import COGS, DATABASE, DEFAULT_PREFIX, ERROR_COLOR, SCHEMA, SHIELD_TEMPLATE
from crop import load_template, process_image
from database import Database
from deck import build_deck_image
from gpt import extract_player_info
from helper import print_error, print_info

COG_COUNT = len(
    [file for file in os.listdir(COGS) if file.endswith(".py")]
)
COGS_LIST = [
    "search",
    "settings",
    "support",
    "owner"
]
assert COG_COUNT == len(COGS_LIST), "New Cog was added but not added to the load list"


class Panda(Bot):
    def __init__(self, intents, gpt_client, help_command):
        super().__init__(
            command_prefix=self.__get_prefix,
            intents=intents,
            help_command=help_command
        )
        self.prefix_cache = {}

        self.db = Database(DATABASE, SCHEMA)
        self.gpt_client = gpt_client
        self.template_gray, self.mask = load_template(SHIELD_TEMPLATE)

    async def __get_prefix(self, bot, message):
        assert bot is not None
        if not message.guild:
            return DEFAULT_PREFIX

        if message.guild.id not in self.prefix_cache:
            prefix = await self.db.get_prefix(message.guild)
            self.prefix_cache[message.guild.id] = prefix

        assert self.user is not None
        return [self.prefix_cache[message.guild.id], f"<@{self.user.id}> ", f"<@!{self.user.id}> "]

    async def setup_hook(self):
        for cog in COGS_LIST:
            await self.load_extension(f"cogs.{cog}")

        await search.create_flaresolverr_session()

        await self.db.connect()
        await print_info(f"Database connected: {self.db.connection}")

    async def on_ready(self):
        assert self.user is not None
        await print_info(f"Logged in as: {self.user.name}:{self.user.id}")

        await self.change_presence(activity=discord.CustomActivity("Let's play some Clash Royale!"))

        for guild in self.guilds:
            await self.db.add_guild(guild)

    async def on_message(self, message):
        if message.author.bot:
            return

        ctx = await self.get_context(message)
        if ctx.command is not None:
            await self.invoke(ctx)
            return

        guild = message.guild
        channel = message.channel
        attachments = message.attachments

        if attachments:
            if guild is None or await self.db.is_image_channel(channel, guild):
                await self.search_by_screenshot(message)

    async def on_guild_join(self, guild):
        await print_info(f"Joined guild {guild.name}, id: {guild.id}")
        await self.db.add_guild(guild)

    async def on_guild_remove(self, guild):
        await print_info(f"Left guild {guild.name}, id: {guild.id}")
        await self.db.remove_guild(guild)

    async def close(self):
        await search.destroy_flaresolverr_session()
        if self.db.connection:
            await self.db.connection.close()

        await super().close()

    async def on_command_error(self, ctx: Context, error: Exception):
        if isinstance(error, errors.CommandInvokeError):
            error = error.original

        error_message = str(error).replace("'", "`")

        if isinstance(error, errors.NoPrivateMessage):
            await ctx.reply(error_message)
        elif isinstance(error, errors.CommandOnCooldown):
            await ctx.reply(f"Slow down! Try again in {error.retry_after:.0f} seconds")
        elif isinstance(error, errors.ExtensionAlreadyLoaded):
            await ctx.reply(error_message)
        elif isinstance(error, errors.ExtensionNotLoaded):
            await ctx.reply(error_message)
        elif isinstance(error, errors.ExtensionNotFound):
            await ctx.reply(error_message)
        else:
            raise error

    async def search_by_info(self, name: str, clan: str | None, message):
        start = time.time()

        await print_info(f"Searching for: {name}, Clan: {clan if clan else 'No clan'}")
        channel = message.channel

        async with channel.typing():
            deck = await search.find_deck(name, clan)

            if not deck:
                embed = discord.Embed(title="No deck Found", color=ERROR_COLOR)
                embed.add_field(name="Name", value=name, inline=False)
                embed.add_field(name="Clan", value=clan, inline=False)
                await message.reply(embed=embed)
                return

            await print_info(f"Found deck for {name}: {[card['name'] for card in deck]}")
            deck_image = await build_deck_image(deck)
            buffer = io.BytesIO()
            deck_image.save(buffer, format="PNG")
            buffer.seek(0)

        await message.reply(
            f"Name: {name}\nClan: {clan}",
            file=discord.File(buffer, filename="deck.png")
        )

        time_taken = time.time() - start
        await print_info(f"Search by info took {time_taken:.2f}s")

    async def search_by_screenshot(self, message):
        start = time.time()

        attachments = message.attachments
        channel = message.channel

        if len(attachments) > 1:
            await message.reply("Please only send 1 image")
            return

        if not attachments[0].content_type.startswith("image/"):
            await message.reply("Attachment must be an image")
            return

        async with channel.typing():
            url = attachments[0].url

            await print_info(f"Link sent to GPT: {url}")
            image_bytes = await process_image(url, self.template_gray, self.mask)
            player_info = await extract_player_info(self.gpt_client, image_bytes)

            if not player_info:
                await message.reply("Internal Error.")
                return

            name = player_info.get("name")
            clan = player_info.get("clan")

            if not name:
                await print_error(f"Invalid image received: {url}")
                await message.reply("Invalid screenshot.")
                return

            await self.search_by_info(name, clan, message)

        time_taken = time.time() - start
        await print_info(f"Search by image took {time_taken:.2f}s")
