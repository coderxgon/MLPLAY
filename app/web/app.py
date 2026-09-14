"""FastAPI application factory: admin panel, mini app API + SPA, media."""
import os

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import UPLOADS_DIR
from app.web import auth

_HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(_HERE, "static")
MINI_DIR = os.path.join(STATIC_DIR, "mini")
TEMPLATE_DIR = os.path.join(_HERE, "templates")


def create_app(controller=None, game_loop=None) -> FastAPI:
    app = FastAPI(title="MLPlay", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.controller = controller
    app.state.game_loop = game_loop

    templates = Jinja2Templates(directory=TEMPLATE_DIR)
    app.state.templates = templates

    # ------------------------------------------------------------- auth guard
    @app.middleware("http")
    async def admin_guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/admin") and path not in ("/admin/login",):
            if not auth.check_session(request.cookies.get(auth.COOKIE_NAME)):
                return RedirectResponse("/admin/login", status_code=302)
        return await call_next(request)

    # ------------------------------------------------------------- routes
    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/admin")

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"ok": True, "app": "MLPlay"}

    # media: QR pngs generated on the fly must be registered BEFORE the mount
    @app.get("/media/qr/{method_id}.png")
    async def qr_png(method_id: int):
        from fastapi.responses import Response
        from app.db import get_session
        from app.models import DepositMethod
        s = get_session()
        try:
            m = s.get(DepositMethod, method_id)
        finally:
            s.close()
        import io
        import qrcode
        qr = qrcode.make(m.detail or f"MLPlay Deposit {m.name}" if m else "MLPlay")
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    app.mount("/media", StaticFiles(directory=UPLOADS_DIR), name="media")

    # mini app SPA (served at /mini)
    app.mount("/mini", StaticFiles(directory=MINI_DIR, html=True), name="mini")

    # admin static assets (css/js)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # routers
    from app.web.admin_routes import router as admin_router
    from app.web.mini_routes import router as mini_router
    app.include_router(admin_router)
    app.include_router(mini_router)

    # optional telegram webhook endpoint (polling is the default)
    @app.post("/webhook/{token}")
    async def webhook(token: str, request: Request):
        from app.db import get_session
        from app.settings_svc import get_setting
        s = get_session()
        try:
            configured = get_setting(s, "bot_token", "")
        finally:
            s.close()
        if token != configured:
            return {"ok": False}
        if controller and controller.dp and controller.bot:
            from aiogram.types import Update
            import json
            payload = await request.json()
            upd = Update.model_validate(payload)
            await controller.dp.feed_update(controller.bot, upd)
        return {"ok": True}

    return app