"""Основной пайплайн обработки и публикации постов."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import typer

from .config import Settings, SettingsError
from .deepseek_client import DeepSeekClient
from .link_selector import append_links
from .telegram_client import TelegramClient, TelegramMessage


logger = logging.getLogger(__name__)
POPULAR_HASHTAGS = "#crypto #bitcoin #trading #altcoins #defi"
EMOJI_PREFIX = "🚀"
DEFAULT_STATE_FILE = Path(".telegram_post_state.json")


def read_last_update_id(state_file: Path) -> Optional[int]:
    """Прочитать идентификатор последнего обновления из файла состояния."""

    if not state_file.exists():
        logger.debug("Файл состояния %s отсутствует", state_file)
        return None

    try:
        raw = state_file.read_text(encoding="utf-8").strip()
    except OSError as exc:  # pragma: no cover - ошибки ввода/вывода редки
        logger.warning("Не удалось прочитать файл состояния %s: %s", state_file, exc)
        return None

    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "Файл состояния %s содержит некорректный JSON: %s", state_file, exc
        )
        return None

    last_update_id = payload.get("last_update_id")
    if isinstance(last_update_id, int):
        return last_update_id

    logger.warning(
        "Файл состояния %s не содержит корректного last_update_id", state_file
    )
    return None


def write_last_update_id(state_file: Path, last_update_id: int) -> None:
    """Сохранить идентификатор последнего обновления в файл состояния."""

    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"last_update_id": last_update_id}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - ошибки ввода/вывода редки
        logger.warning("Не удалось записать файл состояния %s: %s", state_file, exc)


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

        if len(messages) > 2:
            messages = messages[-2:]
        logger.info("К публикации подготовлено %d сообщений", len(messages))
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
            previous_last_update_id = last_update_id
            messages, last_update_id = await telegram_client.fetch_new_messages(
                last_update_id
            )
            if messages:
                if previous_last_update_id is None and len(messages) > 2:
                    messages = messages[-2:]
                logger.info("Цикл: к публикации %d сообщений", len(messages))
                processed = await _process_messages(
                    messages, deepseek_client, telegram_client
                )
                logger.info("Цикл: опубликовано %d сообщений", processed)
            else:
                logger.debug("Цикл: нет новых сообщений")
            await asyncio.sleep(interval)


def run_poll_once(state_file: Path = DEFAULT_STATE_FILE) -> None:
    """Запустить одноразовый опрос через CLI с учётом файла состояния."""

    try:
        settings = Settings.from_env()
    except SettingsError as exc:  # pragma: no cover - CLI поведение
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    masked_pairs = ", ".join(
        f"{name}={value}" for name, value in settings.masked_secrets().items()
    )
    logger.info("Загружены переменные: %s", masked_pairs)

    last_update_id = read_last_update_id(state_file)
    new_last_update = asyncio.run(poll_once(settings, last_update_id=last_update_id))
    if new_last_update is not None:
        write_last_update_id(state_file, new_last_update)


def run_poll_loop(interval: int = 60) -> None:
    """Запустить бесконечный цикл опроса."""

    try:
        settings = Settings.from_env()
    except SettingsError as exc:  # pragma: no cover
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    masked_pairs = ", ".join(
        f"{name}={value}" for name, value in settings.masked_secrets().items()
    )
    logger.info("Загружены переменные: %s", masked_pairs)

    asyncio.run(poll_loop(settings, interval=interval))


app = typer.Typer(help="Автоматизация публикации постов в Telegram")


@app.command("poll-once")
def cli_poll_once(
    state_file: Path = typer.Option(
        DEFAULT_STATE_FILE,
        "--state-file",
        help="Путь к JSON-файлу состояния с last_update_id",
    )
) -> None:
    """Разово проверить канал-источник и опубликовать новые посты."""

    run_poll_once(state_file=state_file)


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
