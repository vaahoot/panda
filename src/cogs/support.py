import discord
from discord.ext import commands

import core
from config.settings import MAIN_COLOR


class SupportView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(
            discord.ui.Button(
                label="Support me on Ko-Fi",
                url="https://ko-fi.com/justsomechilldude",
                style=discord.ButtonStyle.link,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Invite Panda",
                url="https://discord.com/oauth2/authorize?client_id=640995166441832508&permissions=117824&integration_type=0&scope=bot",
                style=discord.ButtonStyle.link,
            )
        )


class Support(commands.Cog, name="💸 Support"):
    """Support the developer."""

    def __init__(self, bot: core.Panda):
        self.bot: core.Panda = bot

    @commands.command(aliases=["donate"], brief="Get a link to support me.")
    async def support(self, ctx: commands.Context):
        """Get a link to support me."""
        embed = discord.Embed(
            description="If you enjoy Panda, consider supporting me!", color=MAIN_COLOR
        )
        await ctx.send(embed=embed, view=SupportView())


async def setup(bot):
    await bot.add_cog(Support(bot))
