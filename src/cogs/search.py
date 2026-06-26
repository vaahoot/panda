from discord.ext import commands
from Panda import Panda


class Search(commands.Cog, name="🔎 Search"):
    """Search for decks."""
    def __init__(self, bot):
        self.bot: Panda = bot

    # TODO: Implement new syntax where !d name     means any clan
    #                                  !d name,    means no clan
    @commands.cooldown(rate=3, per=60, type=commands.BucketType.user)
    @commands.command(aliases=["d"], brief="Find a deck by nickname and clan")
    async def deck(self, ctx, *, query: str | None=None):
        """Searches an opponent's deck by name and clan.

        Both arguments can be partial matches if you can't enter some of the characters from either.

        Note that if clan is not given only players with no clan will be searched.

        Example: `!deck Ijihu, Lifetime`
        """
        if query is None:
            await ctx.reply("You need to provide a name and clan(optional)")
            return

        args = query.split(",")

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

    @commands.cooldown(rate=1, per=180, type=commands.BucketType.user)
    @commands.command(aliases=["s", "ss"], brief="Find a deck by screenshot")
    async def screenshot(self, ctx):
        """Searches an opponent's deck by a screenshot of the match.
        Useful if your opponent's name or clan is in a different language and contains symbols you cannot enter.

        Ideally someone who spectates will screenshot and send it to the bot.

        Example: `!screenshot <attach a screenshot>`"""
        attachments = ctx.attachments
        if not attachments:
            await ctx.reply("This command requires an image attached")
            return
        await self.bot.search_by_screenshot(ctx.message)


async def setup(bot):
    await bot.add_cog(Search(bot))
