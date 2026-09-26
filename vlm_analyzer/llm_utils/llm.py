import aiohttp
import asyncio
import base64
from typing import Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

class OpenRouterError(Exception):
    pass


def encode_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


async def _make_request(
    session: aiohttp.ClientSession,
    api_key: str,
    model: str,
    messages: List[dict],
    timeout: int = 30
):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Optional but recommended:
        "HTTP-Referer": "http://localhost",
        "X-Title": "vlm-client",
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 1024,
    }

    try:
        async with session.post(
            OPENROUTER_URL,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:

            if resp.status != 200:
                text = await resp.text()
                raise OpenRouterError(f"HTTP {resp.status}: {text}")

            data = await resp.json()
            return data["choices"][0]["message"]["content"]

    except asyncio.TimeoutError:
        raise OpenRouterError("Request timeout")
    except Exception as e:
       print(e)




@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(OpenRouterError),
)
async def _call_with_retry(
    session: aiohttp.ClientSession,
    api_key: str,
    model: str,
    messages: List[dict],
):
    return await _make_request(session, api_key, model, messages)


async def query_vlm(
    api_key: str,
    prompt: str,
    image_bytes: Optional[bytes] = None,
    extra_text: Optional[str] = None,
    model_name: str = "google/gemma-4-26b-a4b-it:free" # "openai/gpt-4.1-mini"
) -> str:
    """
    Main function:
    - prompt: main instruction
    - image_bytes: optional image
    - extra_text: optional additional context
    """

    messages = [{
        "role": "system",
        "content": [{"type": "text", "text": prompt}]
    }]

    content = []
    if extra_text:
        content.append({"type": "text", "text": extra_text})

    if image_bytes:
        encoded = encode_image(image_bytes)
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{encoded}"
            }
        })

    messages.append(
        {
            "role": "user",
            "content": content,
        }
    )

    async with aiohttp.ClientSession() as session:
        last_error = None

        try:
            result = await _call_with_retry(
                session=session,
                api_key=api_key,
                model=model_name,
                messages=messages,
            )
            return result

        except Exception as e:
            last_error = e
            raise OpenRouterError(f"llm: {last_error}")
