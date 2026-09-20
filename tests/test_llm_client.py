"""Unit tests for the LLM Client using mocked HTTP transport."""
import pytest
import httpx
from ai.client import LLMClient, LLMClientError


@pytest.mark.asyncio
async def test_llm_client_url_resolution():
    client = LLMClient()
    url = client._get_completions_url()
    assert url.endswith("/chat/completions")


@pytest.mark.asyncio
async def test_llm_client_mock_success(monkeypatch):
    client = LLMClient()

    # Mock httpx.AsyncClient.post
    async def mock_post(*args, **kwargs):
        json_resp = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Chào em :)) dạo này em thế nào?"
                    }
                }
            ]
        }
        return httpx.Response(status_code=200, json=json_resp)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    response = await client.chat([{"role": "user", "content": "hello"}])
    assert "Chào em" in response


@pytest.mark.asyncio
async def test_llm_client_retry_and_failure(monkeypatch):
    client = LLMClient()

    call_count = 0

    async def mock_fail_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(status_code=500, text="Internal Server Error")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_fail_post)

    # Should retry 3 times then raise LLMClientError
    with pytest.raises(LLMClientError):
        await client.chat([{"role": "user", "content": "hi"}])
    
    assert call_count == 3
