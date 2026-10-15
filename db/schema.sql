CREATE TABLE IF NOT EXISTS guild(
  guild_id INTEGER PRIMARY KEY,
  prefix TEXT DEFAULT 'p!'
);

CREATE TABLE IF NOT EXISTS guild_image_channel(
  guild_id INTEGER,
  channel_id INTEGER,
  PRIMARY KEY(guild_id, channel_id),
  FOREIGN KEY(guild_id) REFERENCES guild(guild_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS playlist(
  playlist_id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL COLLATE NOCASE,
  UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS playlist_track(
  track_id INTEGER PRIMARY KEY,
  playlist_id INTEGER NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  author TEXT,
  FOREIGN KEY(playlist_id) REFERENCES playlist(playlist_id) ON DELETE CASCADE
);
