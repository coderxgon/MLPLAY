"""Key-value settings stored in the DB, plus default seeding."""
import json

from app.config import START_UP_BOT_TOKEN, WEBAPP_URL
from app.db import SessionLocal
from app.models import Setting

DEFAULT_WELCOME = (
    "⚡ **WELCOME TO THE MLPLAY ARENA** ⚡\n\n"
    "Where every battle counts and legends are forged! 🏆\n\n"
    "🎮 3 Epic Games: Rank Match • Who's The MVP? • HeRole\n"
    "⚔️ Real-time matches every 2 minutes\n"
    "💰 Earn up to ₱50,000 per bet\n"
    "🎁 Daily rewards • Promo codes • VIP ranks\n\n"
    "Tap **Register to MLPlay** below and claim your spot! 🔥"
)

DEFAULTS = {
    "bot_token": START_UP_BOT_TOKEN,
    "bot_username": "",
    "bot_name": "MLPlay",
    "webapp_url": WEBAPP_URL,
    "welcome_text": DEFAULT_WELCOME,
    "logo_path": "",
    "welcome_media_path": "",
    "referral_pct": 5.0,            # % of invitee's FIRST deposit credited to inviter
    "daily_bonus": 2.0,             # ₱ daily claim reward
    "bind_bonus": 30.0,             # ₱ one-time bonus for binding bank/wallet
    "rank_bonus": {                 # ₱ bonus awarded when REACHING each rank
        "warrior": 0, "elite": 1, "master": 3, "grandmaster": 10,
        "epic": 15, "legend": 30, "mythic": 50, "honor": 100,
        "glory": 200, "immortal": 5000,
    },
    "maintenance": False,           # global betting freeze
    "game_channel": "",             # channel for live match posts (@name or -100 id)
    "tx_group": "",                 # group posting deposit/withdraw requests
    "action_group": "",             # group posting ban/suspend/action notifications
    "csr_group": "",
    "csr_channel": "",
    "csr1": "",
    "csr2": "",
    "csr3": "",
    "admin_ids": [],                # up to 10 telegram ids
    "winrate": {"rank": 0.30, "mvp": 0.30, "herole": 0.30},
    "admin_password": "",
    "referral_text": (
        "🎮 Ready to join the MLPlay Arena? Register now and let's dominate the leaderboard! 💥\n"
        "👇 Tap this link to join:\n{link}\n\nSee you in the arena! ⚡"
    ),
}


def _loads(v):
    try:
        return json.loads(v)
    except Exception:
        return v


def ensure_settings() -> None:
    s = SessionLocal()
    try:
        for key, val in DEFAULTS.items():
            if not s.get(Setting, key):
                s.add(Setting(key=key, value=json.dumps(val, ensure_ascii=False)))
        s.commit()
    finally:
        s.close()


def get_setting(session, key, default=None):
    row = session.get(Setting, key)
    if row is None:
        return default
    return _loads(row.value)


def set_setting(session, key, value):
    row = session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=json.dumps(value, ensure_ascii=False))
        session.add(row)
    else:
        row.value = json.dumps(value, ensure_ascii=False)
    session.commit()


def get_all_settings(session) -> dict:
    out = dict(DEFAULTS)
    for row in session.query(Setting).all():
        out[row.key] = _loads(row.value)
    return out


def winrate_for(session, user, game: str) -> float:
    """Effective win rate: user override > global default."""
    global_wr = get_setting(session, "winrate", {})
    try:
        g = float(global_wr.get(game, 0.3))
    except Exception:
        g = 0.3
    if user.winrate_override:
        try:
            ov = json.loads(user.winrate_override)
            if str(game) in ov:
                return max(0.0, min(1.0, float(ov[str(game)])))
        except Exception:
            pass
    return max(0.0, min(1.0, g))


def set_winrate_override(session, user, game: str, rate: float):
    cur = {}
    if user.winrate_override:
        try:
            cur = json.loads(user.winrate_override)
        except Exception:
            cur = {}
    cur[game] = max(0.0, min(1.0, float(rate)))
    user.winrate_override = json.dumps(cur)
    session.commit()


def is_admin_tg(session, tg_id) -> bool:
    admins = [int(x) for x in get_setting(session, "admin_ids", [])]
    return tg_id in admins


def get_admin_password(session) -> str:
    pw = get_setting(session, "admin_password", "") or ""
    return pw or "MLPlay-Admin-2026"


def effective_webapp_url(session, request_host: str = "") -> str:
    u = get_setting(session, "webapp_url", "") or ""
    if not u and request_host:
        u = f"https://{request_host}"
    return u.rstrip("/")