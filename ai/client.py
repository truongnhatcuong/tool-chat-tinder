"""HTTPX-based asynchronous LLM client compatible with OpenAI Chat Completions API."""
import asyncio
from typing import Any
import httpx
from config.settings import get_settings
from utils.logger import logger
from utils.rate_limiter import AsyncRateLimiter


class LLMClientError(Exception):
    """Base exception for LLM client failures."""
    pass


class LLMClient:
    """Async client communicating with any OpenAI-compatible API endpoint."""

    def __init__(self):
        self.settings = get_settings()
        self.rate_limiter = AsyncRateLimiter(
            max_calls_per_minute=self.settings.automation.max_ai_replies_per_minute
        )

    def _get_base_url(self) -> str:
        url = self.settings.ai_base_url.rstrip("/")
        if not url.endswith("/v1") and not url.endswith("/chat/completions"):
            # If standard base URL like https://api.openai.com
            url = f"{url}/v1"
        return url

    def _get_completions_url(self) -> str:
        base = self._get_base_url()
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 30.0
    ) -> str:
        """
        Send a chat completion request with exponential backoff retry.
        Retries up to max_retries with delays [1s, 2s, 4s].
        """
        settings = get_settings()
        if not settings.ai_api_key or settings.ai_api_key == "dummy_key_for_testing":
            logger.warning("AI_API_KEY is not configured or is placeholder.")

        temp = temperature if temperature is not None else settings.ai.temperature
        tokens = max_tokens if max_tokens is not None else settings.ai.max_tokens
        url = self._get_completions_url()

        headers = {
            "Authorization": f"Bearer {settings.ai_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": settings.ai_model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens
        }

        delays = [1.0, 2.0, 4.0]
        last_error: Exception | None = None

        for attempt, delay in enumerate(delays, start=1):
            try:
                # Respect rate limiter
                await self.rate_limiter.acquire()

                async with httpx.AsyncClient(timeout=timeout) as client:
                    logger.debug(f"Sending LLM request to {url} (attempt {attempt}/{len(delays)})")
                    response = await client.post(url, headers=headers, json=payload)
                    
                    if response.status_code == 200:
                        data = response.json()
                        choices = data.get("choices", [])
                        if choices and "message" in choices[0]:
                            content = choices[0]["message"].get("content", "").strip()
                            return content
                        raise LLMClientError(f"Unexpected response structure: {data}")
                    
                    error_msg = f"API returned status {response.status_code}: {response.text}"
                    logger.warning(f"LLM request error on attempt {attempt}: {error_msg}")
                    last_error = LLMClientError(error_msg)

            except httpx.RequestError as e:
                logger.warning(f"HTTP network error on attempt {attempt}: {e}")
                last_error = e
            except Exception as e:
                logger.warning(f"Unexpected error in LLM call attempt {attempt}: {e}")
                last_error = e

            if attempt < len(delays):
                logger.info(f"Retrying LLM call in {delay}s...")
                await asyncio.sleep(delay)

        raise LLMClientError(f"LLM request failed after {len(delays)} attempts: {last_error}")

    async def test_connection(self) -> tuple[bool, str]:
        """Verify API key and connectivity with a lightweight prompt."""
        test_messages = [{"role": "user", "content": "hi"}]
        try:
            reply = await self.chat(test_messages, max_tokens=10, timeout=10.0)
            return True, f"Connected successfully. Response: {reply[:30]}"
        except Exception as e:
            return False, str(e)
