import datetime
import re
import unicodedata

import aiofiles
from colorama import Fore, Style
from playwright.async_api import BrowserContext, Playwright

from config import LOGS, PROFILE


async def init_context(playwright: Playwright) -> BrowserContext:
    chromium = playwright.chromium

    context = await chromium.launch_persistent_context(
        PROFILE,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )

    return context


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().strip()


def strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


async def log(msg, color, type):
    time = datetime.datetime.now()
    formatted = time.strftime("%Y-%m-%d %H:%M:%S")

    out = f"{Style.DIM}{formatted}{Style.RESET_ALL} {color}{type}{Style.RESET_ALL}\t{msg}{Style.RESET_ALL}"
    print(out)
    async with aiofiles.open(LOGS, "a") as f:
        await f.write(strip_ansi(out) + "\n")


async def print_info(msg):
    await log(msg, Fore.GREEN, "INFO")


async def print_error(msg):
    await log(msg, Fore.RED, "ERROR")
