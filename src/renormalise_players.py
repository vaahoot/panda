"""Recomputes search_name for stored players and clans with the current normalise().

Run it after changing normalise(), otherwise stored names and searches use different keys.
Safe to run while the bot is up: it writes in small batches. Stop the crawler first.

Usage (from the repo root, or inside the bot container with `docker compose exec bot`):
    python3 src/renormalise_players.py
"""

import argparse
import asyncio
import sqlite3
import time

from clash.names import normalise
from config import paths
from database import Database

BATCH_SIZE = 50_000


def renormalise(db: sqlite3.Connection, table: str) -> None:
    total = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    start = time.time()
    last_rowid = checked = changed = 0

    while True:
        rows = db.execute(
            f"SELECT rowid, name, search_name FROM {table} WHERE rowid > ? ORDER BY rowid LIMIT ?",
            (last_rowid, BATCH_SIZE),
        ).fetchall()
        if not rows:
            break
        last_rowid = rows[-1][0]

        updates = [(normalise(name), rowid) for rowid, name, search_name in rows if normalise(name) != search_name]
        db.executemany(f"UPDATE {table} SET search_name = ? WHERE rowid = ?", updates)
        db.commit()

        checked += len(rows)
        changed += len(updates)
        print(f"{table}: {checked}/{total} checked, {changed} updated ({time.time() - start:.0f}s)")

    print(f"{table} done: {changed} of {checked} search names changed")


async def migrate(path: str) -> None:
    """connect() adds search_name to clan tables that predate it."""
    database = Database(path, paths.SCHEMA)
    await database.connect()
    assert database.connection is not None
    await database.connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=paths.DATABASE, help="SQLite database path (default: the bot's)")
    args = parser.parse_args()

    asyncio.run(migrate(args.db))
    db = sqlite3.connect(args.db, timeout=30)
    for table in ("cr_clan", "cr_player"):
        renormalise(db, table)
    db.close()


if __name__ == "__main__":
    main()
