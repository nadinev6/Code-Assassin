"""
Ollama streaming chat client.
"""
import json
import httpx
from typing import Optional, AsyncIterator, Any


class OllamaClient:
    """Streaming client for Ollama /api/chat endpoint."""

    def __init__(self, url: str = "http://127.0.0.1:11434"):
        self.url = url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
        return self._client

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        num_ctx: int = 2048,
        num_predict: int = 512,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        """Stream tokens from Ollama. Yields text chunks."""
        client = await self._get_client()
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "temperature": temperature,
            },
        }
        
        async with client.stream("POST", f"{self.url}/api/chat", json=payload) as response:
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if "message" in data and "content" in data["message"]:
                        yield data["message"]["content"]
                    if data.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def check_available(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            client = await self._get_client()
            r = await client.get(f"{self.url}/api/tags")
            return r.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List available models."""
        try:
            client = await self._get_client()
            r = await client.get(f"{self.url}/api/tags")
            if r.status_code == 200:
                data = r.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []