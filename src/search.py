import aiohttp
import bs4
from config import (
    CLASH_API_BATTLE_LOG,
    CLASH_API_CLAN_MEMBERS,
    CLASH_API_HEADERS,
    FLARESOLVERR_TIMEOUT_MS,
    FLARESOLVERR_URL,
    ROYALE_API_CLAN_SEARCH,
    ROYALE_API_PLAYER_SEARCH,
)
from deck import get_last_deck
from helper import normalise, print_info

FLARESOLVERR_SESSION = "crbot"


async def create_flaresolverr_session() -> None:
    async with aiohttp.ClientSession() as http:
        async with http.post(
            FLARESOLVERR_URL,
            json={"cmd": "sessions.create", "session": FLARESOLVERR_SESSION},
        ) as response:
            response.raise_for_status()
    await print_info(f"Created FlareSolverr session: {FLARESOLVERR_SESSION}")

    async with aiohttp.ClientSession() as http:
        async with http.post(
            FLARESOLVERR_URL,
            json={
                "cmd": "request.get",
                "url": ROYALE_API_PLAYER_SEARCH,
                "session": FLARESOLVERR_SESSION,
                "maxTimeout": FLARESOLVERR_TIMEOUT_MS,
            },
        ) as response:
            response.raise_for_status()
    await print_info("Warmed up RoyaleAPI Cloudflare cookies")


async def destroy_flaresolverr_session() -> None:
    async with aiohttp.ClientSession() as http:
        async with http.post(
            FLARESOLVERR_URL,
            json={"cmd": "sessions.destroy", "session": FLARESOLVERR_SESSION},
        ) as response:
            response.raise_for_status()


async def search(link: str, selector: str) -> str:
    payload = {
        "cmd": "request.get",
        "url": link,
        "session": FLARESOLVERR_SESSION,
        "maxTimeout": FLARESOLVERR_TIMEOUT_MS,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(FLARESOLVERR_URL, json=payload) as response:
            response.raise_for_status()
            data = await response.json()

    solution = data.get("solution") or {}
    html = solution.get("response", "")
    soup = bs4.BeautifulSoup(html, "html.parser")
    element = soup.select_one(selector)
    return element.decode_contents() if element else ""


async def search_player_by_name(name: str) -> str:
    link = ROYALE_API_PLAYER_SEARCH.format(name)
    search_result_selector = ".player_search_results__container"
    return await search(link, search_result_selector)


async def search_clans_by_name(clan: str) -> str:
    link = ROYALE_API_CLAN_SEARCH.format(clan)
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
    url = CLASH_API_BATTLE_LOG.format(tag.replace("#", "%23"))
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=CLASH_API_HEADERS) as response:
            response.raise_for_status()
            return await response.json()


async def get_clan_members(clan_tag: str) -> dict:
    url = CLASH_API_CLAN_MEMBERS.format(clan_tag)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=CLASH_API_HEADERS) as response:
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

    await print_info(f"Found player by name. Tag: {player_tag}")
    data = await get_battle_log(player_tag)
    return get_last_deck(data)


async def find_deck_by_clan(name: str, clan: str) -> list[dict[str, str]] | None:
    search_clans = await search_clans_by_name(clan)
    clans = parse_clans(search_clans)
    member_tag = await search_player_in_clans(clans, name)

    if not member_tag:
        return None

    await print_info(f"Found player by clan. Tag: {member_tag}")
    data = await get_battle_log(member_tag)
    return get_last_deck(data)


async def find_deck(name: str, clan: str | None) -> list[dict[str, str]] | None:
    if not clan:
        return await find_deck_by_name(name, clan)

    deck = await find_deck_by_name(name, clan)
    if not deck:
        deck = await find_deck_by_clan(name, clan)

    if not deck:
        await print_info(f"Player {name} not found")

    return deck
