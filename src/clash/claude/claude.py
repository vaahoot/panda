import asyncio
import base64
import json
import time

import anthropic

import log

from . import const


async def extract_player_info(
    client: anthropic.AsyncAnthropic, image_bytes: bytes, retries: int = 3
) -> dict | None:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    for attempt in range(retries):
        try:
            start = time.time()
            response = await client.beta.messages.create(
                model=const.CLAUDE_DEFAULT_VERSION,
                max_tokens=128,
                system=const.CLAUDE_PROMPT,
                thinking=const.CLAUDE_THINKING,
                betas=[const.CLAUDE_FALLBACK_BETA],
                fallbacks="default",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": ".",
                            },
                        ],
                    }
                ],
            )
            text_block = next(
                (block for block in response.content if block.type == "text"),
                None,
            )
            total = time.time() - start
            print(f"Time taken for claude to respond: {total:.2f}s")

            if response.stop_reason == "refusal":
                details = response.stop_details
                await log.warning(f"Claude declined the screenshot: {details.category if details else 'unknown reason'}")
                return None

            if text_block:
                return json.loads(text_block.text.strip())
        except anthropic.APIStatusError:
            if attempt < retries - 1:
                await asyncio.sleep(1)
            else:
                raise
    return None
