import io

import aiohttp
from PIL import Image, UnidentifiedImageError


async def fetch_image(url: str) -> Image.Image:
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        data = await response.read()
        return Image.open(io.BytesIO(data))


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

    deck = []
    for card in cards:
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

        deck.append(card_info)

    return deck
