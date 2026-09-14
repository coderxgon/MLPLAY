"""
BotController — owns the bot's lifecycle.

- Starts polling as soon as a bot token is available (from env or set later
  in the Admin panel).
- Watches the token setting every 15 s and hot-reloads the bot with a new
  token without restarting the server.
- Feeds the notifier bridge + runs the broadcast job runner.
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile

from app import notifier
from app.db import SessionLocal, get_session
from app.settings_svc import get_setting, set_setting

logger = logging.getLogger("botctl")


def register_handlers(dp: Dispatcher):
    from app.bot_core import router as r_core
    from app.bot_games import router as r_games
    from app.bot_admin import router as r_admin
    dp.include_routers(r_core, r_games, r_admin)


class BotController:
    def __init__(self, game_loop=None):
        self.game_loop = game_loop
        self.bot = None
        self.dp = None
        self.task = None
        self._token = None

    # ------------------------------------------------------------ lifecycle
    async def start(self):
        notifier.set_loop(asyncio.get_running_loop())
        asyncio.create_task(self._watchdog())
        asyncio.create_task(self._broadcast_runner())
        logger.info("Bot controller started (waiting for token if none set).")

    def _read_token(self) -> str:
        s = get_session()
        try:
            return str(get_setting(s, "bot_token", "") or "").strip()
        finally:
            s.close()

    async def _watchdog(self):
        while True:
            try:
                token = self._read_token()
                if token and token != self._token:
                    await self._start_bot(token)
                elif not token and self.bot is not None:
                    await self._stop_polling()
                    self._token = None
                    logger.info("Bot token cleared — polling stopped.")
            except Exception as e:  # noqa: BLE001
                logger.exception("watchdog error: %s", e)
            await asyncio.sleep(15)

    async def _start_bot(self, token: str):
        await self._stop_polling()
        self._token = token
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        if self.dp is None:
            dp = Dispatcher(storage=MemoryStorage())
            dp["sm"] = SessionLocal
            register_handlers(dp)
            self.dp = dp
        notifier.set_bot(bot)
        self.bot = bot
        try:
            me = await bot.get_me()
            s = get_session()
            try:
                set_setting(s, "bot_username", me.username or "")
                if me.first_name:
                    set_setting(s, "bot_name", me.first_name)
            finally:
                s.close()
            logger.info("Telegram bot live: @%s", me.username)
        except Exception as e:  # noqa: BLE001
            logger.warning("could not verify bot token (invalid?): %s", e)
            await self._stop_polling()
            self._token = None
            return
        self._ensure_welcome_media()
        self.task = asyncio.create_task(self._poll(bot))

    async def _poll(self, bot: Bot):
        try:
            await self.dp.start_polling(bot, allowed_updates=self.dp.resolve_used_update_types())
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("polling crashed: %s", e)

    async def _stop_polling(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except Exception:
                pass
            self.task = None
        if self.bot:
            try:
                await self.bot.session.close()
            except Exception:
                pass
        notifier.set_bot(None)
        self.bot = None

    def _ensure_welcome_media(self):
        s = get_session()
        try:
            path = get_setting(s, "welcome_media_path", "") or ""
            if not path or not os.path.exists(path):
                from app.cards import generate_welcome_media
                p = generate_welcome_media(s)
                set_setting(s, "welcome_media_path", p)
        finally:
            s.close()

    # ----------------------------------------------------------- broadcasts
    async def _broadcast_runner(self):
        while True:
            try:
                if self.bot is not None:
                    await self._run_broadcast_jobs()
            except Exception as e:  # noqa: BLE001
                logger.exception("broadcast runner: %s", e)
            await asyncio.sleep(5)

    async def _run_broadcast_jobs(self):
        from datetime import datetime

        from app.models import BroadcastJob, User
        from app.ranks import rank_for

        s = get_session()
        try:
            job = s.query(BroadcastJob).filter(BroadcastJob.status == "pending").first()
            if not job:
                return
            job.status = "running"
            s.commit()
            users = s.query(User).filter(User.chat_id > 0).all()
            if job.target_rank:
                users = [u for u in users if rank_for(u)["key"] == job.target_rank]
            job.total = len(users)
            s.commit()
            buttons = None
            if job.button_text and job.button_url:
                buttons = notifier.kb([[{"t": job.button_text, "u": job.button_url}]])
            for u in users:
                try:
                    if job.image_path and os.path.exists(job.image_path):
                        await self.bot.send_photo(u.chat_id, FSInputFile(job.image_path),
                                                  caption=job.text or "", reply_markup=buttons)
                    else:
                        await self.bot.send_message(u.chat_id, job.text or "", reply_markup=buttons)
                    job.done += 1
                except Exception:
                    job.failed += 1
                s.commit()
            job.status = "done"
            job.finished_at = datetime.utcnow()
            s.commit()
            logger.info("Broadcast job #%s done: %s ok / %s failed", job.id, job.done, job.failed)
        finally:
            s.close()