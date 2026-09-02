import datetime
import re
from zoneinfo import ZoneInfo

import aiofiles
import colorama

import config.paths


def strip_ansi(text) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


async def log(msg: str, color: str, type: str) -> None:
    time = datetime.datetime.now(tz=ZoneInfo("Europe/London"))
    formatted = time.strftime("%Y-%m-%d %H:%M:%S")

    out = f"{colorama.Style.DIM}{formatted}{colorama.Style.RESET_ALL} {color}{type}{colorama.Style.RESET_ALL}\t{msg}{colorama.Style.RESET_ALL}"
    print(out)
    async with aiofiles.open(config.paths.LOGS, "a") as f:
        await f.write(strip_ansi(out) + "\n")


async def info(msg: str) -> None:
    await log(msg, colorama.Fore.GREEN, "INFO")


async def warning(msg: str) -> None:
    await log(msg, colorama.Fore.LIGHTYELLOW_EX, "WARNING")


async def error(msg: str) -> None:
    await log(msg, colorama.Fore.RED, "ERROR")
