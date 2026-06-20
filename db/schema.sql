CREATE TABLE IF NOT EXISTS guild(
  guild_id INTEGER PRIMARY KEY,
  prefix TEXT DEFAULT '!'
);

CREATE TABLE IF NOT EXISTS guild_image_channel(
  guild_id INTEGER,
  channel_id INTEGER,
  PRIMARY KEY(guild_id, channel_id),
  FOREIGN KEY(guild_id) REFERENCES guild(guild_id) ON DELETE CASCADE
)
