import io
import time

import discord
from discord.ext import commands
from playwright.async_api import Browser, Playwright, async_playwright

import helper
import search
from config import GPT_DEFAULT_VERSION, SHIELD_TEMPLATE
from crop import load_template, process_image
from deck import build_deck_image
from gpt import extract_player_info
from helper import load_preferences, print_error, print_info, save_preferences


class CRBot(commands.Bot):
    def __init__(self, command_prefix, intents, gpt_client):
        super().__init__(command_prefix, intents=intents)
        self.browser: Browser | None = None
        self.playwright: Playwright | None = None
        self.gpt_client = gpt_client
        self.template_gray, self.mask = load_template(SHIELD_TEMPLATE)

    async def setup_hook(self):
        self.playwright = await async_playwright().start()
        await print_info(f"Created playwright: {self.playwright}")
        self.browser = await helper.init_browser(self.playwright)
        await print_info(f"Created a browser: {self.browser}")

        self.preferences = load_preferences()
        await print_info("Preferences loaded")

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
        guild = message.guild

        async with channel.typing():
            url = attachments[0].url
            preferences = self.get_preferences(guild.id)
            gpt_version = preferences.setdefault("gptVersion", GPT_DEFAULT_VERSION )

            await print_info(f"Link sent to GPT: {url}")
            image_bytes = await process_image(url, self.template_gray, self.mask)
            player_info = await extract_player_info(self.gpt_client, image_bytes, gpt_version)

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

    async def save_preferences(self):
        await save_preferences(self.preferences)

    def get_preferences(self, guild_id: int):
        """Return a list of all preferences saved in the bot for a given guild"""
        guild_key = str(guild_id)
        return self.preferences.setdefault(guild_key, {})

    async def on_message(self, message):
        if message.author == self.user:
            return

        guild = message.guild.id
        channel = message.channel.id
        preferences = self.get_preferences(guild)

        if (channel in preferences.setdefault("imageChannels", []) and message.attachments):
            await self.search_by_image(message)

        await self.process_commands(message)

    async def close(self):
        if self.browser:
            await self.browser.close()
            await print_info("Closed browser")
        if self.playwright:
            await self.playwright.stop()
            await print_info("Closed playwright")

        await super().close()
