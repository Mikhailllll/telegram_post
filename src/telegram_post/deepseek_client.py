"""Клиент DeepSeek для адаптации постов."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_random_exponential


logger = logging.getLogger(__name__)


class DeepSeekClientError(RuntimeError):
    """Базовая ошибка клиента DeepSeek."""


class DeepSeekClient:
    """Асинхронный клиент DeepSeek API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com/v1",
        timeout: float = 30.0,
        max_attempts: int = 3,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)
        self._retry_settings = {
            "stop": stop_after_attempt(max_attempts),
            "wait": wait_random_exponential(multiplier=1, max=10),
            "retry": retry_if_exception_type((httpx.HTTPError, DeepSeekClientError)),
        }

    async def __aenter__(self) -> "DeepSeekClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - простая обёртка
        await self.aclose()

    async def aclose(self) -> None:
        """Закрыть внутренний ``httpx.AsyncClient``."""

        await self._client.aclose()

    async def adapt_post(self, original_text: str) -> str:
        """Преобразовать пост с помощью DeepSeek.

        Args:
            original_text: Исходный текст поста.

        Raises:
            DeepSeekClientError: При ошибках запроса или формате ответа.

        Returns:
            Сформатированный текст для публикации.
        """

        url = f"{self.base_url}/posts/adapt"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"text": original_text}

        try:
            async for attempt in AsyncRetrying(**self._retry_settings):
                with attempt:
                    response = await self._client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
        except RetryError as exc:  # pragma: no cover - сложный сетевой сценарий
            logger.exception("Ошибка при обращении к DeepSeek: %s", exc)
            raise DeepSeekClientError("Не удалось адаптировать пост через DeepSeek") from exc

        adapted_text = self._extract_text(data)
        logger.debug("Получен адаптированный пост длиной %d символов", len(adapted_text))
        return adapted_text

    def _extract_text(self, payload: Any) -> str:
        """Извлечь текст из ответа DeepSeek."""

        if isinstance(payload, dict):
            for key in ("result", "text", "content", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        raise DeepSeekClientError("Не удалось распознать текст в ответе DeepSeek")
