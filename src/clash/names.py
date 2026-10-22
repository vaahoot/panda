import unicodedata

# Accents and overlays (strikethrough, slashes, underlines) people decorate names with, plus
# Japanese voicing marks: ゛ and ゜ are tiny in the game font and easily misread (ぼ vs ぽ), so
# ば, ぱ and は all match. Other combining marks (Thai vowels, Indic signs) are part of the letter
DECORATION_RANGES = (
    (0x0300, 0x036F),  # Combining Diacritical Marks
    (0x1AB0, 0x1AFF),  # Combining Diacritical Marks Extended
    (0x1DC0, 0x1DFF),  # Combining Diacritical Marks Supplement
    (0x20D0, 0x20FF),  # Combining Diacritical Marks for Symbols
    (0x3099, 0x309A),  # Combining Katakana-Hiragana Voiced / Semi-Voiced Sound Marks
    (0xFE20, 0xFE2F),  # Combining Half Marks
)


# Letters that look like an accented Latin letter but don't decompose into one
LOOKALIKES = str.maketrans({
    "đ": "d", "ð": "d", "ø": "o", "ł": "l", "ħ": "h", "ŧ": "t", "ı": "i",
    "ß": "ss", "æ": "ae", "œ": "oe", "þ": "th",
})


def is_decoration(c: str) -> bool:
    return any(lo <= ord(c) <= hi for lo, hi in DECORATION_RANGES)


def normalise(text: str) -> str:
    """Search key for player and clan names, use it on both sides of every comparison.

    Lowercase, accents and decorative marks removed (so "T̶B̶ J̸O̸H̸A̸N̸" and "Édy" become
    "tbjohan" and "edy"), and only letters and digits kept, so spaces, symbols and emoji
    don't matter. Works the same for any script.
    """
    lowered = unicodedata.normalize("NFKC", text).lower()
    key = "".join(
        c for c in unicodedata.normalize("NFKD", lowered).translate(LOOKALIKES)
        if not is_decoration(c) and (c.isalnum() or unicodedata.category(c) in ("Mn", "Mc"))
    )
    # Back to composed form: rejoins Korean syllables split by NFKD
    key = unicodedata.normalize("NFC", key)
    if key:
        return key
    # Names made only of symbols/emoji would otherwise match everything
    return lowered.strip()
