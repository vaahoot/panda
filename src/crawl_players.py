"""Collects Clash Royale players (tag, name, clan) into the bot's database.

The official API can't list or search players, so this snowballs out from seeds:
  1. Seed clans from every location's clan rankings and a filtered clan search.
  2. Each clan's member list gives up to 50 players (cheapest source).
  3. Each player's battle log gives opponents/teammates, including clanless
     players, plus their clans, which go back into step 2.

Progress lives in the database, so the crawl can be stopped and resumed at any time.

Usage (from the repo root, or inside the bot container with `docker compose exec bot`):
    python3 src/crawl_players.py --max-players 1000000
"""

import argparse
import asyncio
import time
import urllib.parse

import aiohttp
import aiosqlite

import log
import net
from clash.scraping.search import normalise
from config import paths, search_settings
from database import Database
from database.database import UPSERT_PLAYER

BATCH_SIZE = 500
MAX_RETRIES = 5

UPSERT_CLAN = """
    INSERT INTO cr_clan(tag, name) VALUES(?, ?)
    ON CONFLICT(tag) DO UPDATE SET name = excluded.name
"""


class FatalApiError(Exception):
    pass


class Api:
    """CR API client with a global request rate limit and retries."""

    def __init__(self, rps: float, concurrency: int):
        self.interval = 1 / rps
        self.next_slot = 0.0
        self.lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(concurrency)
        self.requests = 0
        self.started = time.monotonic()

    async def wait_for_slot(self) -> None:
        async with self.lock:
            now = time.monotonic()
            delay = self.next_slot - now
            self.next_slot = max(now, self.next_slot) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)

    def rate(self) -> float:
        return self.requests / max(time.monotonic() - self.started, 1)

    async def get(self, path: str, **params) -> dict | list | None:
        """Returns the JSON body, or None if the resource doesn't exist."""
        url = search_settings.CR_API_BASE + path
        params = {k: v for k, v in params.items() if v is not None}

        for attempt in range(MAX_RETRIES):
            await self.wait_for_slot()
            async with self.semaphore:
                self.requests += 1
                try:
                    async with net.session().get(
                        url,
                        params=params,
                        headers=search_settings.CR_API_HEADERS,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as response:
                        if response.status == 200:
                            return await response.json()
                        if response.status in (400, 404):
                            return None
                        if response.status == 403:
                            body = await response.text()
                            raise FatalApiError(f"403 from API, check CR_API_KEY / allowed IPs: {body}")
                        status = response.status
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    status = f"{type(e).__name__}"

            if status == 429:
                # Too fast, slow everyone down for a bit
                backoff = 2 ** attempt
                await log.warning(f"Rate limited, backing off {backoff}s")
                async with self.lock:
                    self.next_slot = max(self.next_slot, time.monotonic() + backoff)
            elif status == 503:
                await log.warning("API in maintenance, waiting 60s")
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(0.5 * (attempt + 1))

        await log.warning(f"Giving up on {path} after {MAX_RETRIES} attempts (last: {status})")
        return None


def player_row(tag: str, name: str, clan_name: str | None) -> tuple:
    return (tag, name, clan_name, normalise(name))


def quote(tag: str) -> str:
    return urllib.parse.quote(tag)


async def seed_location(api: Api, location: dict, seed_pages: int) -> tuple[list, list]:
    """Returns (clan rows, player rows) found for one location."""
    clans, players = [], []
    location_id = location["id"]

    rankings = await api.get(f"/locations/{location_id}/rankings/clans")
    for clan in (rankings or {}).get("items", []):
        clans.append((clan["tag"], clan["name"]))

    path_of_legend = await api.get(f"/locations/{location_id}/pathoflegend/players")
    for player in (path_of_legend or {}).get("items", []):
        clan = player.get("clan") or {}
        players.append(player_row(player["tag"], player["name"], clan.get("name")))
        if clan.get("tag"):
            clans.append((clan["tag"], clan["name"]))

    # Clan search needs at least one filter, locationId + minMembers skips empty clans
    after = None
    for _ in range(seed_pages):
        page = await api.get(
            "/clans", locationId=location_id, minMembers=10, limit=100, after=after
        )
        if not page:
            break
        for clan in page.get("items", []):
            clans.append((clan["tag"], clan["name"]))
        after = page.get("paging", {}).get("cursors", {}).get("after")
        if not after:
            break

    return clans, players


async def seed(api: Api, db: aiosqlite.Connection, seed_pages: int, max_players: int) -> None:
    locations = await api.get("/locations", limit=1000)
    if not locations:
        raise FatalApiError("Couldn't load locations")

    items = locations["items"]
    await log.info(f"Seeding from {len(items)} locations")

    # A few locations at a time so they finish (and get saved) steadily instead of all at the end
    semaphore = asyncio.Semaphore(10)

    async def seed_one(location: dict) -> tuple[list, list]:
        async with semaphore:
            return await seed_location(api, location, seed_pages)

    total_clans = total_players = 0
    for done, result in enumerate(asyncio.as_completed([seed_one(loc) for loc in items]), 1):
        clans, players = await result
        await db.executemany(UPSERT_CLAN, clans)
        await db.executemany(UPSERT_PLAYER, players)
        await db.commit()

        total_clans += len(clans)
        total_players += len(players)
        if done % 10 == 0 or done == len(items):
            await log.info(
                f"Seeded {done}/{len(items)} locations: {total_clans} clans, "
                f"{total_players} players | requests: {api.requests} ({api.rate():.1f}/s)"
            )
        if max_players and await count(db, "SELECT COUNT(*) FROM cr_player") >= max_players:
            await log.info(f"Seeded {done}/{len(items)} locations, player limit reached")
            return


async def crawl_clan(api: Api, tag: str) -> tuple[list, list]:
    """Returns (clan rows, player rows) from the clan's member list."""
    clan = await api.get(f"/clans/{quote(tag)}")
    if not clan:
        return [], []

    players = [
        player_row(member["tag"], member["name"], clan["name"])
        for member in clan.get("memberList", [])
    ]
    return [(clan["tag"], clan["name"])], players


async def crawl_battlelog(api: Api, tag: str) -> tuple[list, list]:
    """Returns (clan rows, player rows) for everyone in the player's recent battles."""
    battles = await api.get(f"/players/{quote(tag)}/battlelog")
    clans, players = [], []

    for battle in battles or []:
        for participant in battle.get("team", []) + battle.get("opponent", []):
            if not participant.get("tag") or not participant.get("name"):
                continue
            clan = participant.get("clan") or {}
            players.append(player_row(participant["tag"], participant["name"], clan.get("name")))
            if clan.get("tag"):
                clans.append((clan["tag"], clan["name"]))

    return clans, players


async def count(db: aiosqlite.Connection, query: str) -> int:
    cursor = await db.execute(query)
    row = await cursor.fetchone()
    return row[0] if row else 0


async def crawl(api: Api, db: aiosqlite.Connection, max_players: int, max_requests: int) -> None:
    while True:
        total_players = await count(db, "SELECT COUNT(*) FROM cr_player")
        if max_players and total_players >= max_players:
            await log.info(f"Database has {total_players} players, at or above --max-players {max_players} (a total, not players to add), stopping")
            return
        if max_requests and api.requests >= max_requests:
            await log.info(f"Used {api.requests} requests, stopping")
            return

        # Clans first: one request gives up to 50 players, a battle log gives far fewer new ones
        cursor = await db.execute(
            "SELECT tag FROM cr_clan WHERE members_checked_at IS NULL LIMIT ?", (BATCH_SIZE,)
        )
        clan_tags = [row[0] for row in await cursor.fetchall()]

        if clan_tags:
            results = await asyncio.gather(*(crawl_clan(api, tag) for tag in clan_tags))
            mark_done = "UPDATE cr_clan SET members_checked_at = ? WHERE tag = ?"
            done_tags = clan_tags
        else:
            cursor = await db.execute(
                "SELECT tag FROM cr_player WHERE battlelog_checked_at IS NULL LIMIT ?",
                (BATCH_SIZE,),
            )
            player_tags = [row[0] for row in await cursor.fetchall()]
            if not player_tags:
                await log.info("Nothing left to crawl")
                return
            results = await asyncio.gather(*(crawl_battlelog(api, tag) for tag in player_tags))
            mark_done = "UPDATE cr_player SET battlelog_checked_at = ? WHERE tag = ?"
            done_tags = player_tags

        # Write the whole batch in one short transaction so the bot is never blocked for long
        now = int(time.time())
        await db.executemany(UPSERT_CLAN, [clan for result in results for clan in result[0]])
        await db.executemany(UPSERT_PLAYER, [player for result in results for player in result[1]])
        await db.executemany(mark_done, [(now, tag) for tag in done_tags])
        await db.commit()

        total_players = await count(db, "SELECT COUNT(*) FROM cr_player")
        pending_clans = await count(db, "SELECT COUNT(*) FROM cr_clan WHERE members_checked_at IS NULL")
        await log.info(
            f"Players: {total_players} | clans to crawl: {pending_clans} | "
            f"requests: {api.requests} ({api.rate():.1f}/s)"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=paths.DATABASE, help="SQLite database path (default: the bot's)")
    parser.add_argument("--rps", type=float, default=15, help="max API requests per second")
    parser.add_argument("--concurrency", type=int, default=20, help="max requests in flight")
    parser.add_argument("--max-players", type=int, default=0, help="stop once the database holds this many players in total")
    parser.add_argument("--max-requests", type=int, default=0, help="stop after roughly this many requests")
    parser.add_argument("--seed-pages", type=int, default=10, help="clan search pages (100 clans each) per location")
    parser.add_argument("--reseed", action="store_true", help="seed again even if clans are already stored")
    args = parser.parse_args()

    database = Database(args.db, paths.SCHEMA)
    await database.connect()
    db = database.connection
    assert db is not None
    api = Api(args.rps, args.concurrency)

    try:
        if args.reseed or await count(db, "SELECT COUNT(*) FROM cr_clan") == 0:
            await seed(api, db, args.seed_pages, args.max_players)
        await crawl(api, db, args.max_players, args.max_requests)
    finally:
        await db.close()
        await net.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped, run again to resume")
