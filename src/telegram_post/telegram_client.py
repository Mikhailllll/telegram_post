"""Минимальный клиент Telegram Bot API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)


logger = logging.getLogger(__name__)


class TelegramClientError(RuntimeError):
    """Ошибка общения с Bot API."""


@dataclass(slots=True)
class TelegramMessage:
    """Сущность сообщения Telegram."""

    update_id: int
    message_id: int
    text: str


class TelegramClient:
    """Асинхронный клиент для чтения и публикации сообщений."""

    def __init__(
        self,
        token: str,
        *,
        source_user_id: int,
        target_channel: str,
        base_url: str = "https://api.telegram.org",
        timeout: float = 20.0,
        max_attempts: int = 3,
    ) -> None:
        self.token = token
        self.source_user_id = source_user_id
        self.target_channel = target_channel
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)
        self._retry_settings = {
            "stop": stop_after_attempt(max_attempts),
            "wait": wait_random_exponential(multiplier=1, max=8),
            "retry": retry_if_exception_type(httpx.HTTPError),
        }

    async def __aenter__(self) -> "TelegramClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - обёртка
        await self.aclose()

    async def aclose(self) -> None:
        """Закрыть ``httpx.AsyncClient``."""

        await self._client.aclose()

    async def fetch_new_messages(
        self, last_update_id: Optional[int] = None
    ) -> Tuple[List[TelegramMessage], Optional[int]]:
        """Получить новые сообщения из канала-источника.

        Args:
            last_update_id: Идентификатор последнего обработанного обновления.

        Returns:
            Список сообщений и новый ``last_update_id``.
        """

        params: dict[str, Any] = {
            "timeout": 0,
            "allowed_updates": [
                "message",
                "channel_post",
                "edited_channel_post",
            ],
        }
        if last_update_id is not None:
            params["offset"] = last_update_id + 1

        url = f"{self.base_url}/bot{self.token}/getUpdates"

        webhook_conflict_handled = False

        while True:
            try:
                async for attempt in AsyncRetrying(**self._retry_settings):
                    with attempt:
                        response = await self._client.get(url, params=params)
                        response.raise_for_status()
                        data = response.json()
                break
            except RetryError as exc:  # pragma: no cover - сетевой сценарий
                last_attempt_exception: Optional[BaseException] = None
                if getattr(exc, "last_attempt", None) is not None:
                    try:
                        last_attempt_exception = exc.last_attempt.exception()
                    except Exception:  # pragma: no cover - защитный сценарий
                        last_attempt_exception = None

                if (
                    isinstance(last_attempt_exception, httpx.HTTPStatusError)
                    and last_attempt_exception.response is not None
                    and last_attempt_exception.response.status_code == 409
                ):
                    if not webhook_conflict_handled:
                        logger.warning(
                            "Получен ответ 409 при получении обновлений Telegram: %s",
                            last_attempt_exception,
                        )
                        await self._delete_webhook()
                        webhook_conflict_handled = True
                        continue

                    raise TelegramClientError(
                        "Не удалось получить обновления Telegram: конфликт вебхука не устранён"
                    ) from exc

                logger.exception("Ошибка получения обновлений: %s", exc)
                raise TelegramClientError(
                    "Не удалось получить обновления Telegram"
                ) from exc

        if not data.get("ok"):
            raise TelegramClientError(f"Telegram API вернул ошибку: {data}")

        updates: Iterable[dict[str, Any]] = data.get("result", [])
        messages: List[TelegramMessage] = []
        new_last_update = last_update_id

        for update in updates:
            update_id = int(update.get("update_id", 0))
            new_last_update = max(new_last_update or update_id, update_id)

            message_block = update.get("channel_post") or update.get("message") or {}
            sender_chat = message_block.get("sender_chat") or {}
            from_user = message_block.get("from") or {}
            sender_id_raw_candidates = (
                sender_chat.get("id"),
                from_user.get("id"),
                (message_block.get("chat") or {}).get("id"),
            )
            sender_id: Optional[int] = None
            for sender_id_raw in sender_id_raw_candidates:
                if sender_id_raw is None:
                    continue
                try:
                    sender_id = int(sender_id_raw)
                except (TypeError, ValueError):
                    sender_id = None
                    continue
                else:
                    break

            if sender_id is None or sender_id != self.source_user_id:
                continue

            text = message_block.get("text") or message_block.get("caption")
            if not text or not text.strip():
                continue

            message_id = int(message_block.get("message_id", 0))
            messages.append(
                TelegramMessage(
                    update_id=update_id, message_id=message_id, text=text.strip()
                )
            )

        logger.debug("Получено %d релевантных сообщений", len(messages))
        return messages, new_last_update

    async def publish_post(
        self, text: str, *, disable_preview: bool = False
    ) -> dict[str, Any]:
        """Отправить пост в целевой канал."""

        url = f"{self.base_url}/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.target_channel,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }

        try:
            async for attempt in AsyncRetrying(**self._retry_settings):
                with attempt:
                    response = await self._client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
        except RetryError as exc:  # pragma: no cover
            logger.exception("Ошибка отправки сообщения: %s", exc)
            raise TelegramClientError(
                "Не удалось отправить сообщение Telegram"
            ) from exc

        if not data.get("ok"):
            raise TelegramClientError(
                f"Telegram API вернул ошибку при отправке: {data}"
            )

        logger.info("Сообщение опубликовано в %s", self.target_channel)
        return data.get("result", {})

    async def _delete_webhook(self) -> None:
        """Удалить активный webhook Telegram без сброса очереди."""

        url = f"{self.base_url}/bot{self.token}/deleteWebhook"
        payload = {"drop_pending_updates": False}

        try:
            async for attempt in AsyncRetrying(**self._retry_settings):
                with attempt:
                    response = await self._client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
        except RetryError as exc:  # pragma: no cover - сетевой сценарий
            logger.exception("Ошибка удаления webhook: %s", exc)
            raise TelegramClientError("Не удалось удалить webhook Telegram") from exc

        if not data.get("ok"):
            raise TelegramClientError(
                f"Telegram API вернул ошибку при удалении webhook: {data}"
            )
