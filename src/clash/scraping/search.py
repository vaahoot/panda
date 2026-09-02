import unicodedata

import aiohttp
import bs4

import log
from clash.deck import get_deck
from config import search_settings

from . import flaresolverr


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().strip()


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
    link = search_settings.ROYALE_API_PLAYER_SEARCH.format(name)
    search_result_selector = ".player_search_results__container"
    return await search(link, search_result_selector)


async def search_clans_by_name(clan: str) -> str:
    link = search_settings.ROYALE_API_CLAN_SEARCH.format(clan)
    search_result_selector = ".three.doubling.stackable.cards"
    return await search(link, search_result_selector)


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
            if player["clan"] and clan.lower() in player["clan"]:
                return player["tag"]

    return None


async def get_battle_log(tag: str) -> list[dict]:
    url = search_settings.CR_API_BATTLE_LOG.format(tag.replace("#", "%23"))
    async with aiohttp.ClientSession() as session:  # noqa: SIM117
        async with session.get(url, headers=search_settings.CR_API_HEADERS) as response:
            response.raise_for_status()
            return await response.json()


async def get_clan_members(clan_tag: str) -> dict:
    url = search_settings.CR_API_CLAN_MEMBERS.format(clan_tag)
    async with aiohttp.ClientSession() as session:  # noqa: SIM117
        async with session.get(url, headers=search_settings.CR_API_HEADERS) as response:
            response.raise_for_status()
            return await response.json()


def find_member_in_clan(data: dict, name: str) -> str | None:
    members = data["items"]
    for member in members:
        if name.lower() in member["name"].lower():
            return member["tag"]
    return None


async def search_player_in_clans(clans: list[str], name: str) -> str | None:
    for clan_tag in clans:
        data = await get_clan_members(clan_tag)
        member_tag = find_member_in_clan(data, name)
        if member_tag:
            return member_tag
    return None


async def find_deck_by_name(name: str, clan: str | None) -> list[dict[str, str]] | None:
    search_players = await search_player_by_name(name)
    players = parse_players(search_players)
    player_tag = find_player_tag(players, clan)

    if not player_tag:
        return None

    await log.info(f"Found player by name. Tag: {player_tag}")
    data = await get_battle_log(player_tag)
    return await get_deck.get_last_deck(data)


async def find_deck_by_clan(name: str, clan: str) -> list[dict[str, str]] | None:
    search_clans = await search_clans_by_name(clan)
    clans = parse_clans(search_clans)
    member_tag = await search_player_in_clans(clans, name)

    if not member_tag:
        return None

    await log.info(f"Found player by clan. Tag: {member_tag}")
    data = await get_battle_log(member_tag)
    return await get_deck.get_last_deck(data)


async def find_deck(name: str, clan: str | None) -> list[dict[str, str]] | None:
    if not clan:
        return await find_deck_by_name(name, clan)

    deck = await find_deck_by_name(name, clan)
    if not deck:
        deck = await find_deck_by_clan(name, clan)

    if not deck:
        await log.info(f"Player {name} not found")

    return deck
