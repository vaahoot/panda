import asyncio
import base64
import json

from openai import APIStatusError, AsyncOpenAI

from config import GPT_DEFAULT_VERSION, PROMPT


async def extract_player_info(client: AsyncOpenAI, image_bytes: bytes, retries: int = 3) -> dict | None:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    for attempt in range(retries):
        try:
            response = await client.chat.completions.create(
                model=GPT_DEFAULT_VERSION,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": PROMPT,
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64}",
                                    "detail": "low",
                                },
                            },
                        ],
                    }
                ],
            )
            text = response.choices[0].message.content
            if text:
                cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                return json.loads(cleaned)
        except APIStatusError as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)
            else:
                raise e
    return None
