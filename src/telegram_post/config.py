"""Конфигурация приложения и валидация переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import fields
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

    @staticmethod
    def mask_secret(value: str) -> str:
        """Скрыть середину секретного значения."""

        if not value:
            return value
        prefix = value[:2]
        suffix = value[-2:]
        return f"{prefix}***{suffix}"

    def masked_secrets(self) -> dict[str, str]:
        """Получить маскированные значения конфигурации."""

        masked: dict[str, str] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            masked[field.name] = self.mask_secret(str(value))
        return masked

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

        env_mapping = os.environ if env is None else env
        required = {
            "deepseek_api_key": ("DEEPSEEK_APPI",),
            "telegram_bot_username": ("USERNAMETELERGRAMBOT",),
            "telegram_bot_token": ("TELEGRAMKEY",),
            "telegram_target_channel": (
                "TELEGRAMKANAL_ID_S_MINYSOM_V_NA4ALE",
                "TELEGRAMKANAL",
            ),
            "telegram_source_user_id": ("TG_ISTO4NIK_ID", "TGUSERID"),
        }

        resolved: dict[str, str] = {}
        missing: list[str] = []

        for field, names in required.items():
            for name in names:
                value = env_mapping.get(name)
                if value:
                    resolved[field] = value
                    break
            else:
                formatted = " или ".join(names)
                if len(names) > 1:
                    formatted += " (укажите хотя бы одну переменную)"
                missing.append(formatted)

        if missing:
            raise SettingsError(
                "Отсутствуют обязательные переменные окружения: "
                + ", ".join(sorted(missing))
            )

        try:
            source_user_id = int(resolved["telegram_source_user_id"])
        except ValueError as exc:  # pragma: no cover - защита от некорректного ввода
            raise SettingsError(
                "TG_ISTO4NIK_ID (или TGUSERID) должен быть целым числом"
            ) from exc

        return cls(
            deepseek_api_key=resolved["deepseek_api_key"],
            telegram_bot_username=resolved["telegram_bot_username"],
            telegram_bot_token=resolved["telegram_bot_token"],
            telegram_target_channel=resolved["telegram_target_channel"],
            telegram_source_user_id=source_user_id,
        )
