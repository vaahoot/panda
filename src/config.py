import os
from pathlib import Path

ROYALE_API_PLAYER_SEARCH = "https://royaleapi.com/player/search/results?q={0}"
ROYALE_API_CLAN_SEARCH = "https://royaleapi.com/clans/search?name={0}"
CLASH_API_BATTLE_LOG = "https://proxy.royaleapi.dev/v1/players/{0}/battlelog"
CLASH_API_CLAN_MEMBERS = "https://proxy.royaleapi.dev/v1/clans/{0}/members"

CLASH_API_KEY = os.getenv("CR_KEY")
CLASH_API_HEADERS = {"Authorization": f"Bearer {CLASH_API_KEY}"}

DISCORD_API_KEY = os.getenv("DISCORD_KEY")

GPT_DEFAULT_VERSION = "gpt-4o"

PROMPT = """You are analyzing a cropped section of a Clash Royale game screen showing a single player's information.
Extract the player name and clan name from the image.
The player name appears to the right of the shield icon. The clan name is smaller and appears directly below the player name in a yellowish colour.
Return ONLY a valid JSON object with no markdown, no explanation, no code blocks:
{"name": "player_name", "clan": "clan_name"}
Rules:
- If no clan is visible, set clan to null
- If you cannot read the name, return {"name": null, "clan": null}
- Preserve exact spelling and capitalisation
- If you are uncertain about specific characters, output the largest substring you are certain about"""

ROOT = Path(__file__).parent.parent
ASSETS = ROOT / "assets/"
IMAGES = ASSETS / "images/"
FONTS = ASSETS / "fonts/"
DB = ROOT / "db"

LOGS = ROOT / "bot.log"
SHIELD_TEMPLATE = IMAGES / "shield.png"
DROPLET = IMAGES / "elixir-droplet.png"
FONT = FONTS / "lilita.ttf"
DATABASE = ROOT / "bot.db"
SCHEMA = DB / "schema.sql"
