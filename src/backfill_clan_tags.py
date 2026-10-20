"""Fills cr_player.clan_tag for players stored before the column existed.

A player's clan tag is only certain when exactly one stored clan has that exact name
(case and symbols included, not the normalised key). Players in clans that share a
name are left NULL; the next crawl/refresh of their clan fills them in.

Usage (from the repo root, or inside the bot container with `docker compose exec bot`):
    python3 src/backfill_clan_tags.py
"""

import argparse
import asyncio
import time

from config import paths
from database import Database

BATCH_SIZE = 100_000


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=paths.DATABASE, help="SQLite database path (default: the bot's)")
    args = parser.parse_args()

    # connect() adds the clan_tag column if this database predates it
    database = Database(args.db, paths.SCHEMA)
    await database.connect()
    db = database.connection
    assert db is not None

    await db.execute("DROP TABLE IF EXISTS temp.unique_clan")
    await db.execute(
        "CREATE TEMP TABLE unique_clan AS \
        SELECT name, MIN(tag) AS tag FROM cr_clan GROUP BY name HAVING COUNT(*) = 1"
    )
    await db.execute("CREATE UNIQUE INDEX temp.unique_clan_name ON unique_clan(name)")

    cursor = await db.execute("SELECT MAX(rowid) FROM cr_player")
    max_rowid = (await cursor.fetchone())[0] or 0
    start = time.time()
    filled = 0

    # Batches by rowid so the bot isn't locked out of the database for the whole run
    for low in range(0, max_rowid + 1, BATCH_SIZE):
        cursor = await db.execute(
            "UPDATE cr_player \
            SET clan_tag = (SELECT tag FROM unique_clan u WHERE u.name = cr_player.clan_name) \
            WHERE rowid > ? AND rowid <= ? AND clan_tag IS NULL \
            AND clan_name IN (SELECT name FROM unique_clan)",
            (low, low + BATCH_SIZE),
        )
        await db.commit()
        filled += cursor.rowcount
        print(f"rows up to {min(low + BATCH_SIZE, max_rowid)}/{max_rowid}: {filled} clan tags filled ({time.time() - start:.0f}s)")

    cursor = await db.execute(
        "SELECT COUNT(*) FROM cr_player WHERE clan_tag IS NULL AND clan_name IS NOT NULL"
    )
    left = (await cursor.fetchone())[0]
    await db.close()
    print(f"Done: {filled} filled, {left} players in clans with shared names left for the next refresh")


if __name__ == "__main__":
    asyncio.run(main())
