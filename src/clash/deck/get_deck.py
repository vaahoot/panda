import asyncio
import io

from PIL import Image, UnidentifiedImageError

import net

# Card icons never change, so keep them for the lifetime of the bot
_image_cache: dict[str, Image.Image] = {}


async def fetch_image(url: str) -> Image.Image:
    if url in _image_cache:
        return _image_cache[url]

    async with net.session().get(url) as response:
        data = await response.read()

    img = Image.open(io.BytesIO(data))
    img.load()
    _image_cache[url] = img
    return img


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

    try:
        card_info["img"] = await fetch_image(card_icons[key])
    except UnidentifiedImageError:
        if key != "medium":
            try:
                card_info["img"] = await fetch_image(card_icons["medium"])
            except UnidentifiedImageError:
                card_info["img"] = None
        else:
            card_info["img"] = None

    return card_info
