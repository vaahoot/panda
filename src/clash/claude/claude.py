import asyncio
import base64
import json
import time

import anthropic

from . import const


async def extract_player_info(
    client: anthropic.AsyncAnthropic, image_bytes: bytes, retries: int = 3
) -> dict | None:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    for attempt in range(retries):
        try:
            start = time.time()
            response = await client.messages.create(
                model=const.CLAUDE_DEFAULT_VERSION,
                max_tokens=64,
                system=const.CLAUDE_PROMPT,
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
                (
                    block
                    for block in response.content
                    if isinstance(block, anthropic.types.TextBlock)
                ),
                None,
            )
            total = time.time() - start
            print(f"Time taken for claude to respond: {total:.2f}s")

            if text_block:
                return json.loads(text_block.text.strip())
        except anthropic.APIStatusError:
            if attempt < retries - 1:
                await asyncio.sleep(1)
            else:
                raise
    return None
