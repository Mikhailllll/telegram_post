"""Тесты для клиента Telegram."""

from __future__ import annotations

import asyncio

import httpx

from telegram_post.telegram_client import TelegramClient


def test_fetch_new_messages_handles_conflict(monkeypatch, caplog):
    """Метод должен игнорировать 409 Conflict и возвращать пустой результат."""

    async def run_test() -> None:
        client = TelegramClient(
            "test-token",
            source_user_id=123,
            target_channel="@target",
            max_attempts=1,
        )

        request = httpx.Request(
            "GET", f"{client.base_url}/bot{client.token}/getUpdates"
        )
        response = httpx.Response(status_code=409, request=request)
        error = httpx.HTTPStatusError("Conflict", request=request, response=response)

        async def fake_get(*args, **kwargs):
            raise error

        monkeypatch.setattr(client._client, "get", fake_get)

        with caplog.at_level("WARNING"):
            messages, new_last_update = await client.fetch_new_messages(
                last_update_id=42
            )

        await client.aclose()

        assert messages == []
        assert new_last_update == 42
        assert any("409" in record.getMessage() for record in caplog.records)

    asyncio.run(run_test())
