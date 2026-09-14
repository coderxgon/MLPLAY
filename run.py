"""
MLPlay — unified entry point.
Runs the FastAPI web server (admin panel + mini app API) and the
Telegram bot (polling mode) inside ONE process, so a single Render
service keeps everything alive 24/7.
"""
import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from app.db import init_db
from app.games_svc import GameLoop
from app.bot_controller import BotController
from app.settings_svc import ensure_settings
from app.heroes import ensure_heroes
from app.web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("mlplay")


def touch_data_dir() -> None:
    os.makedirs("data/uploads/receipts", exist_ok=True)
    os.makedirs("data/uploads/heroes", exist_ok=True)
    os.makedirs("data/uploads/logo", exist_ok=True)
    os.makedirs("data/uploads/promo", exist_ok=True)
    os.makedirs("data/uploads/broadcast", exist_ok=True)
    os.makedirs("data/fonts", exist_ok=True)


async def main() -> None:
    touch_data_dir()
    init_db()                       # create tables
    ensure_settings()               # seed default settings
    ensure_heroes()                 # seed hero roster

    game_loop = GameLoop()
    controller = BotController(game_loop)
    app = create_app(controller, game_loop)

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    # start everything together; if one loop dies the others keep the site up
    await asyncio.gather(
        server.serve(),
        controller.start(),
        game_loop.start(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("MLPlay stopped gracefully.")