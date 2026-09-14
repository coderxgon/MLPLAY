"""Headless smoke test — exercises DB, wallet, cards, mini-app API without Telegram."""
import os
import sys

os.environ.setdefault("DEBUG_WEBAPP_DEV", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/mlplay_smoke.db")

if os.path.exists("/tmp/mlplay_smoke.db"):
    os.remove("/tmp/mlplay_smoke.db")

import io  # noqa: E402

from app.db import init_db, get_session  # noqa: E402
from app.settings_svc import ensure_settings, get_setting  # noqa: E402
from app.heroes import ensure_heroes  # noqa: E402

init_db()
ensure_settings()
ensure_heroes()

s = get_session()
try:
    from app.heroes import get_hero_pool
    heroes = get_hero_pool(s)
    assert len(heroes) == 133, f"expected 133 heroes, got {len(heroes)}"
    roles = {h.role for h in heroes}
    assert roles == {"tank", "fighter", "assassin", "mage", "support", "marksman"}, roles
    print(f"✔ heroes seeded: {len(heroes)}")

    import app.wallet as w
    from app.models import User, DepositMethod, WithdrawChannel, Bet

    user = w.get_or_create_user(s, 1001, chat_id=1001, tg_username="smoke", tg_fullname="Smoke Tester")
    assert user.rank_key == "warrior"

    # bind wallet -> +₱30
    bonus, err = w.bind_wallet(s, user, "GCash", "09171234567", "Smoke Tester")
    assert err is None and bonus == 30.0, (bonus, err)
    assert user.balance == 30.0
    assert w.bind_wallet(s, user, "Maya", "1", "X")[1], "second bind should fail"

    # unbound user cannot withdraw
    user2 = w.get_or_create_user(s, 1002, chat_id=1002, tg_username="smoke2", tg_fullname="No Bind")
    o2, err2 = w.submit_withdraw(s, user2, 0, 10)
    assert o2 is None and err2, "unbound withdrawal must be rejected"
    print("✔ unbound withdrawal blocked")

    # deposit method + deposit submit
    m = DepositMethod(name="GCash", detail="0917 123 4567 — Smoke", min_amount=1, max_amount=50000, active=True)
    s.add(m)
    ch = WithdrawChannel(name="GCash Out", fields='[{"key":"account_number","label":"Account Number","type":"text"}]',
                         min_amount=1, max_amount=50000, active=True)
    s.add(ch)
    s.commit(); s.refresh(m); s.refresh(ch)

    order, err = w.submit_deposit(s, user, m.id, 500, None, {"note": "test"})
    assert err is None and order and order.status == "pending", err
    assert w.approve_deposit(s, order, "smoke-admin", "ok") is True
    assert user.total_deposit == 500.0 and user.balance == 530.0
    # rank after deposit: 500 deposits + 0 bets -> still elite? need bets too; check rank mapping
    from app.ranks import rank_for
    print(f"✔ deposit approved; balance={user.balance} rank={rank_for(user)['name']} valid_bets={user.valid_bets}")

    # promo + daily
    from app.models import Promo
    s.add(Promo(code="SMOKE50", title="Smoke", amount=50, uses_max=5, active=True))
    s.commit()
    amt, err = w.redeem_promo(s, user, "smoke50")
    assert amt == 50.0 and err is None, err
    amt2, err = w.daily_claim(s, user)
    assert amt2 == 2.0, err
    assert w.daily_claim(s, user)[1], "double daily claim should fail"

    # bets: place rank bet then settle
    from app.games_svc import generate_teams, teams_display
    import json
    teams = generate_teams(s)
    assert len(teams["blue"]) == 5 and len(teams["red"]) == 5
    assert len(set(teams["blue"] + teams["red"])) == 10, "no duplicate heroes allowed"
    blue, red = teams_display(s, teams)
    assert len(blue) == 5 and len(red) == 5
    from app.models import Match
    mt = Match(match_no=9999, status="open", teams=json.dumps(teams))
    s.add(mt)
    s.commit(); s.refresh(mt)
    bet, err = w.place_bet(s, user, "rank", 10, mt.match_no, "blue")
    assert err is None and bet.status == "pending", err
    assert user.balance == 30.0 + 500.0 + 50.0 + 2.0 - 10.0, user.balance  # bind+deposit+promo+daily-bet
    assert w.settle_bet(s, bet) is True
    assert bet.status in ("won", "lost")
    print(f"✔ rank bet settled: {bet.status} payout={bet.payout} balance={user.balance} bets={user.valid_bets}")

    # hero pick validations
    from app.heroes import hero_by_name
    assert hero_by_name(s, "popol and kupa") is not None
    assert hero_by_name(s, "yi sun-shin") is not None
    assert hero_by_name(s, "x.borg") is not None
    print("✔ hero name matching (Popol and Kupa / Yi Sun-shin / X.Borg)")

    # rank-up bonus path
    assert user.valid_bets == 1
    print(f"✔ rank now: {rank_for(user)['name']} (rank_key cached: {user.rank_key})")

    # cards
    from app import cards
    imgs = {
        "welcome": cards.welcome_card(is_new=True),
        "profile": cards.profile_card("Smoke Tester", "smoke", {"tier": "Level 1", "name": "Elite"},
                                      530.0, 610.0, 82.0, 500.0, 0.0, 1, "2026-09-14",
                                      "PLAYER", "—", "https://t.me/x?start=ref_1001", bind_label="GCash • 09171234567"),
        "referral": cards.referral_card("Elite", 0.0, 3, 1, "https://t.me/x?start=ref_1001",
                                        [("A", 10.0), ("B", 5.0)]),
        "lineup": cards.lineup_card(9999, blue, red),
        "fight_r": cards.fight_card("rank", match_no=9999, blue=blue, red=red),
        "fight_m": cards.fight_card("mvp", hero={"name": "Layla", "color1": "#E74C3C", "color2": "#641E16"}),
        "fight_h": cards.fight_card("herole", picked_role="marksman"),
        "result": cards.result_card("🎉 YOU WON!", "Blue team dominated!", "+₱10.00 (x2)", win=True),
        "banner": cards.banner_card("MLPLAY GAMES", "Live now"),
        "hero": cards.hero_portrait(heroes[0]),
    }
    for name, data in imgs.items():
        assert isinstance(data, bytes) and len(data) > 5000, (name, len(data) if isinstance(data, bytes) else type(data))
    print("✔ all 10 card types generated:", {k: len(v) for k, v in imgs.items()})

    # withdraw submit + reject refund
    order2, err = w.submit_withdraw(s, user, ch.id, 25, {"account_number": "09171111111"})
    assert err is None and order2, err
    assert user.balance == round(30 + 500 + 50 + 2 + (10 if bet.status == "won" else -10) - 25, 2), user.balance
    assert w.reject_withdraw(s, order2, "smoke-admin", "test reject") is True
    print(f"✔ withdraw submit + reject refund ok, balance={user.balance}")

    # admin user action (ban + bonus)
    assert w.admin_user_action(s, user, "add_balance", "Welcome", "extra", amount=5, admin="t")[0] is True
finally:
    s.close()

# ------------------------------------------------------------------ web API
from fastapi.testclient import TestClient  # noqa: E402
from app.web.app import create_app  # noqa: E402
from app.bot_controller import BotController  # noqa: E402
from app.games_svc import GameLoop  # noqa: E402

ctrl = BotController()
app = create_app(ctrl, GameLoop())
client = TestClient(app)

hdr = {"X-Init-Data": "", "X-Dev-Uid": "1001"}
r = client.get("/health")
assert r.status_code == 200 and r.json()["ok"]

r = client.get("/miniapp/me", headers=hdr)
assert r.status_code == 200 and r.json()["ok"], r.text
me = r.json()["user"]
assert me["balance"] > 0, me

r = client.get("/miniapp/deposit-methods", headers=hdr)
assert r.status_code == 200 and r.json()["ok"] and r.json()["methods"]
mid = r.json()["methods"][0]["id"]

# QR generation
r = client.get(f"/media/qr/{mid}.png")
assert r.status_code == 200 and r.headers["content-type"] == "image/png", r.status_code
print("✔ QR endpoint ok")

r = client.get("/miniapp/withdraw-channels", headers=hdr)
assert r.status_code == 200 and r.json()["ok"] and r.json()["bound"] is True, r.text
assert r.json()["binding"]["account"] == "09171234567"
print("✔ bound wallet returned for withdraw:", r.json()["binding"]["wallet"])

r = client.post("/miniapp/deposit", headers=hdr, json={"method_id": mid, "amount": 100})
assert r.status_code == 200 and r.json()["ok"], r.text

r = client.post("/miniapp/withdraw", headers=hdr, json={"channel_id": 1, "amount": 10, "fields": {"account_number": "0917"}})
assert r.status_code == 200 and r.json()["ok"], r.text

r = client.post("/miniapp/promo", headers=hdr, json={"code": "SMOKE50"})
assert r.status_code == 400 or r.json()["ok"]  # may be used up; endpoint must work
print("✔ deposit/withdraw/promo endpoints ok")

r = client.get("/miniapp/history?kind=all", headers=hdr)
assert r.status_code == 200 and r.json()["ok"] and len(r.json()["rows"]) > 0
print("✔ history rows:", len(r.json()["rows"]))

r = client.get("/miniapp/leaderboard", headers=hdr)
assert r.status_code == 200 and r.json()["ok"]
print("✔ leaderboard ok")

# admin login
r = client.get("/admin/login")
assert r.status_code == 200
r = client.post("/admin/login", data={"password": "MLPlay-Admin-2026"}, follow_redirects=False)
assert r.status_code == 302 and "mlp_session" in r.headers.get("set-cookie", ""), r.status_code
tok = r.cookies.get("mlp_session")
c = {"mlp_session": tok}
r = client.get("/admin", cookies=c)
assert r.status_code == 200, r.status_code
r = client.get("/admin/users", cookies=c)
assert r.status_code == 200
r = client.post("/admin/users/action", cookies=c, json={"tg_id": 1001, "action": "suspend", "title": "Test", "remark": "smoke"})
assert r.json()["ok"]
r = client.post("/admin/users/action", cookies=c, json={"tg_id": 1001, "action": "unsuspend", "title": "Test", "remark": "smoke"})
assert r.json()["ok"]
r = client.post("/admin/users/bind", cookies=c, json={"tg_id": 1001, "bind_name": "Maya", "bind_account": "0987654321", "bind_holder": "Smoke"})
assert r.json()["ok"]
print("✔ admin panel pages + user actions + bind ok")

r = client.post("/admin/winrate/save", cookies=c, json={"rank": 0.25, "mvp": 0.3, "herole": 0.3})
assert r.json()["ok"]
r = client.post("/admin/rankbonus/save", cookies=c, json={"epic": 20})
assert r.json()["ok"]
# approve a *pending* order (the mini-app deposit from the API section)
from app.db import get_session as gs2
from app.models import Order as OrderModel
_s = gs2()
try:
    _pending = _s.query(OrderModel).filter(OrderModel.status == "pending").first()
finally:
    _s.close()
if _pending:
    r = client.post("/admin/order/action", cookies=c, json={"order_id": _pending.id, "action": "approve"})
    assert r.json()["ok"], r.text
    print(f"✔ admin approved pending order #{_pending.id}")
r = client.post("/admin/promos/add", cookies=c, data={"code": "TEST100", "title": "t", "amount": "100", "uses_max": "1"}, follow_redirects=False)
assert r.status_code == 302
print("✔ admin settings/winrate/rankbonus/order/promos endpoints ok")

r = client.get("/mini/index.html")
assert r.status_code == 200
r = client.get("/mini/mini.js")
assert r.status_code == 200
print("✔ mini app SPA served")

print("\n✅ ALL SMOKE TESTS PASSED")