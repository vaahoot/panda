# Panda

A Discord bot that finds a Clash Royale player by their nickname and clan, or from a screenshot, and shows the decks they played last. That's likely the deck they're playing right now. It also plays music in voice channels.

## Demos

<details>
  <summary>Search by Nickname+Clan Demo</summary>
  
  <img width="530" height="538" alt="SearchByNameClanDemo" src="https://github.com/user-attachments/assets/ddbc3d95-1a3e-458c-8ee9-08bbb8708c84" />

</details>
<details>
  <summary>Search by Screenshot</summary>
  
  <img width="530" height="528" alt="SearchByScreenshotDemo" src="https://github.com/user-attachments/assets/4c740b08-cdc6-4a78-90f8-4ef2e7c2b3bb" />
  
</details>

## How it works

The official Clash Royale API only lets you look a player up by their tag. So the bot keeps its own database of players, filled by the [crawler](#player-database-crawler), and searches it by name and clan. If the player isn't stored yet, it falls back to the API's clan search and looks for the name among the members of the matching clans.

Screenshots are read by Claude through the Anthropic API, which pulls out the player's name and clan. The deck images are drawn with Pillow from the card icons, which are downloaded once and kept in `data/cards/`.

Music goes through [Lavalink](https://lavalink.dev), with the YouTube and LavaSrc (Spotify) plugins.

## Services

`docker compose` runs everything:

| Service | What it is |
|---|---|
| `bot` | The bot itself |
| `lavalink` | Lavalink audio server for music. The bot expects it at `lavalink:2333`, so the bot has to run in compose too |
| `spotify-tokener` | Gets Spotify tokens for LavaSrc |
| `crawler` | Fills the player database. Only starts when asked for, see [Player database crawler](#player-database-crawler) |

## Setup

### 1. Get the keys

- **Discord bot token:** create an application at the [Discord Developer Portal](https://discord.com/developers/applications) and add a bot. Under **Bot → Privileged Gateway Intents**, turn on **Server Members Intent** and **Message Content Intent**. The bot needs both.
- **Clash Royale API key:** create one at [developer.clashroyale.com](https://developer.clashroyale.com). Keys are bound to IP addresses. By default the bot goes through the RoyaleAPI proxy, so allow the proxy's IP, `45.79.218.79`. To call the API directly from a server instead, see [Calling the API directly](#calling-the-api-directly).
- **Anthropic API key:** from the [Claude Console](https://platform.claude.com). It's used for screenshot search.
- **Music (optional):** a YouTube OAuth refresh token for the YouTube plugin, and a Spotify client secret for LavaSrc. The Spotify client ID is set in `application.yml`.

### 2. Create `.env`

Clone the repo and create `.env` in the root:

```bash
git clone git@github.com:vaahoot/panda.git
cd panda
```

```bash
DISCORD_API_KEY="your_discord_bot_token"
CR_API_KEY="your_cr_api_key"
ANTHROPIC_API_KEY="your_anthropic_api_key"
LAVALINK_PASSWORD="any_password"

# Music
REFRESH_TOKEN="youtube_oauth_refresh_token"
SPOTIFY_API_KEY="spotify_client_secret"
```

| Variable | Required | Used for |
|---|---|---|
| `DISCORD_API_KEY` | Yes | Discord bot token |
| `CR_API_KEY` | Yes | Clash Royale API key for the bot's searches |
| `ANTHROPIC_API_KEY` | Yes | Reading screenshots |
| `LAVALINK_PASSWORD` | Yes | Shared by the bot and Lavalink. Pick any value |
| `REFRESH_TOKEN` | For YouTube | YouTube OAuth refresh token for Lavalink's YouTube plugin |
| `SPOTIFY_API_KEY` | For Spotify | Spotify client secret for LavaSrc |
| `CR_API_BASE` | No | Clash Royale API base URL. Defaults to the RoyaleAPI proxy, `https://proxy.royaleapi.dev/v1` |
| `CR_CRAWLER_API_KEY` | No | A separate key for the crawler, so it has its own rate limit. Defaults to `CR_API_KEY` |
| `CR_CRAWLER_API_BASE` | No | API base URL for just the crawler. Defaults to `CR_API_BASE` |

`.env` is git-ignored, so keys never get committed.

### 3. Run it

```bash
docker compose up --build -d
```

The first time it starts, the bot creates `data/bot.db` from `db/schema.sql`. Schema changes are applied the same way on later restarts.

## Running it

`src/` and `db/` are mounted into the containers, so code changes only need a restart:

```bash
docker compose restart bot
```

Changes to `requirements.txt` or the `Dockerfile` need a rebuild:

```bash
docker compose up --build -d
```

Logs go to `bot.log` in the repo root, and also to:

```bash
docker compose logs -f bot
```

Everything the bot keeps lives in `data/`: the database `bot.db` and the card images in `cards/`. It's git-ignored and mounted into the bot and crawler containers. The database is in a folder, not mounted as a single file, so the two containers share SQLite's journal. Databases from before this change have to be moved once, with everything stopped:

```bash
mkdir -p data && mv bot.db data/
```

Bot-wide settings, such as the default command prefix, colours and the screenshot cooldown, are in `src/config/settings.py`. Every new 20-win challenge has a new event tag. Add it to `TWENTY_WIN_EVENT_TAGS` there (take it from a battle log's `eventTag`) so its decks are shown as 20-win decks.

## Player database crawler

`src/crawl_players.py` fills the `cr_player` table in `data/bot.db` with player tags, names and clan names from the official API, so players can be found by name without scraping. It starts from clan rankings and clan search in every location, then crawls clan member lists and battle logs. It can be stopped at any time and picks up where it left off when run again.

It has its own container, which only starts when you ask for it and runs until it's stopped. It runs with `--forever`:

- **It keeps data fresh as it goes,** with no separate refresh pass. Every player in a clan's member list is updated.
- **Clans are re-checked when they come up again.** A stored clan that shows up again, in a battle log for example, has its members re-crawled if it wasn't checked in the last day. That also clears out players who left.
- **Battle logs only add players.** They can be days old, so they only add new players and update names. When a battle shows a stored player in a different clan, both clans are re-checked and their member lists decide.
- **It never runs out of work.** Once it has crawled every battle log, it starts over with the oldest.

```bash
docker compose up -d crawler
```

```bash
docker compose stop crawler
```

Stopping it saves the batch it's on first, which can take up to ~30 seconds. Its progress is in `data/crawler.log` and in `docker compose logs -f crawler`. It keeps running across reboots until you stop it. A plain `docker compose up` or `down` leaves it out. Use `docker compose --profile crawler down` to remove it too.

For one-off runs with options (`--max-players`, `--rps`, see `--help`), run the script in the crawler container instead:

```bash
docker compose run --rm crawler python3 src/crawl_players.py --max-players 1000000
```

### Calling the API directly

By default the bot and the crawler send API requests through the RoyaleAPI proxy, which only needs a key allowed for the proxy's IP. On a server with a fixed IP, they can call the official API directly instead, which is faster. Create keys allowed for that IP at developer.clashroyale.com and add to `.env`:

```bash
CR_API_BASE="https://api.clashroyale.com/v1"
CR_API_KEY="key_allowed_for_your_server_ip"          # the bot's searches
CR_CRAWLER_API_KEY="another_key_for_your_server_ip"  # the crawler, so it has its own rate limit
```

### Maintenance

Databases crawled before players had a `clan_tag` can fill in most of them from clan names that only one stored clan uses:

```bash
docker compose exec bot python3 src/backfill_clan_tags.py
```

Name search uses an FTS5 trigram index (`cr_player_fts`), kept in sync by triggers. The bot builds it the first time it connects to a database that doesn't have it yet, which takes about 5 minutes for 10M players. If the database is ever `VACUUM`ed, rebuild it:

```bash
sqlite3 data/bot.db "INSERT INTO cr_player_fts(cr_player_fts) VALUES('rebuild')"
```

Player and clan names are searched by a normalised key (`normalise()` in `src/clash/names.py`). After changing that function, stop the crawler and recompute the stored keys:

```bash
docker compose exec bot python3 src/renormalise_players.py
```

## Limitations

1. The search isn't guaranteed to work if the player has a very common name and either has no clan or is in a clan with a common name too.
2. Even when the search works, your opponent may not be playing the same deck as in their last game.
