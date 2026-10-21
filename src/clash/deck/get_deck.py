import asyncio
import io
import pathlib
import urllib.parse

from PIL import Image, UnidentifiedImageError

import net
from config import paths

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


async def fetch_image(url: str, file: pathlib.Path | None = None) -> Image.Image:
    """Card image from memory, then from disk, then downloaded and saved to disk."""
    if url in _image_cache:
        return _image_cache[url]

    if file is not None and file.exists():
        data = await asyncio.to_thread(file.read_bytes)
    else:
        async with net.session().get(url) as response:
            data = await response.read()

    img = Image.open(io.BytesIO(data))
    img.load()
    # Only valid images are kept, an error page would raise UnidentifiedImageError above
    if file is not None and not file.exists():
        await asyncio.to_thread(save_file, file, data)
    _image_cache[url] = img
    return img


async def fetch_card_image(card: dict, key: str) -> Image.Image:
    url = card["iconUrls"][key]
    return await fetch_image(url, card_image_file(card.get("id", "unknown"), key, url))


async def get_last_deck(data: list[dict] | None) -> list[dict[str, str]] | None:
    if not data:
        return None

    last_battle = {}
    for battle in data:
        if battle.get("type") == "pathOfLegend":
            last_battle = battle
            break

    if not last_battle:
        for battle in data:
            if battle.get("type") == "PvP":
                last_battle = battle
                break

    if not last_battle:
        return None

    team = last_battle["team"][0]
    cards = team["cards"]

    return list(await asyncio.gather(*(get_card_info(card) for card in cards)))


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

    try:
        card_info["img"] = await fetch_card_image(card, key)
    except UnidentifiedImageError:
        if key != "medium":
            try:
                card_info["img"] = await fetch_card_image(card, "medium")
            except UnidentifiedImageError:
                card_info["img"] = None
        else:
            card_info["img"] = None

    return card_info
