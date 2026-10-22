import pathlib
import sqlite3

import aiofiles
import aiosqlite
import discord

import log
from clash.names import normalise
from config.settings import DEFAULT_PREFIX

BUSY_TIMEOUT_SECONDS = 30

# Keeps battlelog_checked_at so the crawler's progress isn't reset by updates
UPSERT_PLAYER = """
    INSERT INTO cr_player(tag, name, clan_tag, clan_name, search_name) VALUES(?, ?, ?, ?, ?)
    ON CONFLICT(tag) DO UPDATE SET
        name = excluded.name,
        clan_tag = excluded.clan_tag,
        clan_name = excluded.clan_name,
        search_name = excluded.search_name
"""

UPSERT_CLAN = """
    INSERT INTO cr_clan(tag, name, search_name) VALUES(?, ?, ?)
    ON CONFLICT(tag) DO UPDATE SET
        name = excluded.name,
        search_name = excluded.search_name
"""

# Columns added after their table was first created: (table, column, type)
ADDED_COLUMNS = [
    ("cr_player", "clan_tag", "TEXT"),
    ("cr_clan", "search_name", "TEXT"),
]


class Database:
    def __init__(self, path: pathlib.Path, schema: pathlib.Path):
        self.path = path
        self.schema = schema
        self.connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        pathlib.Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # The bot and the crawler share this file: wait for each other's writes instead of
        # failing with "database is locked" after the default 5s
        self.connection = await aiosqlite.connect(self.path, timeout=BUSY_TIMEOUT_SECONDS)
        # SQLite ignores ON DELETE CASCADE unless this is enabled per connection
        await self.connection.execute("PRAGMA foreign_keys = ON")
        await self.use_wal()
        # Safe with WAL: a power cut can lose the last commit, but never corrupts the file
        await self.connection.execute("PRAGMA synchronous = NORMAL")
        await self.migrate()
        cursor = await self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'cr_player_fts'"
        )
        had_search_index = await cursor.fetchone() is not None

        async with aiofiles.open(self.schema) as f:
            schema_setup = await f.read()
        await self.connection.executescript(schema_setup)
        await self.connection.commit()

        if not had_search_index:
            # Players stored before the index existed: index them once (~1-2 min for 10M)
            await self.connection.execute("INSERT INTO cr_player_fts(cr_player_fts) VALUES('rebuild')")
            await self.connection.commit()

    async def use_wal(self) -> None:
        """Write-ahead logging: readers no longer wait for the crawler's writes and the other
        way round, only two writers queue. It's stored in the file, so this only matters once."""
        assert self.connection is not None
        cursor = await self.connection.execute("PRAGMA journal_mode")
        if (await cursor.fetchone())[0] == "wal":
            return
        try:
            await self.connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as e:
            # Switching needs nobody else using the file, the next connect tries again
            await log.warning(f"Couldn't switch the database to WAL mode yet: {e}")

    async def migrate(self) -> None:
        """Adds columns to tables created before them, CREATE TABLE IF NOT EXISTS doesn't."""
        assert self.connection is not None
        for table, column, column_type in ADDED_COLUMNS:
            cursor = await self.connection.execute(f"PRAGMA table_info({table})")
            columns = {row[1] for row in await cursor.fetchall()}
            # No columns = table doesn't exist yet, the schema creates it with the column
            if columns and column not in columns:
                await self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
        await self.connection.commit()
        await self.migrate_playlist_table()

    async def migrate_playlist_table(self) -> None:
        """Rebuilds playlist tables created by older versions with the current definition,
        keeping every playlist's id (and so its tracks):
        - early versions created playlist.name without COLLATE NOCASE, so "Chill" and "chill"
          could both exist and lookups were case-sensitive
        - playlist.user_id didn't reference discord_user before that table existed"""
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'playlist'"
        )
        row = await cursor.fetchone()
        if row is None:
            return
        definition = row[0].upper()
        case_sensitive = "NOCASE" not in definition
        if not case_sensitive and "REFERENCES DISCORD_USER" in definition:
            return

        if case_sensitive:
            # Names that only differ by case would break the new UNIQUE, rename the later ones
            cursor = await self.connection.execute(
                "SELECT playlist_id, user_id, name FROM playlist ORDER BY playlist_id"
            )
            taken: set[tuple[int, str]] = set()
            for playlist_id, user_id, name in await cursor.fetchall():
                new_name, n = name, 2
                while (user_id, new_name.lower()) in taken:
                    new_name, n = f"{name} ({n})", n + 1
                taken.add((user_id, new_name.lower()))
                if new_name != name:
                    await self.connection.execute(
                        "UPDATE playlist SET name = ? WHERE playlist_id = ?", (new_name, playlist_id)
                    )
            await self.connection.commit()

        # Foreign keys off while swapping tables, so tracks aren't cascade-deleted with the old one
        await self.connection.execute("PRAGMA foreign_keys = OFF")
        await self.connection.executescript(
            """
            BEGIN;
            CREATE TABLE IF NOT EXISTS discord_user(
              user_id INTEGER PRIMARY KEY,
              cr_tag TEXT
            );
            -- Every playlist owner needs a row for the new foreign key
            INSERT OR IGNORE INTO discord_user(user_id) SELECT DISTINCT user_id FROM playlist;
            CREATE TABLE playlist_new(
              playlist_id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL,
              name TEXT NOT NULL COLLATE NOCASE,
              UNIQUE(user_id, name),
              FOREIGN KEY(user_id) REFERENCES discord_user(user_id) ON DELETE CASCADE
            );
            INSERT INTO playlist_new(playlist_id, user_id, name)
              SELECT playlist_id, user_id, name FROM playlist;
            DROP TABLE playlist;
            ALTER TABLE playlist_new RENAME TO playlist;
            COMMIT;
            """
        )
        await self.connection.execute("PRAGMA foreign_keys = ON")
        await log.info("Rebuilt the playlist table with the current definition")

    async def add_guild(self, guild: discord.Guild) -> None:
        assert self.connection is not None
        await self.connection.execute(
            "INSERT OR IGNORE INTO guild(guild_id) VALUES(?)", (guild.id,)
        )
        await self.connection.commit()

    async def remove_guild(self, guild: discord.Guild) -> None:
        assert self.connection is not None
        await self.connection.execute(
            "DELETE FROM guild WHERE guild_id = ?", (guild.id,)
        )
        await self.connection.commit()

    async def set_prefix(self, guild: discord.Guild, prefix: str) -> None:
        assert self.connection is not None
        await self.connection.execute(
            "UPDATE guild \
            SET prefix = ? \
            WHERE guild_id = ?",
            (prefix, guild.id),
        )
        await self.connection.commit()

    async def get_prefix(self, guild: discord.Guild) -> str:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT prefix \
            FROM guild \
            WHERE guild_id = ?",
            (guild.id,),
        )

        result = await cursor.fetchone()
        return result[0] if result else DEFAULT_PREFIX

    async def add_image_channel(self, guild: discord.Guild, channel: discord.TextChannel) -> bool:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "INSERT OR IGNORE INTO guild_image_channel(guild_id, channel_id) VALUES(?, ?)",
            (guild.id, channel.id),
        )
        await self.connection.commit()
        return cursor.rowcount > 0

    async def remove_image_channel(self, guild: discord.Guild, channel: discord.TextChannel) -> bool:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "DELETE FROM guild_image_channel \
            WHERE guild_id = ? AND channel_id = ?",
            (guild.id, channel.id),
        )
        await self.connection.commit()
        return cursor.rowcount > 0

    async def is_image_channel(self, guild: discord.Guild, channel: discord.TextChannel) -> bool:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT 1 \
            FROM guild_image_channel \
            WHERE guild_id = ? AND channel_id = ?",
            (guild.id, channel.id),
        )
        row = await cursor.fetchone()
        return row is not None

    async def add_user(self, user: discord.abc.User) -> None:
        """Rows that reference a user (playlists) need the user stored first. Doesn't commit."""
        assert self.connection is not None
        await self.connection.execute(
            "INSERT OR IGNORE INTO discord_user(user_id) VALUES(?)", (user.id,)
        )

    async def set_cr_tag(self, user: discord.abc.User, tag: str) -> None:
        assert self.connection is not None
        await self.connection.execute(
            "INSERT INTO discord_user(user_id, cr_tag) VALUES(?, ?) \
            ON CONFLICT(user_id) DO UPDATE SET cr_tag = excluded.cr_tag",
            (user.id, tag),
        )
        await self.connection.commit()

    async def get_cr_tag(self, user: discord.abc.User) -> str | None:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT cr_tag \
            FROM discord_user \
            WHERE user_id = ?",
            (user.id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def create_playlist(self, user: discord.abc.User, name: str) -> bool:
        assert self.connection is not None
        await self.add_user(user)
        cursor = await self.connection.execute(
            "INSERT OR IGNORE INTO playlist(user_id, name) VALUES(?, ?)",
            (user.id, name),
        )
        await self.connection.commit()
        return cursor.rowcount > 0

    async def get_playlists(self, user: discord.abc.User) -> list[str]:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT name \
            FROM playlist \
            WHERE user_id = ? \
            ORDER BY name",
            (user.id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_playlist_id(self, user: discord.abc.User, name: str) -> int | None:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT playlist_id \
            FROM playlist \
            WHERE user_id = ? AND name = ?",
            (user.id, name),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def add_playlist_tracks(
        self, playlist_id: int, tracks: list[tuple[str, str, str]]
    ) -> None:
        """tracks is a list of (url, title, author)."""
        assert self.connection is not None
        await self.connection.executemany(
            "INSERT INTO playlist_track(playlist_id, url, title, author) VALUES(?, ?, ?, ?)",
            [(playlist_id, *track) for track in tracks],
        )
        await self.connection.commit()

    async def get_playlist_urls(self, playlist_id: int) -> list[str]:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT url \
            FROM playlist_track \
            WHERE playlist_id = ? \
            ORDER BY track_id",
            (playlist_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_playlist_tracks(
        self, playlist_id: int
    ) -> list[tuple[int, str | None, str | None]]:
        """Returns (track id, title, author) for each track in the playlist."""
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT track_id, title, author \
            FROM playlist_track \
            WHERE playlist_id = ? \
            ORDER BY track_id",
            (playlist_id,),
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    async def delete_playlist_track(self, playlist_id: int, track_id: int) -> bool:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "DELETE FROM playlist_track \
            WHERE playlist_id = ? AND track_id = ?",
            (playlist_id, track_id),
        )
        await self.connection.commit()
        return cursor.rowcount > 0

    async def get_playlist_summaries(self, user: discord.abc.User) -> list[tuple[str, int]]:
        """Returns (name, track count) for each of the user's playlists."""
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT p.name, COUNT(t.track_id) \
            FROM playlist p \
            LEFT JOIN playlist_track t ON t.playlist_id = p.playlist_id \
            WHERE p.user_id = ? \
            GROUP BY p.playlist_id \
            ORDER BY p.name",
            (user.id,),
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    async def delete_playlist(self, user: discord.abc.User, name: str) -> bool:
        assert self.connection is not None
        cursor = await self.connection.execute(
            "DELETE FROM playlist \
            WHERE user_id = ? AND name = ?",
            (user.id, name),
        )
        await self.connection.commit()
        return cursor.rowcount > 0

    async def get_players_by_name(
        self, search_name: str, limit: int
    ) -> list[tuple[str, str | None, str]]:
        """Returns (tag, clan name, search name) of stored players whose normalised name contains
        search_name, oldest entries first."""
        assert self.connection is not None
        if len(search_name) >= 3 and not any(c in search_name for c in "%_"):
            # Trigram index: substring search in milliseconds. It needs 3+ characters, and
            # '%'/'_' would act as wildcards (normalise() only leaves them in symbol-only names)
            cursor = await self.connection.execute(
                "SELECT p.tag, p.clan_name, p.search_name \
                FROM cr_player_fts f \
                JOIN cr_player p ON p.rowid = f.rowid \
                WHERE f.search_name LIKE ? \
                ORDER BY f.rowid \
                LIMIT ?",
                (f"%{search_name}%", limit),
            )
        else:
            # Too short for trigrams, and a substring that short matches far too many names anyway
            cursor = await self.connection.execute(
                "SELECT tag, clan_name, search_name \
                FROM cr_player \
                WHERE search_name = ? \
                ORDER BY rowid \
                LIMIT ?",
                (search_name, limit),
            )
        rows = await cursor.fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    async def get_players_by_exact_name(
        self, search_name: str, limit: int
    ) -> list[tuple[str, str | None, str]]:
        """Returns (tag, clan name, search name) of stored players whose normalised name is exactly
        search_name, oldest entries first."""
        assert self.connection is not None
        cursor = await self.connection.execute(
            "SELECT tag, clan_name, search_name \
            FROM cr_player \
            WHERE search_name = ? \
            ORDER BY rowid \
            LIMIT ?",
            (search_name, limit),
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    async def get_players_in_clans(
        self, clan_search_name: str, partial: bool, limit: int, max_clans: int = 500
    ) -> list[tuple[str, str, str]]:
        """Returns (tag, player search name, clan search name) of members of stored clans whose
        normalised name is clan_search_name, or contains it when partial."""
        assert self.connection is not None
        # Clans first, then their members through the clan_tag index. Joining in one query
        # makes SQLite walk all players instead
        if partial:
            # ~330k clans, a scan of their short names is quick
            cursor = await self.connection.execute(
                "SELECT tag, search_name FROM cr_clan WHERE instr(search_name, ?) > 0 LIMIT ?",
                (clan_search_name, max_clans + 1),
            )
        else:
            cursor = await self.connection.execute(
                "SELECT tag, search_name FROM cr_clan WHERE search_name = ? LIMIT ?",
                (clan_search_name, max_clans + 1),
            )
        clans = dict(await cursor.fetchall())
        if not clans or len(clans) > max_clans:
            # Nothing, or a clan name so vague it matches hundreds of clans
            return []

        placeholders = ",".join("?" * len(clans))
        cursor = await self.connection.execute(
            f"SELECT tag, search_name, clan_tag FROM cr_player WHERE clan_tag IN ({placeholders}) LIMIT ?",
            (*clans, limit),
        )
        rows = await cursor.fetchall()
        return [(tag, search_name, clans[clan_tag]) for tag, search_name, clan_tag in rows]

    async def save_player(
        self, tag: str, name: str, clan_tag: str | None, clan_name: str | None, search_name: str
    ) -> None:
        assert self.connection is not None
        await self.connection.execute(
            UPSERT_PLAYER, (tag, name, clan_tag, clan_name, search_name)
        )
        if clan_tag and clan_name:
            # So the crawler picks up the rest of the clan and keeps it refreshed
            await self.connection.execute(UPSERT_CLAN, (clan_tag, clan_name, normalise(clan_name)))
        await self.connection.commit()

    async def add_player_if_missing(
        self, tag: str, name: str, clan_tag: str | None, clan_name: str | None
    ) -> bool:
        """Stores a player (and their clan) only if the player isn't stored yet, so the
        crawler's newer data is never overwritten. Returns whether the player was added."""
        assert self.connection is not None
        cursor = await self.connection.execute(
            "INSERT OR IGNORE INTO cr_player(tag, name, clan_tag, clan_name, search_name) \
            VALUES(?, ?, ?, ?, ?)",
            (tag, name, clan_tag, clan_name, normalise(name)),
        )
        added = cursor.rowcount > 0
        if added and clan_tag and clan_name:
            await self.connection.execute(
                "INSERT OR IGNORE INTO cr_clan(tag, name, search_name) VALUES(?, ?, ?)",
                (clan_tag, clan_name, normalise(clan_name)),
            )
        await self.connection.commit()
        return added
