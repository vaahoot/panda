import asyncio
import sqlite3
import urllib.parse

import aiohttp
import bs4

import log
import net
from clash.deck import get_deck
from clash.names import normalise
from config import search_settings
from database import Database

from . import flaresolverr


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
    """GET from the CR API, retrying the random 5xx errors (mostly 520 from the proxy) it returns."""
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
DB_CLAN_MEMBERS_LIMIT = 5000


def pick_clanless(rows: list[tuple[str, str | None]]) -> str | None:
    """With no clan given: the only player, or the only one without a clan."""
    if len(rows) == 1:
        return rows[0][0]
    clanless = [tag for tag, clan_name in rows if not clan_name]
    return clanless[0] if len(clanless) == 1 else None


# Closest first. Names cut off in a screenshot lose their end, so "starts with" beats "contains"
MATCH_LEVELS = (str.__eq__, str.startswith, str.__contains__)


def pick_by_name_and_clan(candidates: dict[str, tuple[str, str]], name: str, clan: str) -> str | None:
    """candidates maps tag -> (player key, clan key). Tries the closest matches first: same clan
    and same name, then looser ones. The first level with any match decides: one player is the
    answer, several means the database can't tell them apart."""
    for clan_matches in MATCH_LEVELS:
        for name_matches in MATCH_LEVELS:
            tags = [
                tag for tag, (player_key, clan_key) in candidates.items()
                if clan_key and clan_matches(clan_key, clan) and name_matches(player_key, name)
            ]
            if tags:
                return tags[0] if len(tags) == 1 else None
    return None


async def find_tag_in_database(db: Database, name: str, clan: str | None) -> str | None:
    name = normalise(name)
    if not name:
        # An empty key is a substring of every name
        return None

    # The name alone is enough when only one stored player has it
    exact = await db.get_players_by_exact_name(name, DB_SEARCH_LIMIT)
    if len(exact) == 1:
        return exact[0][0]
    containing = await db.get_players_by_name(name, DB_SEARCH_LIMIT)
    if not exact and len(containing) == 1:
        return containing[0][0]

    clan = normalise(clan) if clan else ""
    if not clan:
        if exact:
            return pick_clanless([(tag, clan_name) for tag, clan_name, _ in exact])
        if len(containing) >= DB_SEARCH_LIMIT:
            # A capped result may be missing the right player
            return None
        return pick_clanless([(tag, clan_name) for tag, clan_name, _ in containing])

    # Players matching the name, plus members of clans matching the clan. The second half
    # still finds common names whose matches didn't all fit in the name results
    candidates = {
        tag: (search_name, normalise(clan_name) if clan_name else "")
        for tag, clan_name, search_name in exact + containing
    }
    members = await db.get_players_in_clans(clan, partial=False, limit=DB_CLAN_MEMBERS_LIMIT)
    if not members:
        members = await db.get_players_in_clans(clan, partial=True, limit=DB_CLAN_MEMBERS_LIMIT)
    for tag, search_name, clan_key in members:
        candidates[tag] = (search_name, clan_key)

    return pick_by_name_and_clan(candidates, name, clan)


async def find_tag_by_name(name: str, clan: str | None) -> str | None:
    search_players = await search_player_by_name(name)
    players = parse_players(search_players)
    return find_player_tag(players, clan)


async def find_tag_by_clan(name: str, clan: str) -> str | None:
    clans = await search_clans_by_name(clan)
    return await search_player_in_clans(clans, name)


async def find_tag(db: Database, name: str, clan: str | None) -> str | None:
    try:
        tag = await find_tag_in_database(db, name, clan)
    except sqlite3.OperationalError as e:
        # e.g. still locked by the crawler after the busy timeout, the API searches still work
        await log.warning(f"Database search failed, falling back to the API: {e}")
        tag = None
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
            clan = participant.get("clan") or {}
            name = participant["name"]
            await db.save_player(participant["tag"], name, clan.get("tag"), clan.get("name"), normalise(name))
            return


async def find_deck(db: Database, name: str, clan: str | None) -> list[dict[str, str]] | None:
    tag = await find_tag(db, name, clan)
    if not tag:
        await log.info(f"Player {name} not found")
        return None

    data = await get_battle_log(tag)
    # Adds players found by the fallback searches and refreshes stale names/clans
    try:
        await save_player_from_battle_log(db, tag, data)
    except sqlite3.OperationalError as e:
        await log.warning(f"Couldn't save player {tag}: {e}")
    return await get_deck.get_last_deck(data)
