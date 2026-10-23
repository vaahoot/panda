import io
import time

import aiohttp.client_exceptions
import anthropic
import discord
import wavelink
from discord.ext import commands

import database
import log
import net
from clash import claude, screenshots
from clash.deck import generate_image
from clash.deck import views as deck_views
from clash.scraping import search
from config import paths, settings, tokens


# Name, player tag, clan name, clan tag
PlayerInfo = tuple[str, str | None, str | None, str | None]


def describe_player(player: dict | None, name: str, clan: str | None) -> PlayerInfo:
    """The player's real name and clan with their tags, or the ones searched for (without tags)
    when the player wasn't found."""
    if player is None:
        return name, None, clan, None
    player_clan = player.get("clan") or {}
    return player["name"], player.get("tag"), player_clan.get("name"), player_clan.get("tag")


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

        # Shared between !screenshot, screenshot channels and DMs
        self.screenshot_cooldown = commands.CooldownMapping.from_cooldown(
            1, settings.SCREENSHOT_COOLDOWN, commands.BucketType.user
        )

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
        await self.load_extension("cogs.royale")

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

        if attachments and (
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
        await net.close()
        if self.db.connection:
            await self.db.connection.close()

        await super().close()

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.errors.CommandInvokeError):
            error = error.original

        error_message = str(error).replace("'", "`")

        if isinstance(
            error, (commands.errors.NoPrivateMessage, commands.errors.MissingPermissions)
        ):
            await ctx.reply(error_message)
        elif isinstance(error, commands.errors.MissingRequiredArgument):
            embed = discord.Embed(
                description=f"Missing argument `{error.param.name}`. "
                f"Usage: `{ctx.clean_prefix}{ctx.command} {ctx.command.signature if ctx.command else ''}`",
                color=settings.ERROR_COLOR,
            )
            await ctx.reply(embed=embed)
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
            found = await search.find_deck(self.db, name, clan)
            decks, player = found or ({}, None)
            info = describe_player(player, name, clan)

            if not decks:
                await self.reply_no_deck(info, message, player_found=found is not None)
                return

            await self.reply_with_decks(decks, info, message)

        time_taken = time.time() - start
        await log.info(f"Search by info took {time_taken:.2f}s")

    async def search_by_tag(self, tag: str, message: discord.Message) -> bool:
        """Shows the deck of the player with this tag. False if no player has it."""
        start = time.time()

        await log.info(f"Searching for tag: {tag}")
        async with message.channel.typing():
            found = await search.find_deck_by_tag(self.db, tag)
            if found is None:
                await log.info(f"No player with tag {tag}")
                return False
            decks, player = found
            # Without the player's details there's only the tag to show
            info = describe_player(player, tag, None)

            if not decks:
                await self.reply_no_deck(info, message)
                return True

            await self.reply_with_decks(decks, info, message)

        time_taken = time.time() - start
        await log.info(f"Search by tag took {time_taken:.2f}s")
        return True

    async def reply_no_deck(
        self, info: PlayerInfo, message: discord.Message, player_found: bool = True
    ) -> None:
        embed = discord.Embed(
            title="No Deck Found" if player_found else "No Player Found",
            description=deck_views.player_text(*info),
            color=settings.ERROR_COLOR,
        )
        await message.reply(embed=embed)

    async def reply_with_decks(
        self, decks: dict[str, list[dict]], info: PlayerInfo, message: discord.Message
    ) -> None:
        name, name_tag, clan, clan_tag = info
        for deck_mode, deck in decks.items():
            await log.info(f"Found {deck_mode} deck for {name}: {[card['name'] for card in deck]}")
        mode = deck_views.first_mode(decks)
        image = (await generate_image.build_deck_image(decks[mode])).getvalue()

        file = discord.File(io.BytesIO(image), filename=deck_views.DECK_IMAGE_FILENAME)
        view = deck_views.DeckView(decks, mode, image, name, name_tag, clan, clan_tag)
        view.message = await message.reply(file=file, view=view)
        if len(decks) > 1:
            # Both ranked and ladder decks: ranked is showing, get the other one ready
            view.prebuild()

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

        bucket = self.screenshot_cooldown.get_bucket(message)
        retry_after = bucket.update_rate_limit() if bucket else None
        if retry_after:
            await message.reply(f"Slow down! Try again in {retry_after:.0f} seconds")
            return

        async with channel.typing():
            url = attachments[0].url

            image_bytes = await screenshots.process_image(
                await attachments[0].read(), self.template_gray, self.mask
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

