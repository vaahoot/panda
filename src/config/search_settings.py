import os

import dotenv

from . import tokens

dotenv.load_dotenv()

ROYALE_API_PLAYER_SEARCH = "https://royaleapi.com/player/search/results?q={0}"

# Where the bot (and by default the crawler) sends Clash Royale API requests. The RoyaleAPI proxy
# works from any IP with a key allowed for the proxy's IP. On a server with a fixed IP, set
# CR_API_BASE=https://api.clashroyale.com/v1 with keys allowed for that IP to skip the proxy
CR_API_PROXY = "https://proxy.royaleapi.dev/v1"
CR_API_BASE = (os.getenv("CR_API_BASE") or CR_API_PROXY).rstrip("/")
CR_API_BATTLE_LOG = CR_API_BASE + "/players/{0}/battlelog"
CR_API_CLAN_MEMBERS = CR_API_BASE + "/clans/{0}/members"
CR_API_CLAN_SEARCH = CR_API_BASE + "/clans?name={0}&limit=30"

CR_API_HEADERS = {"Authorization": f"Bearer {tokens.CR_API_KEY}"}

# crawl_players.py follows CR_API_BASE unless CR_CRAWLER_API_BASE overrides it just for the crawler
CR_CRAWLER_API_BASE = (os.getenv("CR_CRAWLER_API_BASE") or CR_API_BASE).rstrip("/")
CR_CRAWLER_API_HEADERS = {"Authorization": f"Bearer {tokens.CR_CRAWLER_API_KEY}"}

CR_API_MAX_CONCURRENT = 10
CR_API_RETRIES = 3

FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://flaresolverr:8191/v1")
FLARESOLVERR_TIMEOUT_MS = 60000

