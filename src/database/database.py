import pathlib

import aiofiles
import aiosqlite
import discord

from config.settings import DEFAULT_PREFIX


class Database:
    def __init__(self, path: pathlib.Path, schema: pathlib.Path):
        self.path = path
        self.schema = schema
        self.connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.connection = await aiosqlite.connect(self.path)
        # SQLite ignores ON DELETE CASCADE unless this is enabled per connection
        await self.connection.execute("PRAGMA foreign_keys = ON")

        async with aiofiles.open(self.schema) as f:
            schema_setup = await f.read()
        await self.connection.executescript(schema_setup)
        await self.connection.commit()

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

    async def create_playlist(self, user: discord.abc.User, name: str) -> bool:
        assert self.connection is not None
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
