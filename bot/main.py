"""Entry point: wire storage, browser, Telegram app and the polling job."""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from telegram.ext import Application, ContextTypes

from .adapters import supported_theatres
from .bot import register_handlers
from .browser import BrowserManager
from .config import Config
from .poller import poll_all
from .storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("theatre-monitor")


async def _poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_data = context.application.bot_data
    await poll_all(bot_data["storage"], bot_data["browser"], context.bot)


async def _on_startup(application: Application) -> None:
    config: Config = application.bot_data["config"]
    storage = Storage(config.db_path)
    await storage.connect()
    application.bot_data["storage"] = storage
    application.bot_data["browser"] = BrowserManager(config)
    log.info(
        "Started. Polling every %d min. Adapters: %s",
        config.poll_interval_min,
        ", ".join(supported_theatres()),
    )


async def _on_shutdown(application: Application) -> None:
    storage: Storage = application.bot_data.get("storage")
    browser: BrowserManager = application.bot_data.get("browser")
    if browser:
        await browser.close()
    if storage:
        await storage.close()


def main() -> None:
    config = Config.from_env()
    db_dir = os.path.dirname(config.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    application = (
        Application.builder()
        .token(config.telegram_token)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )
    application.bot_data["config"] = config
    register_handlers(application)

    application.job_queue.run_repeating(
        _poll_job,
        interval=timedelta(minutes=config.poll_interval_min),
        first=timedelta(seconds=20),
        name="poll_all",
    )

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
