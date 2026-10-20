import asyncio
import unicodedata
import urllib.parse

import aiohttp
import bs4

import log
import net
from clash.deck import get_deck
from config import search_settings
from database import Database

from . import flaresolverr


# Accents and overlays (strikethrough, slashes, underlines) people decorate names with.
# Other scripts' combining marks (Japanese voicing, Thai vowels) are part of the letter, so they stay
DECORATION_RANGES = (
    (0x0300, 0x036F),  # Combining Diacritical Marks
    (0x1AB0, 0x1AFF),  # Combining Diacritical Marks Extended
    (0x1DC0, 0x1DFF),  # Combining Diacritical Marks Supplement
    (0x20D0, 0x20FF),  # Combining Diacritical Marks for Symbols
    (0xFE20, 0xFE2F),  # Combining Half Marks
)


# Letters that look like an accented Latin letter but don't decompose into one
LOOKALIKES = str.maketrans({
    "đ": "d", "ð": "d", "ø": "o", "ł": "l", "ħ": "h", "ŧ": "t", "ı": "i",
    "ß": "ss", "æ": "ae", "œ": "oe", "þ": "th",
})


def is_decoration(c: str) -> bool:
    return any(lo <= ord(c) <= hi for lo, hi in DECORATION_RANGES)


def normalise(text: str) -> str:
    """Search key for player and clan names, use it on both sides of every comparison.

    Lowercase, accents and decorative marks removed (so "T̶B̶ J̸O̸H̸A̸N̸" and "Édy" become
    "tbjohan" and "edy"), and only letters and digits kept, so spaces, symbols and emoji
    don't matter. Works the same for any script.
    """
    lowered = unicodedata.normalize("NFKC", text).lower()
    key = "".join(
        c for c in unicodedata.normalize("NFKD", lowered).translate(LOOKALIKES)
        if not is_decoration(c) and (c.isalnum() or unicodedata.category(c) in ("Mn", "Mc"))
    )
    # Back to composed form: rejoins Korean syllables and Japanese voiced kana split by NFKD
    key = unicodedata.normalize("NFC", key)
    if key:
        return key
    # Names made only of symbols/emoji would otherwise match everything
    return lowered.strip()


async def search(link: str, selector: str) -> str:
    data = await flaresolverr.solve(link)

    if data is None:
        raise ValueError()

    solution = data.get("solution") or {}
    html = solution.get("response", "")
    soup = bs4.BeautifulSoup(html, "html.parser")
    element = soup.select_one(selector)
    return element.decode_contents() if element else ""


async def search_player_by_name(name: str) -> str:
    link = search_settings.ROYALE_API_PLAYER_SEARCH.format(urllib.parse.quote(name))
    search_result_selector = ".player_search_results__container"
    return await search(link, search_result_selector)


async def cr_api_get(url: str):
    """GET from the CR API proxy, retrying the random 5xx errors (mostly 520) it returns."""
    for attempt in range(search_settings.CR_API_RETRIES):
        try:
            async with net.session().get(
                url, headers=search_settings.CR_API_HEADERS
            ) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientResponseError as e:
            if e.status < 500 or attempt == search_settings.CR_API_RETRIES - 1:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))


async def search_clans_by_name(clan: str) -> dict:
    endpoint = search_settings.CR_API_CLAN_SEARCH.format(urllib.parse.quote(clan))
    return await cr_api_get(endpoint)


def parse_players(html: str) -> list[dict]:
    soup = bs4.BeautifulSoup(html, "html.parser")
    results = soup.find_all("div", class_="player_search_results__result_container")

    players = []
    for result in results:
        header = result.find("a", class_="header")
        player_tag = result.find("div", class_="player_tag")

        name = header.text.strip() if header else None
        tag = player_tag.text.strip() if player_tag else None

        clan_and_tag = result.find("a", class_="meta")
        clan_name = (
            clan_and_tag.text.strip().split("\xa0\xa0")[0] if clan_and_tag else None
        )
        clan_tag = (
            clan_and_tag.text.strip().split("\xa0\xa0")[1] if clan_and_tag else None
        )

        if name:
            name = normalise(name)
        if clan_name:
            clan_name = normalise(clan_name)

        players.append(
            {"name": name, "tag": tag, "clan": clan_name, "clan_tag": clan_tag}
        )

    return players


# Not used anymore, will delete if searching clans using official API doesn't work out well.
def parse_clans(html: str) -> list[str]:
    soup = bs4.BeautifulSoup(html, "html.parser")
    results = soup.find_all("div", class_="clanresult")

    clans = []
    for result in results:
        clan_tag = "%23" + str(result["data-clantag"])
        clans.append(clan_tag)

    return clans


def find_player_tag(players: list[dict], clan: str | None) -> str | None:
    if len(players) == 1:
        return players[0]["tag"]
    if not clan:
        for player in players:
            if not player["clan"]:
                return player["tag"]

    else:
        for player in players:
            if player["clan"] and normalise(clan) in player["clan"]:
                return player["tag"]

    return None


async def get_battle_log(tag: str) -> list[dict]:
    url = search_settings.CR_API_BATTLE_LOG.format(urllib.parse.quote(tag))
    return await cr_api_get(url)


async def get_clan_members(clan_tag: str) -> dict:
    url = search_settings.CR_API_CLAN_MEMBERS.format(urllib.parse.quote(clan_tag))
    return await cr_api_get(url)


def find_member_in_clan(data: dict, name: str) -> str | None:
    members = data["items"]
    name = normalise(name)
    if not name:
        return None
    for member in members:
        if name in normalise(member["name"]):
            return member["tag"]
    return None


async def search_player_in_clans(data: dict, name: str) -> str | None:
    clans = data["items"]
    semaphore = asyncio.Semaphore(search_settings.CR_API_MAX_CONCURRENT)

    async def get_members(clan_tag: str) -> dict:
        async with semaphore:
            try:
                return await get_clan_members(clan_tag)
            except aiohttp.ClientResponseError as e:
                # Don't fail the whole search because of one clan
                await log.warning(f"Skipping clan {clan_tag}: {e.status} {e.message}")
                return {"items": []}

    # Fetch all clans in parallel, but keep the original clan order when matching
    all_members = await asyncio.gather(
        *(get_members(clan.get("tag")) for clan in clans)
    )
    for members in all_members:
        member_tag = find_member_in_clan(members, name)
        if member_tag is not None:
            return member_tag
    return None


DB_SEARCH_LIMIT = 1000


def pick_stored_player(rows: list[tuple[str, str | None]], clan: str | None) -> str | None:
    """Picks the tag from stored (tag, clan name) rows, None if there's no single clear match."""
    if not clan:
        if len(rows) == 1:
            return rows[0][0]
        clanless = [tag for tag, clan_name in rows if not clan_name]
        return clanless[0] if len(clanless) == 1 else None

    clan = normalise(clan)
    exact = [tag for tag, clan_name in rows if clan_name and normalise(clan_name) == clan]
    if len(exact) == 1:
        return exact[0]
    partial = [tag for tag, clan_name in rows if clan_name and clan in normalise(clan_name)]
    return partial[0] if len(partial) == 1 else None


async def find_tag_in_database(db: Database, name: str, clan: str | None) -> str | None:
    name = normalise(name)
    if not name:
        # An empty key is a substring of every name
        return None
    rows = await db.get_players_by_name(name, DB_SEARCH_LIMIT)

    # Prefer players whose whole name matches, then any name containing it
    exact = [(tag, clan_name) for tag, clan_name, search_name in rows if search_name == name]
    tag = pick_stored_player(exact, clan)
    if tag or len(rows) >= DB_SEARCH_LIMIT:
        # A capped result may be missing the right player, so a "unique" substring match isn't trustworthy
        return tag

    return pick_stored_player([(tag, clan_name) for tag, clan_name, _ in rows], clan)


async def find_tag_by_name(name: str, clan: str | None) -> str | None:
    search_players = await search_player_by_name(name)
    players = parse_players(search_players)
    return find_player_tag(players, clan)


async def find_tag_by_clan(name: str, clan: str) -> str | None:
    clans = await search_clans_by_name(clan)
    return await search_player_in_clans(clans, name)


async def find_tag(db: Database, name: str, clan: str | None) -> str | None:
    tag = await find_tag_in_database(db, name, clan)
    if tag:
        await log.info(f"Found player in database. Tag: {tag}")
        return tag

    if clan:
        tag = await find_tag_by_clan(name, clan)
        if tag:
            await log.info(f"Found player by clan. Tag: {tag}")
            return tag

    tag = await find_tag_by_name(name, clan)
    if tag:
        await log.info(f"Found player by name. Tag: {tag}")
    return tag


async def save_player_from_battle_log(db: Database, tag: str, battles: list[dict]) -> None:
    """Stores the player's current name and clan, taken from their latest battle."""
    # Scraped tags may come without the '#' or in a different case
    wanted = tag.lstrip("#").upper()
    for battle in battles:
        for participant in battle.get("team", []):
            if participant.get("tag", "").lstrip("#").upper() != wanted or not participant.get("name"):
                continue
            clan_name = (participant.get("clan") or {}).get("name")
            name = participant["name"]
            await db.save_player(participant["tag"], name, clan_name, normalise(name))
            return


async def find_deck(db: Database, name: str, clan: str | None) -> list[dict[str, str]] | None:
    tag = await find_tag(db, name, clan)
    if not tag:
        await log.info(f"Player {name} not found")
        return None

    data = await get_battle_log(tag)
    # Adds players found by the fallback searches and refreshes stale names/clans
    await save_player_from_battle_log(db, tag, data)
    return await get_deck.get_last_deck(data)
