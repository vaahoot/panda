from discord.ext import commands


class Settings(commands.Cog, name="Settings ⚙️"):
    """Commands to change preferences for this bot."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=["sc"], brief="Mark current channel as a screenshot channel.")
    @commands.guild_only()
    async def screenshot_channel(self, ctx, state: str | None = None):
        guild = ctx.guild
        channel = ctx.channel

        if not state:
            image_channel = await self.bot.db.is_image_channel(channel, guild)
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
                await ctx.send(f"Channel {channel.name} was already a screenshot channel.")
        elif state.lower() == "off":
            remove = await self.bot.db.remove_image_channel(guild, channel)
            if remove:
                await ctx.send(f"Channel {channel.name} is no longer a screenshot channel.")
            else:
                await ctx.send(f"Channel {channel.name} wasn't a screenshot channel.")
        else:
            await ctx.reply(f"Invalid state {state}.")

    @commands.command(brief="Change the current comman prefix.")
    @commands.guild_only()
    async def prefix(self, ctx, prefix=None):
        guild = ctx.guild

        if prefix is None:
            current_prefix = await self.bot.db.get_prefix(guild)
            ctx.send(f"The current prefix is `{current_prefix}`.")
            return

        await self.bot.db.set_prefix(guild, prefix)
        self.bot.prefix_cache.pop(guild.id)
        await ctx.send(f"Changed the prefix to `{prefix}`.")


async def setup(bot):
    await bot.add_cog(Settings(bot))
