import discord
from discord.ext import commands

import core


class Settings(commands.Cog, name="⚙️ Settings"):
    """Change preferences for this bot."""

    def __init__(self, bot: core.Panda):
        self.bot: core.Panda = bot

    @commands.command(
        aliases=["sc"], brief="<on/off> Mark current channel as a screenshot channel."
    )
    @commands.guild_only()
    async def screenshot_channel(
        self, ctx: commands.Context, state: str | None = None
    ) -> None:
        """Mark the current channel as a screenshot channel.
        In a screenshot channel, the bot will attempt to search every image sent, no !screenshot needed.
        Useful to save save time and not type !screenshot/!s every time.
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
                await ctx.send(f"Channel {channel.name} is a screenshot channel.")
            else:
                await ctx.send(f"Channel {channel.name} is not a screenshot channel.")

            return

        if state.lower() == "on":
            add = await self.bot.db.add_image_channel(guild, channel)
            if add:
                await ctx.send(f"Channel {channel.name} is now a screenshot channel.")
            else:
                await ctx.send(
                    f"Channel {channel.name} was already a screenshot channel."
                )
        elif state.lower() == "off":
            remove = await self.bot.db.remove_image_channel(guild, channel)
            if remove:
                await ctx.send(
                    f"Channel {channel.name} is no longer a screenshot channel."
                )
            else:
                await ctx.send(f"Channel {channel.name} wasn't a screenshot channel.")
        else:
            await ctx.reply(f"Invalid state: `{state}`.")

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

        await self.bot.db.set_prefix(guild, prefix)
        self.bot.prefix_cache.pop(guild.id)
        await ctx.send(f"Changed the prefix to `{prefix}`.")


async def setup(bot):
    await bot.add_cog(Settings(bot))
