import pathlib

FILE = pathlib.Path(__file__)
SRC = FILE.parent.parent
ROOT = SRC.parent

COGS = SRC / "cogs/"

ASSETS = ROOT / "assets/"
DB = ROOT / "db/"
LOGS = ROOT / "bot.log"
DATABASE = ROOT / "bot.db"

IMAGES = ASSETS / "images/"
FONTS = ASSETS / "fonts/"

SHIELD_TEMPLATE = IMAGES / "shield.png"
DROPLET = IMAGES / "elixir-droplet.png"

FONT = FONTS / "lilita.ttf"

SCHEMA = DB / "schema.sql"
