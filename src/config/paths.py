import os
import pathlib

FILE = pathlib.Path(__file__)
SRC = FILE.parent.parent
ROOT = SRC.parent

COGS = SRC / "cogs/"

ASSETS = ROOT / "assets/"
DB = ROOT / "db/"
# A folder, not just the file, so containers sharing the database also share SQLite's journal
DATA = ROOT / "data/"
DATABASE = DATA / "bot.db"
# Card images, downloaded once and reused for deck images
CARD_IMAGES = DATA / "cards/"
# The crawler container sets LOG_FILE so its progress doesn't mix with the bot's log
LOGS = pathlib.Path(os.getenv("LOG_FILE", ROOT / "bot.log"))

IMAGES = ASSETS / "images/"
FONTS = ASSETS / "fonts/"

SHIELD_TEMPLATE = IMAGES / "shield.png"
DROPLET = IMAGES / "elixir-droplet.png"

FONT = FONTS / "lilita.ttf"

SCHEMA = DB / "schema.sql"
