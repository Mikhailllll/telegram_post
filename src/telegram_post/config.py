"""Конфигурация приложения и валидация переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, MutableMapping


class SettingsError(RuntimeError):
    """Исключение, описывающее проблемы с конфигурацией."""


@dataclass(slots=True)
class Settings:
    """Контейнер настроек сервиса автоматизации Telegram."""

    deepseek_api_key: str
    telegram_bot_username: str
    telegram_bot_token: str
    telegram_target_channel: str
    telegram_source_user_id: int

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | MutableMapping[str, str] | None = None
    ) -> "Settings":
        """Создать настройки из переменных окружения.

        Args:
            env: Объект с методом ``get`` для чтения переменных.

        Raises:
            SettingsError: Если какая-либо переменная отсутствует или некорректна.

        Returns:
            Экземпляр настроек.
        """

        env_mapping = env or os.environ
        required = {
            "deepseek_api_key": "DEEPSEEK_APPI",
            "telegram_bot_username": "USERNAMETELERGRAMBOT",
            "telegram_bot_token": "TELEGRAMKEY",
            "telegram_target_channel": "TELEGRAMKANAL",
            "telegram_source_user_id": "TGUSERID",
        }

        missing = [var for var in required.values() if not env_mapping.get(var)]
        if missing:
            raise SettingsError(
                "Отсутствуют обязательные переменные окружения: "
                + ", ".join(sorted(missing))
            )

        try:
            source_user_id = int(env_mapping[required["telegram_source_user_id"]])
        except ValueError as exc:  # pragma: no cover - защита от некорректного ввода
            raise SettingsError("TGUSERID должен быть целым числом") from exc

        return cls(
            deepseek_api_key=env_mapping[required["deepseek_api_key"]],
            telegram_bot_username=env_mapping[required["telegram_bot_username"]],
            telegram_bot_token=env_mapping[required["telegram_bot_token"]],
            telegram_target_channel=env_mapping[required["telegram_target_channel"]],
            telegram_source_user_id=source_user_id,
        )
