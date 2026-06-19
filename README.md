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

```OPENAI_API_KEY``` - OpenAI API token.

Additionally I'm using Pillow to create the image of the deck that the bot then sends to the chat.

## Installation and Running the bot
Clone the repo:
```bash
git clone git@github.com:vaahoot/cr-deck-bot.git
cd cr-deck-bot
```

All the dependencies can be installed with:
```bash
pip3 install -r requirements.txt
```

Set environment variables:
```bash
export CR_KEY="your_cr_api_key"
export DISCORD_KEY="your_discord_bot_token"
export OPENAI_API_KEY="your_openai_api_key"
```

Start FlareSolverr (any reachable instance works; this one is exposed on port 8191):
```bash
docker run -d --name flaresolverr -p 8191:8191 --restart unless-stopped ghcr.io/flaresolverr/flaresolverr:latest
```

Run the bot:
```bash
cd src/
python3 bot.py
```

Or run everything (bot + FlareSolverr) together:
```bash
docker compose up --build -d
```

## Usage
When you create your bot and get a token, invite it to your server and set the token in your environment variables.

```
!d <nickname>, <clan>
```
Clan is optional but if not given, only users with no clan will be searched. Exact names are recommended although incomplete name/clan can still work.

```
!i <attach image to the message>
```
The image should be a screenshot of the battle, an API call is made to chatGPT to identify the name and clan and then search for the deck. Useful when the nickname is in another language or contains a lot of emotes and will take long to write.

```
!image_channel <on/off>
```
Saves this channel as an image channel. In every image channel, the bot will try to search for a deck for every image sent, useful if you want to have a dedicated channel in which you can just send screenshots and get decks without the `!i` command to save time.

```
!gpt <version>
```
Chooses a GPT version to use on the server. Running this command without the version attribute will return the currently chosen version.

## Limitations
1. The search is not guaranteed to work if the player has a very common name and no clan or their clan has a common name too.

2. Even when the search works, there is a chance your opponent is not playing the same deck as last game.
