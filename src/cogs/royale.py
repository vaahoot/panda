import re

import aiohttp
import discord
from discord.ext import commands

import core
import log
from clash import player as cr_player
from clash.profile_view import ProfileView
from config import settings

USER_MENTION = re.compile(r"<@!?\d+>")


class Royale(commands.Cog, name="👑 Royale"):
    """Clash Royale players and profiles."""

    def __init__(self, bot: core.Panda):
        self.bot: core.Panda = bot
        # The bot's application emojis by name, e.g. "trophy", "league1", "league2", ...
        self.emojis: dict[str, str] = {}

    async def cog_load(self) -> None:
        try:
            emojis = await self.bot.fetch_application_emojis()
        except discord.HTTPException as e:
            # Profiles still work, just without emojis
            await log.warning(f"Couldn't fetch the application emojis: {e}")
            return
        self.emojis = {emoji.name: str(emoji) for emoji in emojis}

    async def fetch_player(self, ctx: commands.Context, tag: str) -> dict | None:
        """Validates the tag and gets the player from the CR API.
        Replies with an error embed and returns None if there's no such player."""
        normalised = cr_player.normalise_tag(tag)
        if normalised is None:
            embed = discord.Embed(
                description=f"`{discord.utils.escape_markdown(tag)}` isn't a valid player tag. "
                "Tags look like `#2PP` and only use the characters `0289PYLQGRJCUV`.",
                color=settings.ERROR_COLOR,
            )
            await ctx.reply(embed=embed)
            return None

        try:
            player = await cr_player.get_player(normalised)
        except aiohttp.ClientResponseError as e:
            if e.status != 404:
                raise
            embed = discord.Embed(
                description=f"No player found with the tag `{normalised}`.",
                color=settings.ERROR_COLOR,
            )
            await ctx.reply(embed=embed)
            return None

        # Makes the player findable by deck search, and their clan crawlable
        clan = player.get("clan") or {}
        await self.bot.db.add_player_if_missing(
            player["tag"], player["name"], clan.get("tag"), clan.get("name")
        )
        return player

    @commands.command(brief="<tag> Show or set your Clash Royale tag.")
    async def mytag(self, ctx: commands.Context, tag: str | None = None) -> None:
        """Shows your saved Clash Royale player tag, or saves a new one if you give it.

        Example: `!mytag #2PP`"""
        if tag is None:
            saved = await self.bot.db.get_cr_tag(ctx.author)
            if saved is None:
                embed = discord.Embed(
                    title="No tag saved",
                    description="You haven't saved your Clash Royale tag yet. "
                    f"Save it with `{ctx.clean_prefix}mytag <tag>`.",
                    color=settings.ERROR_COLOR,
                )
            else:
                embed = discord.Embed(
                    title="Your tag", description=f"`{saved}`", color=settings.MAIN_COLOR
                )
            await ctx.reply(embed=embed)
            return

        async with ctx.typing():
            player = await self.fetch_player(ctx, tag)
            if player is None:
                return
            await self.bot.db.set_cr_tag(ctx.author, player["tag"])

        embed = discord.Embed(
            title="Tag saved",
            description=f"Your tag is now `{player['tag']}` "
            f"(**{discord.utils.escape_markdown(player['name'])}**).",
            color=settings.MAIN_COLOR,
        )
        await ctx.reply(embed=embed)

    @commands.command(brief="<tag> Show a Clash Royale player's profile.")
    async def profile(self, ctx: commands.Context, tag: str | None = None) -> None:
        """Shows a player's profile: name, clan, rank, trophies and win rate.
        Without a tag, shows your own profile if you've saved your tag with mytag.
        Mention someone instead of a tag to see the profile they saved.

        Example: `!profile #2PP` or `!profile @someone`"""
        if tag is not None and USER_MENTION.fullmatch(tag):
            try:
                user = await commands.UserConverter().convert(ctx, tag)
            except commands.UserNotFound:
                user = None
            tag = await self.bot.db.get_cr_tag(user) if user else None
            if tag is None:
                # Mentions in embeds never ping
                who = user.mention if user else "That user"
                embed = discord.Embed(
                    description=f"{who} hasn't saved their Clash Royale tag yet.",
                    color=settings.ERROR_COLOR,
                )
                await ctx.reply(embed=embed)
                return
        elif tag is None:
            tag = await self.bot.db.get_cr_tag(ctx.author)
            if tag is None:
                embed = discord.Embed(
                    description="Give me a player tag, or save yours with "
                    f"`{ctx.clean_prefix}mytag <tag>` to see your own profile.",
                    color=settings.ERROR_COLOR,
                )
                await ctx.reply(embed=embed)
                return

        async with ctx.typing():
            player = await self.fetch_player(ctx, tag)
        if player is None:
            return

        await ctx.reply(view=ProfileView(player, self.emojis))


async def setup(bot):
    await bot.add_cog(Royale(bot))
