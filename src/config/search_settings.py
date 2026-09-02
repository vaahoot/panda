import os

import dotenv

from . import tokens

dotenv.load_dotenv()

ROYALE_API_PLAYER_SEARCH = "https://royaleapi.com/player/search/results?q={0}"
ROYALE_API_CLAN_SEARCH = "https://royaleapi.com/clans/search?name={0}"

CR_API_BATTLE_LOG = "https://proxy.royaleapi.dev/v1/players/{0}/battlelog"
CR_API_CLAN_MEMBERS = "https://proxy.royaleapi.dev/v1/clans/{0}/members"

CR_API_HEADERS = {"Authorization": f"Bearer {tokens.CR_API_KEY}"}

FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://localhost:8191/v1")
FLARESOLVERR_TIMEOUT_MS = 60000

