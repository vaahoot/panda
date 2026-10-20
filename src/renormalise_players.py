"""Recomputes cr_player.search_name with the current normalise().

Run it after changing normalise(), otherwise stored names and searches use different keys.
Safe to run while the bot is up: it writes in small batches. Stop the crawler first.

Usage (from the repo root, or inside the bot container with `docker compose exec bot`):
    python3 src/renormalise_players.py
"""

import argparse
import sqlite3
import time

from clash.scraping.search import normalise
from config import paths

BATCH_SIZE = 50_000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=paths.DATABASE, help="SQLite database path (default: the bot's)")
    args = parser.parse_args()

    db = sqlite3.connect(args.db, timeout=30)
    total = db.execute("SELECT COUNT(*) FROM cr_player").fetchone()[0]
    start = time.time()
    last_rowid = checked = changed = 0

    while True:
        rows = db.execute(
            "SELECT rowid, name, search_name FROM cr_player WHERE rowid > ? ORDER BY rowid LIMIT ?",
            (last_rowid, BATCH_SIZE),
        ).fetchall()
        if not rows:
            break
        last_rowid = rows[-1][0]

        updates = [(normalise(name), rowid) for rowid, name, search_name in rows if normalise(name) != search_name]
        db.executemany("UPDATE cr_player SET search_name = ? WHERE rowid = ?", updates)
        db.commit()

        checked += len(rows)
        changed += len(updates)
        print(f"{checked}/{total} checked, {changed} updated ({time.time() - start:.0f}s)")

    db.close()
    print(f"Done: {changed} of {checked} search names changed")


if __name__ == "__main__":
    main()
