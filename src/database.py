import aiosqlite
import aiofiles
from pathlib import Path


class Database:
    def __init__(self, path: Path, schema: Path):
        self.path = path
        self.schema = schema

    async def connect(self):
        self.connection = await aiosqlite.connect(self.path)

        async with aiofiles.open(self.schema) as f:
            schema_setup = await f.read()
        await self.connection.executescript(schema_setup)
        await self.connection.commit()

    async def add_guild(self, guild):
        await self.connection.execute(
            "INSERT OR IGNORE INTO guild(guild_id) VALUES(?)",
            (guild.id,)
        )
        await self.connection.commit()

    async def remove_guild(self, guild):
        await self.connection.execute(
            "DELETE FROM guild WHERE guild_id = ?",
            (guild.id,)
        )
        await self.connection.commit()

    async def add_image_channel(self, guild, channel):
        cursor = await self.connection.execute(
            "INSERT OR IGNORE INTO guild_image_channel(guild_id, channel_id) VALUES(?, ?)",
            (guild.id, channel.id)
        )
        await self.connection.commit()
        return cursor.rowcount > 0

    async def remove_image_channel(self, guild, channel):
        cursor = await self.connection.execute(
            "DELETE FROM guild_image_channel \
            WHERE guild_id = ? AND channel_id = ?",
            (guild.id, channel.id)
        )
        await self.connection.commit()
        return cursor.rowcount > 0

    async def is_image_channel(self, channel, guild):
        cursor = await self.connection.execute(
            "SELECT 1 \
            FROM guild_image_channel \
            WHERE guild_id = ? AND channel_id = ?",
            (guild.id, channel.id)
        )
        row = await cursor.fetchone()
        return row is not None
