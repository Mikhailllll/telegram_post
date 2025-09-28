"""Тесты для основного цикла публикации."""

from __future__ import annotations

from typing import List, Tuple

from unittest.mock import AsyncMock

import pytest

from telegram_post.config import Settings
from telegram_post.main import poll_loop
from telegram_post.telegram_client import TelegramMessage


class DummyTelegramClient:
    """Заглушка клиента Telegram для тестов."""

    def __init__(self, responses: List[Tuple[list[TelegramMessage], int]]):
        self.fetch_new_messages = AsyncMock(side_effect=responses)

    async def __aenter__(self) -> "DummyTelegramClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - заглушка
        return None


class DummyDeepSeekClient:
    """Заглушка клиента DeepSeek для тестов."""

    async def __aenter__(self) -> "DummyDeepSeekClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - заглушка
        return None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_poll_loop_limits_messages_with_missing_last_update(
    monkeypatch, anyio_backend
):
    """Проверить, что цикл ограничивает количество сообщений без last_update_id."""

    settings = Settings(
        deepseek_api_key="key",
        telegram_bot_username="bot",
        telegram_bot_token="token",
        telegram_target_channel="channel",
        telegram_source_user_id=123,
    )

    first_batch = [
        TelegramMessage(update_id=1, message_id=1, text="m1"),
        TelegramMessage(update_id=2, message_id=2, text="m2"),
        TelegramMessage(update_id=3, message_id=3, text="m3"),
    ]
    second_batch = [
        TelegramMessage(update_id=4, message_id=4, text="n1"),
        TelegramMessage(update_id=5, message_id=5, text="n2"),
        TelegramMessage(update_id=6, message_id=6, text="n3"),
    ]

    dummy_telegram_client = DummyTelegramClient(
        responses=[(first_batch, 3), (second_batch, 6)]
    )
    dummy_deepseek_client = DummyDeepSeekClient()

    monkeypatch.setattr(
        "telegram_post.main.TelegramClient", lambda *_, **__: dummy_telegram_client
    )
    monkeypatch.setattr(
        "telegram_post.main.DeepSeekClient", lambda *_, **__: dummy_deepseek_client
    )

    processed_batches: list[list[int]] = []

    async def fake_process(messages, *_args):
        processed_batches.append([msg.message_id for msg in messages])
        if len(processed_batches) == 2:
            raise RuntimeError("stop loop")
        return len(messages)

    process_mock = AsyncMock(side_effect=fake_process)
    monkeypatch.setattr("telegram_post.main._process_messages", process_mock)

    sleep_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("telegram_post.main.asyncio.sleep", sleep_mock)

    with pytest.raises(RuntimeError, match="stop loop"):
        await poll_loop(settings, interval=0)

    assert processed_batches[0] == [2, 3]
    assert processed_batches[1] == [4, 5, 6]
    assert process_mock.await_count == 2

