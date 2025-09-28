"""Определение биржи и выбор промо-ссылок."""

from __future__ import annotations

import re
from typing import Optional


EXCHANGE_LINKS = {
    "okx": (
        "\n\n"
        "💼 OKX для новых трейдеров:\n"
        "• Регистрация: https://www.okx.com/join/your_ref\n"
        "• Приложение iOS: https://apps.apple.com/app/okx/id1327268470\n"
        "• Приложение Android: https://play.google.com/store/apps/details?id=com.okinc.okex.gp\n"
    ),
    "binance": (
        "\n\n"
        "💼 Binance — топовая ликвидность:\n"
        "• Регистрация: https://accounts.binance.com/register?ref=YOURCODE\n"
        "• Платформа Web: https://www.binance.com\n"
        "• Мобильное приложение: https://www.binance.com/en/download\n"
    ),
}

KEYWORDS = {
    "okx": (r"\bokx\b", r"\bокх\b"),
    "binance": (r"\bbinance\b", r"\bбинанс\b"),
}


def detect_exchange(text: str) -> Optional[str]:
    """Определить биржу по ключевым словам."""

    normalized = text.lower()
    for exchange, patterns in KEYWORDS.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            return exchange
    return None


def append_links(text: str) -> str:
    """Добавить релевантный блок ссылок к тексту."""

    exchange = detect_exchange(text)
    if not exchange:
        return text

    return text.rstrip() + EXCHANGE_LINKS[exchange]
