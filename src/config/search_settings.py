import os

import dotenv

from . import tokens

dotenv.load_dotenv()

ROYALE_API_PLAYER_SEARCH = "https://royaleapi.com/player/search/results?q={0}"
ROYALE_API_CLAN_SEARCH = "https://royaleapi.com/clans/search?name={0}"

CR_API_BATTLE_LOG = "https://proxy.royaleapi.dev/v1/players/{0}/battlelog"
CR_API_CLAN_MEMBERS = "https://proxy.royaleapi.dev/v1/clans/{0}/members"
CR_API_CLAN_SEARCH = "https://proxy.royaleapi.dev/v1/clans?name={0}&limit=30"

CR_API_HEADERS = {"Authorization": f"Bearer {tokens.CR_API_KEY}"}
CR_API_MAX_CONCURRENT = 10
CR_API_RETRIES = 3

FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://flaresolverr:8191/v1")
FLARESOLVERR_TIMEOUT_MS = 60000

