"""Тесты для основного цикла публикации."""

from __future__ import annotations

import json
from typing import List, Optional, Tuple

from unittest.mock import AsyncMock

import pytest

from telegram_post.config import Settings
from telegram_post.main import poll_loop, poll_once, run_poll_once
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


class StatefulDummyTelegramClient:
    """Телеграм-клиент, запоминающий входящий last_update_id."""

    def __init__(self) -> None:
        self.calls: list[Optional[int]] = []

    async def __aenter__(self) -> "StatefulDummyTelegramClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - заглушка
        return None

    async def fetch_new_messages(
        self, last_update_id: Optional[int]
    ) -> Tuple[list[TelegramMessage], int]:
        self.calls.append(last_update_id)
        if last_update_id is None:
            message = TelegramMessage(update_id=1, message_id=100, text="first")
            return [message], 1
        if last_update_id == 1:
            return [], 1
        raise AssertionError("Неожиданный last_update_id")


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


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_poll_once_uses_all_messages_with_existing_last_update(
    monkeypatch, anyio_backend
):
    """При наличии last_update_id должны обрабатываться все новые сообщения."""

    settings = Settings(
        deepseek_api_key="key",
        telegram_bot_username="bot",
        telegram_bot_token="token",
        telegram_target_channel="channel",
        telegram_source_user_id=123,
    )

    new_messages = [
        TelegramMessage(update_id=11, message_id=101, text="m1"),
        TelegramMessage(update_id=12, message_id=102, text="m2"),
        TelegramMessage(update_id=13, message_id=103, text="m3"),
        TelegramMessage(update_id=14, message_id=104, text="m4"),
    ]

    dummy_telegram_client = DummyTelegramClient(responses=[(new_messages, 14)])
    dummy_deepseek_client = DummyDeepSeekClient()

    monkeypatch.setattr(
        "telegram_post.main.TelegramClient", lambda *_, **__: dummy_telegram_client
    )
    monkeypatch.setattr(
        "telegram_post.main.DeepSeekClient", lambda *_, **__: dummy_deepseek_client
    )

    process_mock = AsyncMock(return_value=len(new_messages))
    monkeypatch.setattr("telegram_post.main._process_messages", process_mock)

    result = await poll_once(settings, last_update_id=10)

    assert result == 14
    assert process_mock.await_count == 1
    processed_messages = process_mock.await_args_list[0].args[0]
    assert [msg.message_id for msg in processed_messages] == [101, 102, 103, 104]


def test_run_poll_once_persists_state(monkeypatch, tmp_path):
    """Проверить сохранение и повторное использование last_update_id."""

    state_file = tmp_path / "state.json"
    settings = Settings(
        deepseek_api_key="key",
        telegram_bot_username="bot",
        telegram_bot_token="token",
        telegram_target_channel="channel",
        telegram_source_user_id=123,
    )

    monkeypatch.setattr(
        "telegram_post.main.Settings.from_env",
        classmethod(lambda cls: settings),
    )

    telegram_client = StatefulDummyTelegramClient()
    dummy_deepseek_client = DummyDeepSeekClient()

    monkeypatch.setattr(
        "telegram_post.main.TelegramClient",
        lambda *args, **kwargs: telegram_client,
    )
    monkeypatch.setattr(
        "telegram_post.main.DeepSeekClient",
        lambda *args, **kwargs: dummy_deepseek_client,
    )

    process_mock = AsyncMock(return_value=1)
    monkeypatch.setattr("telegram_post.main._process_messages", process_mock)

    run_poll_once(state_file=state_file)

    assert state_file.exists()
    assert json.loads(state_file.read_text(encoding="utf-8")) == {"last_update_id": 1}
    assert telegram_client.calls == [None]
    assert process_mock.await_count == 1
    first_call_messages = process_mock.await_args_list[0].args[0]
    assert [msg.message_id for msg in first_call_messages] == [100]

    process_mock.reset_mock()
    run_poll_once(state_file=state_file)

    assert telegram_client.calls == [None, 1]
    assert process_mock.await_count == 0
