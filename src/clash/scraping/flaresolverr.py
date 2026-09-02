from typing import Any

import aiohttp

import log
from config import search_settings

FLARESOLVERR_SESSION = "panda"


async def create_flaresolverr_session() -> None:
    async with (
        aiohttp.ClientSession() as http,
        http.post(
            search_settings.FLARESOLVERR_URL,
            json={"cmd": "sessions.create", "session": FLARESOLVERR_SESSION},
        ) as response,
    ):
        response.raise_for_status()
    await log.info(f"Created FlareSolverr session: {FLARESOLVERR_SESSION}")

    async with (
        aiohttp.ClientSession() as http,
        http.post(
            search_settings.FLARESOLVERR_URL,
            json={
                "cmd": "request.get",
                "url": search_settings.ROYALE_API_PLAYER_SEARCH,
                "session": FLARESOLVERR_SESSION,
                "maxTimeout": search_settings.FLARESOLVERR_TIMEOUT_MS,
            },
        ) as response,
    ):
        response.raise_for_status()
    await log.info("Warmed up RoyaleAPI Cloudflare cookies")


async def destroy_flaresolverr_session() -> None:
    async with (
        aiohttp.ClientSession() as http,
        http.post(
            search_settings.FLARESOLVERR_URL,
            json={"cmd": "sessions.destroy", "session": FLARESOLVERR_SESSION},
        ) as response,
    ):
        response.raise_for_status()


async def solve(link: str) -> dict[str, Any]:
    payload = {
        "cmd": "request.get",
        "url": link,
        "session": FLARESOLVERR_SESSION,
        "maxTimeout": search_settings.FLARESOLVERR_TIMEOUT_MS,
    }
    async with (
        aiohttp.ClientSession() as session,
        session.post(search_settings.FLARESOLVERR_URL, json=payload) as response,
    ):
        response.raise_for_status()
        data = await response.json()

    return data
