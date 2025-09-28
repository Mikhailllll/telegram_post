"""Основной пайплайн обработки и публикации постов."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import typer

from .config import Settings, SettingsError
from .deepseek_client import DeepSeekClient
from .link_selector import append_links
from .telegram_client import TelegramClient, TelegramMessage


logger = logging.getLogger(__name__)
POPULAR_HASHTAGS = "#crypto #bitcoin #trading #altcoins #defi"
EMOJI_PREFIX = "🚀"


async def _process_messages(
    messages: list[TelegramMessage],
    deepseek_client: DeepSeekClient,
    telegram_client: TelegramClient,
) -> int:
    """Обработать и опубликовать сообщения."""

    processed = 0
    for message in messages:
        logger.info("Обработка сообщения %s", message.message_id)
        adapted = await deepseek_client.adapt_post(message.text)
        prepared = prepare_post(adapted)
        enriched = append_links(prepared)
        await telegram_client.publish_post(enriched)
        processed += 1
    return processed


def prepare_post(text: str) -> str:
    """Добавить эмодзи и базовые хештеги к тексту."""

    stripped = text.strip()
    if not stripped.startswith(EMOJI_PREFIX):
        stripped = f"{EMOJI_PREFIX} {stripped}"

    if POPULAR_HASHTAGS.lower() not in stripped.lower():
        stripped = f"{stripped.rstrip()}\n\n{POPULAR_HASHTAGS}"

    return stripped


async def poll_once(
    settings: Settings, *, last_update_id: Optional[int] = None
) -> Optional[int]:
    """Считать новые посты и опубликовать их один раз."""

    async with TelegramClient(
        settings.telegram_bot_token,
        source_user_id=settings.telegram_source_user_id,
        target_channel=settings.telegram_target_channel,
    ) as telegram_client, DeepSeekClient(settings.deepseek_api_key) as deepseek_client:
        messages, new_last_update = await telegram_client.fetch_new_messages(
            last_update_id
        )
        if not messages:
            logger.info("Новых сообщений не обнаружено")
            return new_last_update

        processed = await _process_messages(messages, deepseek_client, telegram_client)
        logger.info("Опубликовано %d сообщений", processed)
        return new_last_update


async def poll_loop(settings: Settings, *, interval: int = 60) -> None:
    """Циклический опрос канала-источника."""

    last_update_id: Optional[int] = None
    async with TelegramClient(
        settings.telegram_bot_token,
        source_user_id=settings.telegram_source_user_id,
        target_channel=settings.telegram_target_channel,
    ) as telegram_client, DeepSeekClient(settings.deepseek_api_key) as deepseek_client:
        while True:
            messages, last_update_id = await telegram_client.fetch_new_messages(
                last_update_id
            )
            if messages:
                processed = await _process_messages(
                    messages, deepseek_client, telegram_client
                )
                logger.info("Цикл: опубликовано %d сообщений", processed)
            else:
                logger.debug("Цикл: нет новых сообщений")
            await asyncio.sleep(interval)


def run_poll_once() -> None:
    """Запустить одноразовый опрос через CLI."""

    try:
        settings = Settings.from_env()
    except SettingsError as exc:  # pragma: no cover - CLI поведение
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    asyncio.run(poll_once(settings))


def run_poll_loop(interval: int = 60) -> None:
    """Запустить бесконечный цикл опроса."""

    try:
        settings = Settings.from_env()
    except SettingsError as exc:  # pragma: no cover
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    asyncio.run(poll_loop(settings, interval=interval))


app = typer.Typer(help="Автоматизация публикации постов в Telegram")


@app.command("poll-once")
def cli_poll_once() -> None:
    """Разово проверить канал-источник и опубликовать новые посты."""

    run_poll_once()


@app.command("run-loop")
def cli_run_loop(
    interval: int = typer.Option(60, help="Интервал между опросами в секундах")
) -> None:
    """Запустить бесконечный цикл опроса."""

    run_poll_loop(interval=interval)


def main() -> None:  # pragma: no cover - точка входа
    """CLI-обёртка."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
