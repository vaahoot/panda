import discord

from config import settings

ROYALE_API_PLAYER = "https://royaleapi.com/player/{0}"
ROYALE_API_CLAN = "https://royaleapi.com/clan/{0}"

CLAN_ROLES = {
    "member": "Member",
    "elder": "Elder",
    "coLeader": "Co-leader",
    "leader": "Leader",
}

# Badge emoji shown for players without a clan
NO_CLAN_BADGE = "00000000"

# Path of Legends leagues by the API's leagueNumber
LEAGUES = [
    "Master I",
    "Master II",
    "Master III",
    "Champion",
    "Grand Champion",
    "Royal Champion",
    "Ultimate Champion",
]


def clan_badge(player: dict) -> str:
    """Name of the clan's badge emoji. Badge emojis are named by the API's badgeId."""
    clan = player.get("clan")
    return str(clan.get("badgeId")) if clan else NO_CLAN_BADGE


def clan_text(player: dict) -> str:
    """Empty for players without a clan, the heading says it."""
    clan = player.get("clan")
    if not clan:
        return ""
    role = CLAN_ROLES.get(player.get("role", ""), "Member")
    return f"{clan['name']} `{clan['tag']}`\n{role}"


def with_emoji(emojis: dict[str, str], name: str, text: str, after: bool = False) -> str:
    """Puts the named emoji before the text (or after it), if the bot has it."""
    emoji = emojis.get(name)
    if not emoji:
        return text
    return f"{text} {emoji}" if after else f"{emoji} {text}"


def trophies_text(player: dict, emojis: dict[str, str]) -> str:
    text = with_emoji(emojis, "trophy", f"**{player.get('trophies', 0):,}**", after=True)
    arena = (player.get("arena") or {}).get("name")
    return f"{text}\n{arena}" if arena else text


def rank_text(player: dict, emojis: dict[str, str]) -> str:
    """This season's and the best Path of Legends league, each with its league emoji."""
    lines = []
    for key, label in (
        ("currentPathOfLegendSeasonResult", "Current"),
        ("bestPathOfLegendSeasonResult", "Best"),
    ):
        league = (player.get(key) or {}).get("leagueNumber")
        if not league:
            continue
        if league > len(LEAGUES):
            # Leagues above 7 are 3 higher than the league they show as
            league -= 3
        name = LEAGUES[league - 1] if 1 <= league <= len(LEAGUES) else f"League {league}"
        # Subtext (-#) only works for a whole line, so the label goes underneath
        lines.append(f"-# *{label}*")
        lines.append(with_emoji(emojis, f"league{league}", f"**{name}**", after=True))
    return "\n".join(lines) or "Unranked"


def winrate_text(player: dict) -> str:
    wins, losses = player.get("wins", 0), player.get("losses", 0)
    if wins + losses == 0:
        return "No battles yet"
    return f"**{wins / (wins + losses):.1%}**\n{wins:,} W · {losses:,} L"


class ProfileView(discord.ui.LayoutView):
    """A player's profile card, from the CR API's /players/{tag} response."""

    def __init__(self, player: dict, emojis: dict[str, str]):
        """emojis are the bot's application emojis by name."""
        super().__init__(timeout=None)
        tag = player["tag"]

        title = discord.ui.TextDisplay(f"## {player['name']}\n`{tag}`")
        clan = player.get("clan")

        stats = [
            (
                with_emoji(emojis, clan_badge(player), "Clan" if clan else "No Clan"),
                clan_text(player),
            ),
            (with_emoji(emojis, "rank", "Ranked"), rank_text(player, emojis)),
            (with_emoji(emojis, "battle", "Trophy Road"), trophies_text(player, emojis)),
            (with_emoji(emojis, "crownblue", "Win Rate"), winrate_text(player)),
        ]

        buttons = discord.ui.ActionRow(
            discord.ui.Button(
                label="RoyaleAPI", url=ROYALE_API_PLAYER.format(tag.lstrip("#"))
            )
        )
        if clan:
            buttons.add_item(
                discord.ui.Button(
                    label="Clan", url=ROYALE_API_CLAN.format(clan["tag"].lstrip("#"))
                )
            )

        self.add_item(
            discord.ui.Container(
                title,
                discord.ui.Separator(),
                *(
                    discord.ui.TextDisplay(f"### {name}\n{value}" if value else f"### {name}")
                    for name, value in stats
                ),
                discord.ui.Separator(),
                buttons,
                accent_colour=settings.MAIN_COLOR,
            )
        )
