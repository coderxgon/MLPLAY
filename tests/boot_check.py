"""Final boot check: import every bot module, render every admin page."""
import os
os.environ.setdefault("DEBUG_WEBAPP_DEV", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/mlplay_boot.db")
if os.path.exists("/tmp/mlplay_boot.db"):
    os.remove("/tmp/mlplay_boot.db")

# 1) import ALL bot modules (register_handlers path)
import app.bot_core  # noqa: F401
import app.bot_games  # noqa: F401
import app.bot_admin  # noqa: F401
import app.bot_controller  # noqa: F401
import app.games_svc  # noqa: F401
print("✔ all bot modules import OK")

# 2) boot the full app
from app.db import init_db
from app.settings_svc import ensure_settings
from app.heroes import ensure_heroes
init_db(); ensure_settings(); ensure_heroes()

from fastapi.testclient import TestClient
from app.web.app import create_app
from app.bot_controller import BotController
from app.games_svc import GameLoop
from app.ranks import RANKS

app = create_app(BotController(), GameLoop())
c = TestClient(app)

# admin login
r = c.post("/admin/login", data={"password": "MLPlay-Admin-2026"}, follow_redirects=False)
assert r.status_code == 302
tok = r.cookies.get("mlp_session")
cookies = {"mlp_session": tok}

pages = ["", "/users", "/users?q=smoke", "/deposits", "/withdrawals", "/payments",
         "/promotions", "/games", "/rankings", "/broadcast", "/customize",
         "/customize?tab=channels", "/customize?tab=csr", "/customize?tab=admins",
         "/heroes", "/logs"]
for p in pages:
    r = c.get("/admin" + p, cookies=cookies)
    assert r.status_code == 200, (p, r.status_code)
print(f"✔ {len(pages)} admin pages render")

for p in ["/mini/index.html", "/mini/mini.css", "/mini/mini.js", "/static/admin.css", "/static/admin.js"]:
    r = c.get(p)
    assert r.status_code == 200, (p, r.status_code)
print("✔ static assets served")

# mini api with dev header
hdr = {"X-Init-Data": "", "X-Dev-Uid": "4242"}
r = c.get("/miniapp/me", headers=hdr)
assert r.status_code == 200 and r.json()["ok"], r.text
r = c.get("/miniapp/withdraw-channels", headers=hdr)
assert r.status_code == 200 and r.json()["bound"] is False, r.text
assert "Bind your wallet" in r.json()["hint"]
print("✔ mini app APIs OK (unbound user sees bind-first withdraw)")

# game loop tick + match creation path (no bot: channel posts are skipped safely)
gl = GameLoop()
gl._tick()  # should create an open match (aligned to current slot)
import time
from app.db import get_session
from app.models import Match
s = get_session()
try:
    m = s.query(Match).order_by(Match.id.desc()).first()
    assert m is not None and m.status == "open"
    gl._resolve_match(s, m)  # resolve directly; must not raise without bot
    print(f"✔ game loop tick ok (match #{m.match_no} created/resolved)")
finally:
    s.close()

print("\n✅ BOOT CHECK PASSED")