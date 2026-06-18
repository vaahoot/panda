import io
import time

import discord
from discord.ext import commands
from discord.ext.commands.errors import NoPrivateMessage
from playwright.async_api import Browser, Playwright, async_playwright

import helper
import search
from config import DATABASE, SCHEMA, SHIELD_TEMPLATE
from crop import load_template, process_image
from database import Database
from deck import build_deck_image
from gpt import extract_player_info
from helper import print_error, print_info


class CRBot(commands.Bot):
    def __init__(self, command_prefix, intents, gpt_client):
        super().__init__(command_prefix, intents=intents)
        self.browser: Browser | None = None
        self.playwright: Playwright | None = None
        self.db = Database(DATABASE, SCHEMA)
        self.gpt_client = gpt_client
        self.template_gray, self.mask = load_template(SHIELD_TEMPLATE)

    async def setup_hook(self):
        self.playwright = await async_playwright().start()
        await print_info(f"Created playwright: {self.playwright}")
        self.browser = await helper.init_browser(self.playwright)
        await print_info(f"Created a browser: {self.browser}")

        await self.db.connect()
        await print_info(f"Database connected: {self.db.connection}")

    async def on_ready(self):
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.competing, name="Guessing Clash Royale decks"))
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
                await self.search_by_image(message)

    async def on_guild_join(self, guild):
        await print_info(f"Joined guild {guild.name}, id: {guild.id}")
        await self.db.add_guild(guild)

    async def on_guild_remove(self, guild):
        await print_info(f"Left guild {guild.name}, id: {guild.id}")
        await self.db.remove_guild(guild)

    async def close(self):
        if self.browser:
            await self.browser.close()
            await print_info("Closed browser")
        if self.playwright:
            await self.playwright.stop()
            await print_info("Closed playwright")
        if self.db:
            await self.db.connection.close()

        await super().close()

    async def on_command_error(self, ctx, error):
        if isinstance(error, NoPrivateMessage):
            await ctx.send(error)
        else:
            raise error

    async def search_by_info(self, name: str, clan: str | None, message):
        assert self.browser is not None

        start = time.time()

        await print_info(f"Searching for: {name}, Clan: {clan if clan else 'No clan'}")
        channel = message.channel

        async with channel.typing():
            deck = await search.find_deck(self.browser, name, clan)

            if not deck:
                await message.reply("No deck found")
                return

            await print_info(f"Found deck for {name}: {[card['name'] for card in deck]}")
            deck_image = await build_deck_image(deck)
            buffer = io.BytesIO()
            deck_image.save(buffer, format="PNG")
            buffer.seek(0)

        await message.reply(file=discord.File(buffer, filename="deck.png"))

        time_taken = time.time() - start
        await print_info(f"Search by info took {time_taken:.2f}s")

    async def search_by_image(self, message):
        assert self.browser is not None

        start = time.time()

        attachments = message.attachments
        channel = message.channel

        async with channel.typing():
            url = attachments[0].url

            await print_info(f"Link sent to GPT: {url}")
            image_bytes = await process_image(url, self.template_gray, self.mask)
            player_info = await extract_player_info(self.gpt_client, image_bytes)

            if not player_info:
                await message.reply("Internal Error")
                return

            name = player_info.get("name")
            clan = player_info.get("clan")

            if not name:
                await print_error(f"Invalid image received: {url}")
                await message.reply("Invalid image")
                return

            await self.search_by_info(name, clan, message)

        time_taken = time.time() - start
        await print_info(f"Search by image took {time_taken:.2f}s")
