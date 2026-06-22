import io

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from config import DROPLET, FONT


def get_last_deck(data: list[dict] | None) -> list[dict[str, str]] | None:
    if not data:
        return None

    last_battle = dict()
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
            card_info["imgLink"] = card_icons["evolutionMedium"]
        elif card.get("evolutionLevel") == 2:
            card_info["imgLink"] = card_icons["heroMedium"]
        else:
            card_info["imgLink"] = card_icons["medium"]

        deck.append(card_info)

    return deck


async def fetch_image(url: str) -> Image.Image:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.read()
            return Image.open(io.BytesIO(data))


def get_average_elixir(cards: list[dict]) -> float:
    total = 0
    for card in cards:
        total += card["cost"]
    return total/8


async def build_deck_image(cards: list[dict]) -> Image.Image:
    images = [await fetch_image(card["imgLink"]) for card in cards]
    elixir_drop = Image.open(DROPLET)
    drop_width = elixir_drop.width
    drop_height = elixir_drop.height


    width = (sum(img.width for img in images) // 2) + drop_width
    height = max(img.height for img in images) * 2

    drop_x = width - drop_width
    drop_y = height - drop_height

    combined = Image.new("RGBA", (width, height))
    x = 0
    y = 0
    for img in images:
        if x >= (width - drop_width):
            x = 0
            y = height // 2

        combined.paste(img, (x, y))
        x += img.width

    average_cost = get_average_elixir(cards)
    combined.paste(elixir_drop, (drop_x, drop_y))

    draw = ImageDraw.Draw(combined)
    font = ImageFont.truetype(FONT, size=36)
    text = f"{average_cost:.1f}"

    # Center text on the droplet
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = drop_x + (drop_width - text_w) // 2
    text_y = drop_y + (drop_height - text_h) // 2

    draw.text((text_x, text_y), text, font=font, fill="white")

    return combined
