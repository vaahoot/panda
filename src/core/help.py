from typing import cast

import discord
from discord.ext import commands

from cogs.support import SupportView
from config import settings

from .panda import Panda


class CustomHelp(commands.HelpCommand):
    async def send_bot_help(self, mapping) -> None:
        """Called when user runs !help"""
        embed = discord.Embed(
            title="Command list",
            color=settings.MAIN_COLOR,
        )

        for cog, cmds in mapping.items():
            filtered = await self.filter_commands(cmds, sort=True)
            if not filtered:
                continue
            cog_name = getattr(cog, "qualified_name", "Misc")
            embed.add_field(
                name=cog_name,
                value="\n".join(
                    f"`{c.name}` — {c.brief or 'No description'}" for c in filtered
                ),
                inline=False,
            )

        bot = cast("Panda", self.context.bot)
        guild_id = self.context.guild.id if self.context.guild else None
        prefix = (
            bot.prefix_cache.get(guild_id, settings.DEFAULT_PREFIX)
            if guild_id
            else settings.DEFAULT_PREFIX
        )
        embed.add_field(name="", value=f"For more info, run {prefix}help command name")

        await self.get_destination().send(embed=embed, view=SupportView())

    async def send_cog_help(self, cog: commands.Cog) -> None:
        """Called when user runs !help <cog>"""
        embed = discord.Embed(
            title=f"{cog.qualified_name} Commands",
            description=cog.description or "No description",
            color=settings.MAIN_COLOR,
        )

        filtered = await self.filter_commands(cog.get_commands(), sort=True)
        for cmd in filtered:
            embed.add_field(
                name=cmd.name, value=cmd.brief or "No description", inline=False
            )

        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command: commands.Command) -> None:
        """Called when user runs !help <command>"""
        embed = discord.Embed(
            title=f"`{command.name}`",
            description=command.help or "No description",
            color=settings.MAIN_COLOR,
        )
        if command.aliases:
            embed.add_field(
                name="Aliases", value=", ".join(f"`{a}`" for a in command.aliases)
            )

        await self.get_destination().send(embed=embed)

    async def send_error_message(self, error: str) -> None:
        embed = discord.Embed(description=error, color=settings.ERROR_COLOR)
        await self.get_destination().send(embed=embed)
