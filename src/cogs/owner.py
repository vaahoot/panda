import discord
from discord.ext import commands

from Panda import Panda
from config import MAIN_COLOR


class Owner(commands.Cog, name="🐼 Owner"):
    """Owner commands."""
    def __init__(self, bot):
        self.bot: Panda = bot

    @commands.command()
    @commands.is_owner()
    async def list_guilds(self, ctx):
        embed = discord.Embed(title=f"Guilds: {len(self.bot.guilds)}", color=MAIN_COLOR)

        for guild in self.bot.guilds:
            embed.add_field(
                name="",
                value=f"{guild.id}: {guild.name}\n",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def leave_guild(self, ctx, guild_id: int):
        for guild in self.bot.guilds:
            if guild.id == guild_id:
                await guild.leave()
                await ctx.reply("Left guild")
                return

        await ctx.reply("Not in this guild")

    @commands.command()
    @commands.is_owner()
    async def reload(self, ctx, cog: str):
        await self.bot.reload_extension(f"cogs.{cog}")
        await ctx.reply(f"Reloaded {cog}")

    @commands.command()
    @commands.is_owner()
    async def load(self, ctx, cog: str):
        await self.bot.load_extension(f"cogs.{cog}")
        await ctx.reply(f"Loaded {cog}")

    @commands.command()
    @commands.is_owner()
    async def unload(self, ctx, cog: str):
        await self.bot.unload_extension(f"cogs.{cog}")
        await ctx.reply(f"Unloaded {cog}")

    @commands.command()
    @commands.is_owner()
    async def setstatus(self, ctx, *, status: str):
        await self.bot.change_presence(activity=discord.CustomActivity(status))
        await ctx.reply("Status updated")

    @commands.command()
    @commands.is_owner()
    async def shutdown(self, ctx):
        await ctx.reply("Shutting down...")
        await self.bot.close()

    @commands.command()
    @commands.is_owner()
    async def stats(self, ctx):
        embed = discord.Embed(title="Panda Stats", color=MAIN_COLOR)
        embed.add_field(name="Servers", value=len(self.bot.guilds))
        embed.add_field(name="Users", value=len(self.bot.users))
        embed.add_field(name="Ping", value=f"{self.bot.latency * 1000:.0f}ms")
        await ctx.send(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def list_users(self, ctx):
        res = ""
        for user in self.bot.users:
            res += f"{user.name}\n"
        await ctx.send(res)

async def setup(bot):
    await bot.add_cog(Owner(bot))
