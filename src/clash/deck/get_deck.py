import asyncio
import io
import pathlib
import urllib.parse

import aiohttp
from PIL import Image

import log
import net
from config import paths, settings

# Everything that can go wrong getting one card image. PIL raises OSError for anything it
# can't decode (UnidentifiedImageError is one) and aiohttp for failed downloads
IMAGE_ERRORS = (OSError, aiohttp.ClientError, asyncio.TimeoutError)

# Card icons never change, so keep them in memory for the lifetime of the bot
_image_cache: dict[str, Image.Image] = {}


def card_image_file(card_id: int | str, key: str, url: str) -> pathlib.Path:
    # The URL's file name changes when Supercell updates a card's art, so new art gets downloaded
    url_name = pathlib.PurePosixPath(urllib.parse.urlparse(url).path).name
    return paths.CARD_IMAGES / f"{card_id}_{key}_{url_name}"


def save_file(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a half-written file is never read as a card
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)


def decode(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    # Decodes the whole image, so a cut-off file fails here rather than when drawing the deck
    img.load()
    return img


async def fetch_image(url: str, file: pathlib.Path | None = None) -> Image.Image:
    """Card image from memory, then from disk, then downloaded and saved to disk."""
    if url in _image_cache:
        return _image_cache[url]

    if file is not None and file.exists():
        try:
            img = decode(await asyncio.to_thread(file.read_bytes))
            _image_cache[url] = img
            return img
        except OSError as e:
            # A damaged file would otherwise fail on every deck, get a fresh copy instead
            await log.warning(f"Stored card image {file.name} is unreadable, downloading it again: {e}")
            await asyncio.to_thread(file.unlink, missing_ok=True)

    async with net.session().get(url) as response:
        response.raise_for_status()
        data = await response.read()

    # Only valid images are saved: anything that doesn't decode raises before this
    img = decode(data)
    if file is not None:
        await asyncio.to_thread(save_file, file, data)
    _image_cache[url] = img
    return img


async def fetch_card_image(card: dict, key: str) -> Image.Image:
    url = card["iconUrls"][key]
    return await fetch_image(url, card_image_file(card.get("id", "unknown"), key, url))


TWENTY_WINS = "20 Wins"
RANKED = "Ranked"
LADDER = "Ladder"


def is_twenty_wins(battle: dict) -> bool:
    return battle.get("eventTag") in settings.TWENTY_WIN_EVENT_TAGS


def is_ranked(battle: dict) -> bool:
    return battle.get("type") == "pathOfLegend"


# Ladder games are "Showdown_Friendly" below 14k trophies and "Ladder" above
LADDER_GAME_MODES = {"Ladder", "Showdown_Friendly"}


def is_ladder(battle: dict) -> bool:
    # Ladder games come as type "PvP" or "trail", and "trail" also covers events (draft,
    # event decks) whose decks aren't the player's own. The game mode tells them apart
    return (battle.get("gameMode") or {}).get("name") in LADDER_GAME_MODES


# In the order the menu lists them. The first one the player has is the deck shown first
DECK_MODES = {TWENTY_WINS: is_twenty_wins, RANKED: is_ranked, LADDER: is_ladder}


async def get_last_decks(data: list[dict] | None) -> dict[str, list[dict]]:
    """The deck of the most recent battle of each mode, in DECK_MODES order. Modes without a battle
    in the log are left out, so an empty dict means there's no deck to show."""
    battles = {}
    for mode, matches in DECK_MODES.items():
        battle = next((b for b in data or [] if matches(b)), None)
        if battle is not None:
            battles[mode] = battle["team"][0]["cards"]

    decks = await asyncio.gather(
        *(asyncio.gather(*(get_card_info(card) for card in cards)) for cards in battles.values())
    )
    return {mode: list(deck) for mode, deck in zip(battles, decks)}


async def get_card_info(card: dict) -> dict:
    card_info = {}

    card_info["name"] = card.get("name", "Unknown")
    card_info["cost"] = card.get("elixirCost", 1.5)

    card_icons = card["iconUrls"]

    if card.get("evolutionLevel") == 1:
        key = "evolutionMedium"
    elif card.get("evolutionLevel") == 2:
        key = "heroMedium"
    else:
        key = "medium"
    if key not in card_icons:
        key = "medium"

    # The evolution/hero image first, then the normal one, then the deck image draws a placeholder.
    # One bad image never fails the whole deck
    card_info["img"] = None
    for image_key in dict.fromkeys([key, "medium"]):
        try:
            card_info["img"] = await fetch_card_image(card, image_key)
            break
        except IMAGE_ERRORS as e:
            await log.warning(f"Couldn't get the {image_key} image for {card_info['name']}: {type(e).__name__}: {e}")

    return card_info
