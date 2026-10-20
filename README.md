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
This bot uses `RoyaleAPI` and official `Clash Royale API` to find a player by their nickname and clan. Then it outputs the deck they played last, which is likely to be the deck they are playing right now.

I am using Python to scrape RoyaleAPI for nickname/clan search since the official API only lets you find a player by their tag. RoyaleAPI sits behind Cloudflare, so the bot routes its requests through a [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) instance that handles the challenge once and reuses the resulting browser session.
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

It has its own container, which only starts when you ask for it and runs until stopped:

```bash
docker compose up -d crawler
```

```bash
docker compose stop crawler
```

Stopping it saves the batch it's on first, which can take up to ~30 seconds. Its progress is in `data/crawler.log` and `docker compose logs -f crawler`. It keeps running across reboots until you stop it. A plain `docker compose up` / `down` leaves it out; use `docker compose --profile crawler down` to remove it too.

For one-off runs with options (`--max-players`, `--rps`, `--refresh-days`, see `--help`), run the script in the crawler container instead:

```bash
docker compose run --rm crawler python3 src/crawl_players.py --max-players 1000000
```

The database lives in `data/` rather than as a single mounted file so the bot and crawler containers share SQLite's journal. Databases from before this change have to be moved once, with everything stopped: `mkdir -p data && mv bot.db data/`.

By default the crawler uses the same key and RoyaleAPI proxy as the bot. On a server with a fixed IP it can call the official API directly with its own key, created for that IP at developer.clashroyale.com. Add these to `.env`:

```bash
CR_CRAWLER_API_KEY="key_allowed_for_your_server_ip"
CR_CRAWLER_API_BASE="https://api.clashroyale.com/v1"
```

The bot's own searches keep using `CR_API_KEY` through the proxy.

To keep everyone's clan up to date, re-crawl clans that haven't been checked in a while. Each clan request updates all of its members' names and clans and clears players who left, and the run stops once every clan is fresh:

```bash
docker compose run --rm crawler python3 src/crawl_players.py --refresh-days 7
```

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
