"""Telegram command handlers: /add, /list, /remove, /start, /help."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from .adapters import resolve, supported_theatres
from .browser import BrowserManager
from .config import Config
from .storage import Storage

log = logging.getLogger(__name__)

HELP = (
    "🎭 <b>Theatre ticket monitor</b>\n\n"
    "I watch sold-out shows and message you when tickets appear.\n\n"
    "<b>Commands</b>\n"
    "/add &lt;url&gt; — start monitoring a production page\n"
    "/list — show what you're monitoring\n"
    "/remove — pick a monitor to delete\n"
    "/help — this message\n\n"
    "<b>Supported theatres</b>\n" + "\n".join(f"• {t}" for t in supported_theatres())
)


def _storage(context: ContextTypes.DEFAULT_TYPE) -> Storage:
    return context.application.bot_data["storage"]


def _browser(context: ContextTypes.DEFAULT_TYPE) -> BrowserManager:
    return context.application.bot_data["browser"]


def _config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def _authorised(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    allowed = _config(context).allowed_user_ids
    if not allowed:
        return True
    user = update.effective_user
    return bool(user and user.id in allowed)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorised(update, context):
        return
    await update.message.reply_html(HELP, disable_web_page_preview=True)


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorised(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /add <production url>")
        return
    url = context.args[0].strip()
    adapter = resolve(url)
    if adapter is None:
        await update.message.reply_html(
            "I don't support that site yet. Supported theatres:\n"
            + "\n".join(f"• {t}" for t in supported_theatres())
        )
        return

    msg = await update.message.reply_text("Checking that link…")
    try:
        result = await adapter.fetch(url, _browser(context))
    except Exception as exc:
        log.warning("Validation fetch failed for %s: %s", url, exc)
        await msg.edit_text(
            "I couldn't read that page. Double-check it's a production page "
            "and try again."
        )
        return

    monitor_id = await _storage(context).add_monitor(
        chat_id=update.effective_chat.id,
        url=url,
        theatre=adapter.name,
        title=result.title,
    )
    if monitor_id is None:
        await msg.edit_text("You're already monitoring that link.")
        return

    avail = len(result.available)
    note = (
        f"{avail} performance(s) currently look available — "
        "I'll only alert on new availability from now on."
        if avail
        else "Currently sold out. I'll message you when tickets appear."
    )
    await msg.edit_text(
        f"✅ Monitoring “{result.title}” at {adapter.name}.\n{note}"
    )


async def list_monitors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorised(update, context):
        return
    monitors = await _storage(context).list_monitors(update.effective_chat.id)
    if not monitors:
        await update.message.reply_text("You're not monitoring anything yet. /add a link.")
        return
    lines = ["<b>You're monitoring:</b>"]
    for m in monitors:
        lines.append(f"{m.id}. {m.title} — {m.theatre}")
    await update.message.reply_html("\n".join(lines), disable_web_page_preview=True)


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorised(update, context):
        return
    storage = _storage(context)
    chat_id = update.effective_chat.id
    # /remove <id> shortcut
    if context.args:
        try:
            mid = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Usage: /remove <id> (see /list)")
            return
        ok = await storage.remove_monitor(chat_id, mid)
        await update.message.reply_text(
            "Removed." if ok else "No monitor with that id."
        )
        return

    monitors = await storage.list_monitors(chat_id)
    if not monitors:
        await update.message.reply_text("Nothing to remove.")
        return
    buttons = [
        [InlineKeyboardButton(f"❌ {m.title[:40]}", callback_data=f"rm:{m.id}")]
        for m in monitors
    ]
    await update.message.reply_text(
        "Tap a monitor to delete it:", reply_markup=InlineKeyboardMarkup(buttons)
    )


async def on_remove_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    if not _authorised(update, context):
        return
    try:
        mid = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    ok = await _storage(context).remove_monitor(update.effective_chat.id, mid)
    await query.edit_message_text("Removed." if ok else "Already gone.")


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("add", add))
    application.add_handler(CommandHandler("list", list_monitors))
    application.add_handler(CommandHandler("remove", remove))
    application.add_handler(CallbackQueryHandler(on_remove_callback, pattern=r"^rm:"))
