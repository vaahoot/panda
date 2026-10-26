# Clash Royale Deck Bot

## Demos

<details>
  <summary>Search by Nickname+Clan Demo</summary>
  
  <img width="530" height="538" alt="SearchByNameClanDemo" src="https://github.com/user-attachments/assets/ddbc3d95-1a3e-458c-8ee9-08bbb8708c84" />

</details>
<details>
  <summary>Search by Screenshot</summary>
  
  <img width="530" height="528" alt="SearchByScreenshotDemo" src="https://github.com/user-attachments/assets/4c740b08-cdc6-4a78-90f8-4ef2e7c2b3bb" />
  
</details>

## What it does
This bot uses the official `Clash Royale API` to find a player by their nickname and clan. Then it outputs the deck they played last, which is likely to be the deck they are playing right now.

The official API only lets you look a player up by their tag, so the bot keeps its own database of players (see [Player database crawler](#player-database-crawler)) and searches it by name and clan. If the player isn't stored yet, it falls back to the API's clan search and looks for the name among the members of matching clans.
The bot expects three API keys in your environment variables:

```CR_KEY``` - Clash Royale API key.

```DISCORD_KEY``` - Discord bot token.

```ANTHROPIC_API_KEY``` - Anthropic API token.

Additionally I'm using Pillow to create the image of the deck that the bot then sends to the user.

## Installation and Running the bot
Clone the repo:
```bash
git clone git@github.com:vaahoot/panda.git
cd panda
```

All the dependencies can be installed with:
```bash
pip3 install -r requirements.txt
```

Set environment variables:
```bash
export CR_KEY="your_cr_api_key"
export DISCORD_KEY="your_discord_bot_token"
export ANTHROPIC_API_KEY="your_anthropic_api_key"
```

Run everything together:
```bash
docker compose up --build -d
```

## Player database crawler
`src/crawl_players.py` fills the `cr_player` table in `data/bot.db` with player tags, names and clan names from the official API, so players can be found by name without scraping. It starts from clan rankings and clan search in every location, then crawls clan member lists and battle logs. It can be stopped at any time and picks up where it left off when run again.

It has its own container, which only starts when you ask for it and runs until stopped. It runs with `--forever`, and keeps data fresh as it goes instead of in a separate refresh: every player in a clan's member list is updated, and a stored clan that shows up again (in a battle log, say) has its members re-crawled if it wasn't checked in the last day, which also clears players who left. Battle logs can be days old, so they only add new players and update names; when a battle shows a stored player in a different clan, both clans are re-checked and their member lists decide. Once every battle log was crawled it starts over with the oldest, so it never runs out of players to come across:

```bash
docker compose up -d crawler
```

```bash
docker compose stop crawler
```

Stopping it saves the batch it's on first, which can take up to ~30 seconds. Its progress is in `data/crawler.log` and `docker compose logs -f crawler`. It keeps running across reboots until you stop it. A plain `docker compose up` / `down` leaves it out; use `docker compose --profile crawler down` to remove it too.

For one-off runs with options (`--max-players`, `--rps`, see `--help`), run the script in the crawler container instead:

```bash
docker compose run --rm crawler python3 src/crawl_players.py --max-players 1000000
```

The database lives in `data/` rather than as a single mounted file so the bot and crawler containers share SQLite's journal. Databases from before this change have to be moved once, with everything stopped: `mkdir -p data && mv bot.db data/`.

By default the bot and the crawler send API requests through the RoyaleAPI proxy, which only needs a key allowed for the proxy's IP. On a server with a fixed IP they can call the official API directly instead, which is faster. Create keys allowed for that IP at developer.clashroyale.com and add to `.env`:

```bash
CR_API_BASE="https://api.clashroyale.com/v1"
CR_API_KEY="key_allowed_for_your_server_ip"          # the bot's searches
CR_CRAWLER_API_KEY="another_key_for_your_server_ip"  # the crawler, so it has its own rate limit
```

`CR_CRAWLER_API_BASE` sends just the crawler somewhere else, overriding `CR_API_BASE`.

Databases crawled before players had a `clan_tag` can fill most of them from clan names that only one stored clan uses:

```bash
docker compose exec bot python3 src/backfill_clan_tags.py
```

Name search uses an FTS5 trigram index (`cr_player_fts`), kept in sync by triggers. The bot builds it the first time it connects to a database that doesn't have it yet (about 5 minutes for 10M players). If the database is ever `VACUUM`ed, rebuild it:

```bash
sqlite3 data/bot.db "INSERT INTO cr_player_fts(cr_player_fts) VALUES('rebuild')"
```

Player and clan names are searched by a normalised key (`normalise()` in `src/clash/names.py`). After changing that function, stop the crawler and recompute the stored keys:

```bash
docker compose exec bot python3 src/renormalise_players.py
```

## Limitations
```
1. The search is not guaranteed to work if the player has a very common name and no clan or their clan has a common name too.

2. Even when the search works, there is a chance your opponent is not playing the same deck as last game.
```
