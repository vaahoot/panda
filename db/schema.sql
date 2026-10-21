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
  clan_tag TEXT,                 -- NULL = no clan, or left the clan it was last seen in
  clan_name TEXT,
  search_name TEXT NOT NULL,     -- normalise(name), letters and digits only, for lookups
  battlelog_checked_at INTEGER   -- unix time, NULL = battle log not crawled yet
);

CREATE INDEX IF NOT EXISTS cr_player_search_name ON cr_player(search_name);
CREATE INDEX IF NOT EXISTS cr_player_pending ON cr_player(tag) WHERE battlelog_checked_at IS NULL;
CREATE INDEX IF NOT EXISTS cr_player_clan_tag ON cr_player(clan_tag);

-- Trigram index over search_name for fast substring search (LIKE '%...%' with 3+ characters).
-- It points at cr_player rows by rowid. VACUUM can renumber those, so after a VACUUM run:
--   INSERT INTO cr_player_fts(cr_player_fts) VALUES('rebuild');
CREATE VIRTUAL TABLE IF NOT EXISTS cr_player_fts USING fts5(
  search_name, content='cr_player', content_rowid='rowid', tokenize='trigram', detail='none'
);

-- Keep the index in sync with cr_player
CREATE TRIGGER IF NOT EXISTS cr_player_fts_insert AFTER INSERT ON cr_player BEGIN
  INSERT INTO cr_player_fts(rowid, search_name) VALUES (new.rowid, new.search_name);
END;

CREATE TRIGGER IF NOT EXISTS cr_player_fts_delete AFTER DELETE ON cr_player BEGIN
  INSERT INTO cr_player_fts(cr_player_fts, rowid, search_name) VALUES ('delete', old.rowid, old.search_name);
END;

-- Upserts rewrite search_name on every update, only reindex when it actually changed
CREATE TRIGGER IF NOT EXISTS cr_player_fts_update AFTER UPDATE OF search_name ON cr_player
WHEN old.search_name IS NOT new.search_name BEGIN
  INSERT INTO cr_player_fts(cr_player_fts, rowid, search_name) VALUES ('delete', old.rowid, old.search_name);
  INSERT INTO cr_player_fts(rowid, search_name) VALUES (new.rowid, new.search_name);
END;

-- Clans discovered by the crawler, their member lists are the main source of players
CREATE TABLE IF NOT EXISTS cr_clan(
  tag TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  search_name TEXT,              -- normalise(name), same key as cr_player.search_name
  members_checked_at INTEGER     -- unix time, NULL = members not crawled yet
);

CREATE INDEX IF NOT EXISTS cr_clan_pending ON cr_clan(tag) WHERE members_checked_at IS NULL;
CREATE INDEX IF NOT EXISTS cr_clan_checked_at ON cr_clan(members_checked_at);
CREATE INDEX IF NOT EXISTS cr_clan_search_name ON cr_clan(search_name);
