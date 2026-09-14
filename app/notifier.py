"""
Notifier — bridges sync services (FastAPI threadpool, SQLAlchemy sync) to the
asyncio Telegram bot. Any code can call `send_user(...)`; the coroutine is
dispatched onto the main event loop, so the bot is never blocked.
"""
import asyncio
import logging
from html import escape as _esc

from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("notifier")

_bot = None
LOOP = None


def set_bot(bot):
    global _bot
    _bot = bot


def get_bot():
    return _bot


def set_loop(loop):
    global LOOP
    LOOP = loop


def esc(text) -> str:
    return _esc(str(text), quote=False)


def _dispatch(coro) -> bool:
    loop = LOOP
    if loop is None or not loop.is_running():
        logger.warning("notifier: no running loop, message dropped")
        return False
    try:
        asyncio.run_coroutine_threadsafe(coro, loop)
        return True
    except Exception as e:  # pragma: no cover
        logger.warning("notifier dispatch failed: %s", e)
        return False


async def _send(chat_id, text: str = "", photo: bytes | None = None, kb=None):
    bot = get_bot()
    if bot is None or not chat_id:
        return False
    try:
        if photo:
            await bot.send_photo(chat_id, BufferedInputFile(photo, filename="mlplay.png"),
                                 caption=text, reply_markup=kb)
        else:
            await bot.send_message(chat_id, text, reply_markup=kb)
        return True
    except Exception as e:  # bot blocked / chat deleted etc.
        logger.info("send to %s failed: %s", chat_id, e)
        return False


def send_user(chat_id, text: str = "", photo: bytes | None = None, kb=None) -> bool:
    return _dispatch(_send(chat_id, text, photo, kb))


def send_text(chat_id, text: str, kb=None) -> bool:
    return send_user(chat_id, text=text, kb=kb)


def send_photo(chat_id, photo: bytes, caption: str = "", kb=None) -> bool:
    return send_user(chat_id, text=caption, photo=photo, kb=kb)


def kb(rows) -> InlineKeyboardMarkup | None:
    """rows: [[{"t": text, "cb": callback_data} | {"t": text, "u": url} | {"t": text, "wa": url}], ...]"""
    if not rows:
        return None
    parsed = []
    for row in rows:
        btns = []
        for item in row:
            if "u" in item:
                btns.append(InlineKeyboardButton(text=item["t"], url=item["u"]))
            elif "wa" in item:
                from aiogram.types import WebAppInfo
                btns.append(InlineKeyboardButton(text=item["t"], web_app=WebAppInfo(url=item["wa"])))
            else:
                btns.append(InlineKeyboardButton(text=item["t"], callback_data=item["cb"]))
        parsed.append(btns)
    return InlineKeyboardMarkup(inline_keyboard=parsed)


def resolve_target(target: str) -> str | int | None:
    """Channels/groups stored as '@name' or numeric id."""
    if not target:
        return None
    t = str(target).strip()
    if t.lstrip("-").isdigit():
        return int(t)
    if t.startswith("@"):
        return t
    return t