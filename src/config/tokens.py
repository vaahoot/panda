import os

import dotenv

dotenv.load_dotenv()

DISCORD_API_KEY = os.getenv("DISCORD_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

CR_API_KEY = os.getenv("CR_API_KEY")
CR_API_HEADERS = {"Authorization": f"Bearer {CR_API_KEY}"}

LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "password")
