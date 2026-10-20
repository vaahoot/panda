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

-- Clash Royale players collected by src/crawl_players.py, used for deck search by name
CREATE TABLE IF NOT EXISTS cr_player(
  tag TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  clan_name TEXT,
  search_name TEXT NOT NULL,     -- normalised name (NFKC, lowercase) for lookups
  battlelog_checked_at INTEGER   -- unix time, NULL = battle log not crawled yet
);

CREATE INDEX IF NOT EXISTS cr_player_search_name ON cr_player(search_name);
CREATE INDEX IF NOT EXISTS cr_player_pending ON cr_player(tag) WHERE battlelog_checked_at IS NULL;

-- Clans discovered by the crawler, their member lists are the main source of players
CREATE TABLE IF NOT EXISTS cr_clan(
  tag TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  members_checked_at INTEGER     -- unix time, NULL = members not crawled yet
);

CREATE INDEX IF NOT EXISTS cr_clan_pending ON cr_clan(tag) WHERE members_checked_at IS NULL;
