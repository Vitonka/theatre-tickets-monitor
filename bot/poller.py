"""The polling job: fetch each monitor, diff, notify on new availability."""
from __future__ import annotations

import logging

from telegram import Bot
from telegram.constants import ParseMode

from .adapters import resolve
from .browser import BrowserManager
from .models import Performance
from .notifier import format_alert
from .storage import Monitor, Storage

log = logging.getLogger(__name__)


def newly_available(
    performances: list[Performance], prior: dict[str, bool]
) -> list[Performance]:
    """Performances that are available now and were not available before.

    "Before" means either unseen (first poll) or previously recorded as
    unavailable. This is what makes us alert on a sold-out → available flip
    without re-alerting every cycle while it stays available.
    """
    fresh = []
    for p in performances:
        if p.available and not prior.get(p.key, False):
            fresh.append(p)
    return fresh


async def check_monitor(
    monitor: Monitor, storage: Storage, browser: BrowserManager, bot: Bot
) -> None:
    adapter = resolve(monitor.url)
    if adapter is None:
        log.warning("No adapter for %s (monitor %s)", monitor.url, monitor.id)
        return
    try:
        result = await adapter.fetch(monitor.url, browser)
    except Exception as exc:  # network/parse failure: skip this cycle
        log.warning("Fetch failed for monitor %s (%s): %s", monitor.id, monitor.url, exc)
        return

    prior = await storage.get_state(monitor.id)
    fresh = newly_available(result.performances, prior)

    if fresh:
        try:
            await bot.send_message(
                chat_id=monitor.chat_id,
                text=format_alert(monitor, fresh),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            log.error("Failed to notify chat %s: %s", monitor.chat_id, exc)
            return  # don't persist state, so we retry the alert next cycle

    # Persist the latest state for every performance we saw.
    for p in result.performances:
        await storage.set_state(monitor.id, p.key, p.available)


async def poll_all(storage: Storage, browser: BrowserManager, bot: Bot) -> None:
    monitors = await storage.all_monitors()
    log.info("Polling %d monitor(s)", len(monitors))
    for monitor in monitors:
        await check_monitor(monitor, storage, browser, bot)
