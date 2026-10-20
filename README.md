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
`src/crawl_players.py` fills the `cr_player` table in `bot.db` with player tags, names and clan names from the official API, so players can be found by name without scraping. It starts from clan rankings and clan search in every location, then crawls clan member lists and battle logs. It can be stopped at any time and picks up where it left off when run again.

```bash
docker compose exec bot python3 src/crawl_players.py --max-players 1000000
```

Run it with `exec` inside the bot container so both share the same SQLite file and journal. Use `--rps` to change the request rate (default 15/s) and `--help` for the other options.

Player names are searched by a normalised key (`normalise()` in `src/clash/scraping/search.py`). After changing that function, stop the crawler and recompute the stored keys:

```bash
docker compose exec bot python3 src/renormalise_players.py
```

## Limitations
```
1. The search is not guaranteed to work if the player has a very common name and no clan or their clan has a common name too.

2. Even when the search works, there is a chance your opponent is not playing the same deck as last game.
```
