import asyncio
import base64
import json
from anthropic import APIStatusError, AsyncAnthropic
from anthropic.types import TextBlock
from config import PROMPT
import time

CLAUDE_DEFAULT_VERSION = "claude-sonnet-4-6"

async def extract_player_info(client: AsyncAnthropic, image_bytes: bytes, retries: int = 3) -> dict | None:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    for attempt in range(retries):
        try:
            start = time.time()
            response = await client.messages.create(
                model=CLAUDE_DEFAULT_VERSION,
                max_tokens=64,
                system=PROMPT,
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
            total = time.time() - start
            text_block = next((block for block in response.content if isinstance(block, TextBlock)), None)
            print(f"Time taken for claude to respond: {total:.2f}s")

            if text_block:
                return json.loads(text_block.text.strip())
        except APIStatusError as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)
            else:
                raise e
    return None
