"""Тесты для клиента Telegram."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from telegram_post.telegram_client import TelegramClient, TelegramClientError


def test_fetch_new_messages_deletes_webhook_and_retries(monkeypatch, caplog):
    """Клиент должен удалить webhook и повторить запрос после 409."""

    async def run_test() -> None:
        client = TelegramClient(
            "test-token",
            source_user_id=123,
            target_channel="@target",
            max_attempts=1,
        )

        url = f"{client.base_url}/bot{client.token}/getUpdates"
        request = httpx.Request("GET", url)
        conflict_response = httpx.Response(status_code=409, request=request)
        conflict_error = httpx.HTTPStatusError(
            "Conflict", request=request, response=conflict_response
        )

        success_response = httpx.Response(
            status_code=200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 100,
                        "channel_post": {
                            "message_id": 200,
                            "text": "  Привет  ",
                            "sender_chat": {"id": 123},
                        },
                    }
                ],
            },
            request=request,
        )

        get_calls = {"count": 0}

        async def fake_get(*args, **kwargs):
            get_calls["count"] += 1
            if get_calls["count"] == 1:
                raise conflict_error
            return success_response

        delete_called = {"count": 0}

        async def fake_delete_webhook() -> None:
            delete_called["count"] += 1

        monkeypatch.setattr(client._client, "get", fake_get)
        monkeypatch.setattr(client, "_delete_webhook", fake_delete_webhook)

        with caplog.at_level("WARNING"):
            messages, new_last_update = await client.fetch_new_messages(
                last_update_id=42
            )

        await client.aclose()

        assert len(messages) == 1
        assert messages[0].text == "Привет"
        assert new_last_update == 100
        assert get_calls["count"] == 2
        assert delete_called["count"] == 1
        assert any("409" in record.getMessage() for record in caplog.records)

    asyncio.run(run_test())


def test_fetch_new_messages_raises_on_repeated_conflict(monkeypatch):
    """Повторный 409 после удаления webhook приводит к исключению."""

    async def run_test() -> None:
        client = TelegramClient(
            "test-token",
            source_user_id=123,
            target_channel="@target",
            max_attempts=1,
        )

        url = f"{client.base_url}/bot{client.token}/getUpdates"
        request = httpx.Request("GET", url)
        conflict_response = httpx.Response(status_code=409, request=request)
        conflict_error = httpx.HTTPStatusError(
            "Conflict", request=request, response=conflict_response
        )

        async def fake_get(*args, **kwargs):
            raise conflict_error

        delete_called = {"count": 0}

        async def fake_delete_webhook() -> None:
            delete_called["count"] += 1

        monkeypatch.setattr(client._client, "get", fake_get)
        monkeypatch.setattr(client, "_delete_webhook", fake_delete_webhook)

        with pytest.raises(TelegramClientError, match="конфликт вебхука"):
            await client.fetch_new_messages(last_update_id=1)

        await client.aclose()

        assert delete_called["count"] == 1

    asyncio.run(run_test())
