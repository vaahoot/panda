import discord
from discord.ext import commands


class CustomHelp(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        """Called when user runs !help"""
        embed = discord.Embed(
            title="Command list",
            color=discord.Color.dark_magenta(),
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

        await self.get_destination().send(embed=embed)

    async def send_cog_help(self, cog):
        """Called when user runs !help <cog>"""
        embed = discord.Embed(
            title=f"{cog.qualified_name} Commands",
            description=cog.description or "No description",
            color=discord.Color.dark_magenta(),
        )

        filtered = await self.filter_commands(cog.get_commands(), sort=True)
        for cmd in filtered:
            embed.add_field(
                name=cmd.name, value=cmd.brief or "No description", inline=False
            )

        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command):
        """Called when user runs !help <command>"""
        embed = discord.Embed(
            title=f"`{command.name}`",
            description=command.help or "No description",
            color=discord.Color.dark_magenta(),
        )
        if command.aliases:
            embed.add_field(
                name="Aliases", value=", ".join(f"`{a}`" for a in command.aliases)
            )
        if command.signature:
            embed.add_field(name="Usage", value=f"`{command.name} {command.signature}`")

        await self.get_destination().send(embed=embed)

    async def send_error_message(self, error):
        embed = discord.Embed(
            description=error, color=discord.Color.red()
        )
        await self.get_destination().send(embed=embed)
