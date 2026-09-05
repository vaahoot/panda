import io
import time
from typing import cast

import aiohttp.client_exceptions
import anthropic
import discord
import wavelink
from discord.ext import commands

import database
import log
from clash import claude, screenshots
from clash.deck import generate_image
from clash.scraping import flaresolverr, search
from config import paths, settings, tokens
from music import PandaPlayer


class Panda(commands.Bot):
    def __init__(
        self,
        intents: discord.Intents,
        claude_client: anthropic.AsyncAnthropic,
        help_command: commands.HelpCommand,
    ):
        super().__init__(
            command_prefix=self.__get_prefix, intents=intents, help_command=help_command
        )
        self.prefix_cache = {}

        self.db = database.Database(paths.DATABASE, paths.SCHEMA)
        self.claude_client = claude_client
        self.template_gray, self.mask = screenshots.load_template(paths.SHIELD_TEMPLATE)

    async def __get_prefix(
        self, bot: commands.Bot, message: discord.Message
    ) -> list | str:
        assert bot is not None
        if not message.guild:
            return settings.DEFAULT_PREFIX

        if message.guild.id not in self.prefix_cache:
            prefix = await self.db.get_prefix(message.guild)
            self.prefix_cache[message.guild.id] = prefix

        assert self.user is not None
        return [
            self.prefix_cache[message.guild.id],
            f"<@{self.user.id}> ",
            f"<@!{self.user.id}> ",
        ]

    async def setup_hook(self) -> None:
        await self.load_extension("cogs.search")
        await self.load_extension("cogs.owner")
        await self.load_extension("cogs.settings")
        await self.load_extension("cogs.support")
        await self.load_extension("cogs.music")

        await flaresolverr.create_flaresolverr_session()

        await self.db.connect()
        await log.info(f"Database connected: {self.db.connection}")

        nodes = [
            wavelink.Node(uri="http://lavalink:2333", password=tokens.LAVALINK_PASSWORD)
        ]
        await wavelink.Pool.connect(nodes=nodes, client=self, cache_capacity=None)

    async def on_ready(self) -> None:
        assert self.user is not None
        await log.info(f"Logged in as: {self.user.name} | {self.user.id}")

        await self.change_presence(activity=discord.CustomActivity("I love bamBOO!"))

        for guild in self.guilds:
            await self.db.add_guild(guild)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        ctx = await self.get_context(message)
        if ctx.command is not None:
            await self.invoke(ctx)
            return

        guild = message.guild
        channel = message.channel
        attachments = message.attachments

        if (attachments is not None) and (
            guild is None or await self.db.is_image_channel(guild, channel)  # type: ignore
        ):
            await self.search_by_screenshot(message)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await log.info(f"Joined guild {guild.name}, id: {guild.id}")
        await self.db.add_guild(guild)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        await log.info(f"Left guild {guild.name}, id: {guild.id}")
        await self.db.remove_guild(guild)

    async def close(self) -> None:
        await flaresolverr.destroy_flaresolverr_session()
        if self.db.connection:
            await self.db.connection.close()

        await super().close()

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.errors.CommandInvokeError):
            error = error.original

        error_message = str(error).replace("'", "`")

        if isinstance(error, commands.errors.NoPrivateMessage):
            await ctx.reply(error_message)
        elif isinstance(error, commands.errors.CommandOnCooldown):
            await ctx.reply(f"Slow down! Try again in {error.retry_after:.0f} seconds")
        elif isinstance(
            error,
            (
                commands.errors.ExtensionAlreadyLoaded,
                commands.errors.ExtensionNotLoaded,
                commands.errors.ExtensionNotFound,
                aiohttp.client_exceptions.ClientResponseError,
            ),
        ):
            await ctx.reply(error_message)
        else:
            raise error

    async def search_by_info(
        self, name: str, clan: str | None, message: discord.Message
    ):
        start = time.time()

        await log.info(f"Searching for: {name}, Clan: {clan if clan else 'No clan'}")
        channel = message.channel

        async with channel.typing():
            deck = await search.find_deck(name, clan)

            if not deck:
                embed = discord.Embed(title="No deck Found", color=settings.ERROR_COLOR)
                embed.add_field(name="Name", value=name, inline=False)
                embed.add_field(name="Clan", value=clan, inline=False)
                await message.reply(embed=embed)
                return

            await log.info(f"Found deck for {name}: {[card['name'] for card in deck]}")
            deck_image = await generate_image.build_deck_image(deck)
            buffer = io.BytesIO()
            deck_image.save(buffer, format="PNG")
            buffer.seek(0)

        await message.reply(
            f"Name: {name}\nClan: {clan}",
            file=discord.File(buffer, filename="deck.png"),
        )

        time_taken = time.time() - start
        await log.info(f"Search by info took {time_taken:.2f}s")

    async def search_by_screenshot(self, message: discord.Message) -> None:
        start = time.time()

        attachments = message.attachments
        channel = message.channel

        if len(attachments) > 1:
            await message.reply("Please only send 1 image")
            return

        if not attachments[0].content_type.startswith("image/"):  # type: ignore
            await message.reply("Attachment must be an image")
            return

        async with channel.typing():
            url = attachments[0].url

            image_bytes = await screenshots.process_image(
                url, self.template_gray, self.mask
            )
            player_info = await claude.extract_player_info(
                self.claude_client, image_bytes
            )

            if player_info is None:
                await message.reply("Internal Error.")
                return

            name = player_info.get("name")
            clan = player_info.get("clan")

            if name is None:
                await log.error(f"Invalid image received: {url}")
                await message.reply("Invalid screenshot.")
                return

            await self.search_by_info(name, clan, message)

        time_taken = time.time() - start
        await log.info(f"Search by image took {time_taken:.2f}s")

    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        await log.info(
            f"Wavelink Node connected: {payload.node} | Resumed: {payload.resumed}"
        )

    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        player: wavelink.Player | None = payload.player
        if not player:
            return

        player = cast("PandaPlayer", player)
        if player.home is None:
            return

        track: wavelink.Playable = payload.track

        embed: discord.Embed = discord.Embed(color=settings.MAIN_COLOR)
        embed.description = f"Now playing **{track.title}** by **{track.author}**"

        await player.home.send(embed=embed)
