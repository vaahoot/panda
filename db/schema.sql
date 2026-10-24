CREATE TABLE IF NOT EXISTS guild(
  guild_id INTEGER PRIMARY KEY,
  prefix TEXT DEFAULT 'p!',
  mods_create_playlists INTEGER NOT NULL DEFAULT 0  -- 1 = only Manage Server can create server playlists
);

CREATE TABLE IF NOT EXISTS guild_image_channel(
  guild_id INTEGER,
  channel_id INTEGER,
  PRIMARY KEY(guild_id, channel_id),
  FOREIGN KEY(guild_id) REFERENCES guild(guild_id) ON DELETE CASCADE
);

-- Discord users. "user" is a keyword in most SQL dialects, hence the prefix
CREATE TABLE IF NOT EXISTS discord_user(
  user_id INTEGER PRIMARY KEY,
  cr_tag TEXT                    -- their Clash Royale player tag, e.g. #2PP, NULL = not set
);

-- A playlist belongs to a user, or with guild_id set to a server. guild_id doesn't reference
-- guild on purpose: that row is deleted when the bot leaves, server playlists are kept
CREATE TABLE IF NOT EXISTS playlist(
  playlist_id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,           -- the owner, or whoever created a server playlist
  guild_id INTEGER,                   -- NULL = personal playlist
  name TEXT NOT NULL COLLATE NOCASE,
  locked INTEGER NOT NULL DEFAULT 0,  -- server playlists: 1 = only the creator and mods can edit
  FOREIGN KEY(user_id) REFERENCES discord_user(user_id) ON DELETE CASCADE
);

-- Names are unique among a user's playlists and among a server's, a user's playlist and a
-- server playlist can share a name
CREATE UNIQUE INDEX IF NOT EXISTS playlist_user_name ON playlist(user_id, name) WHERE guild_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS playlist_guild_name ON playlist(guild_id, name) WHERE guild_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS playlist_track(
  track_id INTEGER PRIMARY KEY,
  playlist_id INTEGER NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  author TEXT,
  added_by INTEGER,              -- user id, NULL = saved before this was recorded
  FOREIGN KEY(playlist_id) REFERENCES playlist(playlist_id) ON DELETE CASCADE
);

-- A track can only be in a playlist once. An index rather than UNIQUE in the table
-- so it also applies to databases made before it
CREATE UNIQUE INDEX IF NOT EXISTS playlist_track_url ON playlist_track(playlist_id, url);

-- Clash Royale players collected by src/crawl_players.py, used for deck search by name
CREATE TABLE IF NOT EXISTS cr_player(
  tag TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  clan_tag TEXT,                 -- NULL = no clan, or left the clan it was last seen in
  clan_name TEXT,
  search_name TEXT NOT NULL,     -- normalise(name), letters and digits only, for lookups
  battlelog_checked_at INTEGER,  -- unix time, NULL = battle log not crawled yet
  updated_at INTEGER             -- unix time name/clan were last confirmed, NULL = unknown or left a clan
);

CREATE INDEX IF NOT EXISTS cr_player_search_name ON cr_player(search_name);
CREATE INDEX IF NOT EXISTS cr_player_pending ON cr_player(tag) WHERE battlelog_checked_at IS NULL;
CREATE INDEX IF NOT EXISTS cr_player_clan_tag ON cr_player(clan_tag);
-- Clanless players by how stale they are, for the crawler's refresh (clan members are refreshed with their clan)
CREATE INDEX IF NOT EXISTS cr_player_clanless_updated ON cr_player(updated_at) WHERE clan_tag IS NULL AND clan_name IS NULL;

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
