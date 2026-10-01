import asyncio
import io

from PIL import Image, ImageDraw, ImageFont

from config import paths

# Size of the "medium" card icons from the Clash Royale API
DEFAULT_CARD_SIZE = (285, 420)

_elixir_drop = Image.open(paths.DROPLET)
_elixir_drop.load()


def get_average_elixir(cards: list[dict]) -> float:
    total = 0
    for card in cards:
        total += card["cost"]
    return total / 8


def fit_text(text: str, max_width: int) -> tuple[ImageFont.FreeTypeFont, str]:
    """Wraps text by words and shrinks the font until every line fits."""
    for size in range(40, 15, -4):
        font = ImageFont.truetype(paths.FONT, size=size)
        lines: list[str] = []
        for word in text.split():
            candidate = f"{lines[-1]} {word}" if lines else word
            if lines and font.getlength(candidate) <= max_width:
                lines[-1] = candidate
            else:
                lines.append(word)

        if all(font.getlength(line) <= max_width for line in lines):
            return font, "\n".join(lines)

    return font, "\n".join(lines)


def make_placeholder(name: str, size: tuple[int, int]) -> Image.Image:
    """Card-sized tile with the card's name, used when its image couldn't be loaded."""
    width, height = size
    # Transparent white, same as the card icons' background
    placeholder = Image.new("RGBA", size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(placeholder)
    draw.rounded_rectangle(
        (8, 8, width - 8, height - 8),
        radius=24,
        fill=(40, 40, 48, 255),
        outline=(90, 90, 100, 255),
        width=4,
    )

    font, text = fit_text(name or "?", max_width=width - 48)
    draw.multiline_text(
        (width // 2, height // 2),
        text,
        font=font,
        fill="white",
        anchor="mm",
        align="center",
    )

    return placeholder


def _build_deck_image(cards: list[dict]) -> Image.Image:
    card_size = next(
        (card["img"].size for card in cards if card["img"] is not None),
        DEFAULT_CARD_SIZE,
    )
    images = [
        card["img"]
        if card["img"] is not None
        else make_placeholder(card["name"], card_size)
        for card in cards
    ]
    elixir_drop = _elixir_drop
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


def _build_deck_png(cards: list[dict]) -> io.BytesIO:
    buffer = io.BytesIO()
    _build_deck_image(cards).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def build_deck_image(cards: list[dict]) -> io.BytesIO:
    """Builds the deck image as PNG in a thread so it doesn't block the event loop."""
    return await asyncio.to_thread(_build_deck_png, cards)
