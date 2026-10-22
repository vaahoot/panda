import urllib.parse

from clash.scraping.search import cr_api_get
from config import search_settings

# Player tags only ever use these characters
TAG_CHARACTERS = set("0289PYLQGRJCUV")
TAG_MIN_LENGTH = 3
TAG_MAX_LENGTH = 12


def normalise_tag(tag: str) -> str | None:
    """Returns the tag as the API wants it ("#ABC123"), or None if it can't be a player tag.
    Accepts it with or without "#", in any case, and with the common O/0 mix-up."""
    tag = tag.strip().lstrip("#").upper().replace("O", "0")
    if not TAG_MIN_LENGTH <= len(tag) <= TAG_MAX_LENGTH:
        return None
    if not set(tag) <= TAG_CHARACTERS:
        return None
    return f"#{tag}"


async def get_player(tag: str) -> dict:
    """Raises aiohttp.ClientResponseError with status 404 if no player has this tag."""
    url = search_settings.CR_API_PLAYER.format(urllib.parse.quote(tag))
    return await cr_api_get(url)
