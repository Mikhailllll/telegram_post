"""Тесты для клиента Telegram."""

from __future__ import annotations

import asyncio

import json

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


def test_fetch_new_messages_passes_allowed_updates(monkeypatch):
    """Клиент должен запрашивать только разрешённые обновления."""

    async def run_test() -> None:
        client = TelegramClient(
            "test-token",
            source_user_id=123,
            target_channel="@target",
            max_attempts=1,
        )

        url = f"{client.base_url}/bot{client.token}/getUpdates"
        request = httpx.Request("GET", url)

        success_response = httpx.Response(
            status_code=200,
            json={"ok": True, "result": []},
            request=request,
        )

        async def fake_get(*args, **kwargs):
            params = kwargs.get("params") or {}
            assert set(params.keys()) == {"timeout", "allowed_updates"}
            assert params["timeout"] == 0

            allowed_updates_raw = params["allowed_updates"]
            assert isinstance(allowed_updates_raw, str)
            allowed_updates = json.loads(allowed_updates_raw)
            assert set(allowed_updates) == {
                "message",
                "channel_post",
                "edited_channel_post",
            }
            return success_response

        monkeypatch.setattr(client._client, "get", fake_get)

        await client.fetch_new_messages()
        await client.aclose()

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


def test_fetch_new_messages_handles_channel_post_without_sender_chat(monkeypatch):
    """Сообщение без ``sender_chat`` не должно отбрасываться, если есть ``chat.id``."""

    async def run_test() -> None:
        client = TelegramClient(
            "test-token",
            source_user_id=123,
            target_channel="@target",
            max_attempts=1,
        )

        url = f"{client.base_url}/bot{client.token}/getUpdates"
        request = httpx.Request("GET", url)

        success_response = httpx.Response(
            status_code=200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 77,
                        "channel_post": {
                            "message_id": 555,
                            "text": "Привет",
                            "chat": {"id": "123"},
                        },
                    }
                ],
            },
            request=request,
        )

        async def fake_get(*args, **kwargs):
            return success_response

        monkeypatch.setattr(client._client, "get", fake_get)

        messages, new_last_update = await client.fetch_new_messages()

        await client.aclose()

        assert len(messages) == 1
        assert messages[0].text == "Привет"
        assert messages[0].message_id == 555
        assert new_last_update == 77

    asyncio.run(run_test())


def test_fetch_new_messages_accepts_normalized_sender(monkeypatch):
    """Сообщение с идентификатором ``-100`` должно засчитываться как допустимое."""

    async def run_test() -> None:
        client = TelegramClient(
            "test-token",
            source_user_id=123,
            target_channel="@target",
            max_attempts=1,
        )

        url = f"{client.base_url}/bot{client.token}/getUpdates"
        request = httpx.Request("GET", url)

        success_response = httpx.Response(
            status_code=200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 10,
                        "channel_post": {
                            "message_id": 11,
                            "text": "Сообщение",
                            "sender_chat": {"id": "-100123"},
                        },
                    }
                ],
            },
            request=request,
        )

        async def fake_get(*args, **kwargs):
            return success_response

        monkeypatch.setattr(client._client, "get", fake_get)

        messages, _ = await client.fetch_new_messages()

        await client.aclose()

        assert len(messages) == 1
        assert messages[0].text == "Сообщение"

    asyncio.run(run_test())
