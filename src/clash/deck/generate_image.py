from PIL import Image, ImageDraw, ImageFont

from config import paths


def get_average_elixir(cards: list[dict]) -> float:
    total = 0
    for card in cards:
        total += card["cost"]
    return total / 8


async def build_deck_image(cards: list[dict]) -> Image.Image:
    images = [card["img"] for card in cards]
    elixir_drop = Image.open(paths.DROPLET)
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
    font = ImageFont.truetype(paths.FONT, size=36)
    text = f"{average_cost:.1f}"

    # Center text on the droplet
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = drop_x + (drop_width - text_w) // 2
    text_y = drop_y + (drop_height - text_h) // 2

    draw.text((text_x, text_y), text, font=font, fill="white")

    return combined
