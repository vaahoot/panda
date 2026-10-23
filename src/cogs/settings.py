import discord
from discord.ext import commands

import core

# Only checked when changing a setting, viewing doesn't need permissions
can_manage_guild = commands.has_guild_permissions(manage_guild=True).predicate


class Settings(commands.Cog, name="⚙️ Settings"):
    """Change preferences for this bot."""

    def __init__(self, bot: core.Panda):
        self.bot: core.Panda = bot

    @commands.command(
        aliases=["as"], brief="<on/off> Search every image sent in this channel."
    )
    @commands.guild_only()
    async def autoscan(
        self, ctx: commands.Context, state: str | None = None
    ) -> None:
        """Turn autoscan on or off for the current channel.
        With autoscan on, the bot searches every image sent in the channel, no !screenshot needed.
        Without on/off, shows whether autoscan is on here.
        """
        guild = ctx.guild
        channel = ctx.channel

        if not isinstance(channel, discord.TextChannel):
            return
        if guild is None:
            return

        if not state:
            image_channel = await self.bot.db.is_image_channel(guild, channel)
            if image_channel:
                await ctx.send(f"Autoscan is on in {channel.mention}.")
            else:
                await ctx.send(f"Autoscan is off in {channel.mention}.")

            return

        await can_manage_guild(ctx)

        if state.lower() == "on":
            add = await self.bot.db.add_image_channel(guild, channel)
            if add:
                await ctx.send(f"Autoscan is now on in {channel.mention}.")
            else:
                await ctx.send(f"Autoscan was already on in {channel.mention}.")
        elif state.lower() == "off":
            remove = await self.bot.db.remove_image_channel(guild, channel)
            if remove:
                await ctx.send(f"Autoscan is now off in {channel.mention}.")
            else:
                await ctx.send(f"Autoscan was already off in {channel.mention}.")
        else:
            await ctx.reply(f"Invalid state: `{state}`. Use `on` or `off`.")

    @commands.command(brief="Change the current command prefix.")
    @commands.guild_only()
    async def prefix(self, ctx: commands.Context, prefix: str | None = None) -> None:
        guild = ctx.guild
        if guild is None:
            return

        if prefix is None:
            current_prefix = await self.bot.db.get_prefix(guild)
            await ctx.send(f"The current prefix is `{current_prefix}`.")
            return

        await can_manage_guild(ctx)

        await self.bot.db.set_prefix(guild, prefix)
        self.bot.prefix_cache.pop(guild.id)
        await ctx.send(f"Changed the prefix to `{prefix}`.")


async def setup(bot):
    await bot.add_cog(Settings(bot))
