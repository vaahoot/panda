import io
import os
import time

import discord
from discord.ext.commands import Bot
from discord.ext.commands.errors import NoPrivateMessage

import search
from config import COGS, DATABASE, DEFAULT_PREFIX, SCHEMA, SHIELD_TEMPLATE
from crop import load_template, process_image
from database import Database
from deck import build_deck_image
from gpt import extract_player_info
from helper import print_error, print_info


class CRBot(Bot):
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
        if not message.guild:
            return DEFAULT_PREFIX

        if message.guild.id not in self.prefix_cache:
            row = await self.db.get_prefix(message.guild)
            self.prefix_cache[message.guild.id] = row[0] if row else "!"

        return self.prefix_cache[message.guild.id]

    async def setup_hook(self):
        for file in os.listdir(COGS):
            if file.endswith(".py") and file != "__init__.py":
                await self.load_extension(f"cogs.{file[:-3]}")

        await search.create_flaresolverr_session()

        await self.db.connect()
        await print_info(f"Database connected: {self.db.connection}")

    async def on_ready(self):
        assert self.user is not None
        await print_info(f"Logged in as: {self.user.name}:{self.user.id}")

        await self.change_presence(activity=discord.CustomActivity("Let's play some Clash Royale | !help"))

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

    async def on_command_error(self, ctx, error):
        if isinstance(error, NoPrivateMessage):
            await ctx.send(error)
        else:
            raise error

    async def search_by_info(self, name: str, clan: str | None, message):
        start = time.time()

        await print_info(f"Searching for: {name}, Clan: {clan if clan else 'No clan'}")
        channel = message.channel

        async with channel.typing():
            deck = await search.find_deck(name, clan)

            if not deck:
                await message.reply("No deck found.")
                return

            await print_info(f"Found deck for {name}: {[card['name'] for card in deck]}")
            deck_image = await build_deck_image(deck)
            buffer = io.BytesIO()
            deck_image.save(buffer, format="PNG")
            buffer.seek(0)

        await message.reply(file=discord.File(buffer, filename="deck.png"))

        time_taken = time.time() - start
        await print_info(f"Search by info took {time_taken:.2f}s")

    async def search_by_screenshot(self, message):
        start = time.time()

        attachments = message.attachments
        channel = message.channel

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
