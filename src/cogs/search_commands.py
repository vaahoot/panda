from discord.ext import commands
from CRBot import CRBot


class Search(commands.Cog, name="Search 🔎"):
    """Commands to search for decks."""
    def __init__(self, bot):
        self.bot: CRBot = bot

    @commands.command(aliases=["d"], brief="Find a deck by nickname and clan")
    async def deck(self, ctx):
        """Searches an opponent's deck by name and clan.

        Both arguments can be partial matches if you can't enter some of the characters from either.

        Note that if clan is not given only players with no clan will be searched.

        Example: `!deck Ijihu, Lifetime`
        """
        message = ctx.message.content
        message_without_command = message[2:]

        args = message_without_command.split(",")

        if len(args) == 2:
            name = args[0].strip()
            clan = args[1].strip()
        elif len(args) == 1:
            name = args[0].strip()
            clan = None
        else:
            await ctx.reply("Invalid number of arguments.")
            return

        await self.bot.search_by_info(name, clan, ctx.message)

    @commands.command(aliases=["s", "ss"], brief="Find a deck by screenshot")
    async def screenshot(self, ctx):
        """Searches an opponent's deck by a screenshot of the match.
        Useful if your opponent's name or clan is in a different language and contains symbols you cannot enter.

        Ideally someone who spectates will screenshot and send it to the bot.

        Example: `!screenshot <attach a screenshot>`"""
        await self.bot.search_by_screenshot(ctx.message)

async def setup(bot):
    await bot.add_cog(Search(bot))
