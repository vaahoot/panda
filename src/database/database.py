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
