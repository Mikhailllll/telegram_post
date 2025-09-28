"""Тесты для загрузки настроек из окружения."""

from __future__ import annotations

import pytest

from telegram_post.config import Settings, SettingsError


@pytest.fixture()
def base_env() -> dict[str, str]:
    """Базовый набор переменных окружения для валидных настроек."""

    return {
        "DEEPSEEK_APPI": "deepseek",
        "USERNAMETELERGRAMBOT": "@bot",
        "TELEGRAMKEY": "token",
        "TG_ISTO4NIK_ID": "123",
        "TGUSERID": "123",
        "TELEGRAMKANAL": "@legacy-channel",
    }


def test_settings_prefers_new_channel_variable(base_env: dict[str, str]) -> None:
    """Новая переменная канала имеет приоритет над устаревшей."""

    base_env.pop("TELEGRAMKANAL", None)
    base_env["TELEGRAMKANAL_ID_S_MINYSOM_V_NA4ALE"] = "@new-channel"

    settings = Settings.from_env(base_env)

    assert settings.telegram_target_channel == "@new-channel"


def test_settings_falls_back_to_legacy_variable(base_env: dict[str, str]) -> None:
    """При отсутствии новой переменной используется старое имя."""

    base_env.pop("TELEGRAMKANAL_ID_S_MINYSOM_V_NA4ALE", None)

    settings = Settings.from_env(base_env)

    assert settings.telegram_target_channel == "@legacy-channel"


def test_settings_prefers_new_source_user_variable(base_env: dict[str, str]) -> None:
    """Для ID источника приоритет у новой переменной окружения."""

    base_env["TG_ISTO4NIK_ID"] = "456"
    base_env["TGUSERID"] = "789"

    settings = Settings.from_env(base_env)

    assert settings.telegram_source_user_id == 456


def test_settings_falls_back_to_legacy_source_user_variable(
    base_env: dict[str, str]
) -> None:
    """Если новой переменной нет, используется устаревшее имя."""

    base_env.pop("TG_ISTO4NIK_ID", None)
    base_env["TGUSERID"] = "654"

    settings = Settings.from_env(base_env)

    assert settings.telegram_source_user_id == 654


def test_settings_error_when_both_channel_variables_missing(
    base_env: dict[str, str]
) -> None:
    """Сообщение об ошибке поясняет необходимость указать одну из переменных."""

    base_env.pop("TELEGRAMKANAL", None)
    base_env.pop("TELEGRAMKANAL_ID_S_MINYSOM_V_NA4ALE", None)

    with pytest.raises(SettingsError) as exc_info:
        Settings.from_env(base_env)

    message = str(exc_info.value)
    assert "TELEGRAMKANAL_ID_S_MINYSOM_V_NA4ALE" in message
    assert "TELEGRAMKANAL" in message
    assert "укажите хотя бы одну" in message
