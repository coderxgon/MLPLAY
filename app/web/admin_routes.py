"""Admin panel routes (under /admin, session-guarded by middleware)."""
import json
import os
import shutil

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse

from app import wallet
from app.config import UPLOADS_DIR
from app.db import get_session
from app.models import (
    ActionLog, Bet, BroadcastJob, DepositMethod, Hero, Order, Promotion, Promo,
    User, WithdrawChannel,
)
from app.ranks import RANKS, RANK_EMOJI, rank_for
from app.settings_svc import (
    get_all_settings, get_setting, is_admin_tg, set_setting, set_winrate_override,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------- helpers --
def tpl(request: Request, name: str, ctx: dict = None):
    templates = request.app.state.templates
    ctx = ctx or {}
    ctx.setdefault("active", name.replace(".html", ""))
    return templates.TemplateResponse(request=request, name=name, context=ctx)


def _db():
    return get_session()


def _save_upload(file: UploadFile | None, folder: str) -> str:
    if not file or not file.filename:
        return ""
    ext = os.path.splitext(file.filename)[1] or ".png"
    fname = f"{int(__import__('time').time() * 1000)}{ext}"
    os.makedirs(os.path.join(UPLOADS_DIR, folder), exist_ok=True)
    path = os.path.join(UPLOADS_DIR, folder, fname)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return f"/media/{folder}/{fname}"


# ---------------------------------------------------------------- login ----
@router.get("/login")
async def login_page(request: Request):
    return tpl(request, "login.html", {"active": "login"})


@router.post("/login")
async def login(request: Request):
    from app.web import auth
    body = await request.form()
    password = str(body.get("password", ""))
    s = _db()
    try:
        ok = password == (get_setting(s, "admin_password", "") or "MLPlay-Admin-2026")
    finally:
        s.close()
    if not ok:
        return tpl(request, "login.html", {"error": "Wrong password", "active": "login"})
    tok = auth.create_session()
    resp = RedirectResponse("/admin", status_code=302)
    resp.set_cookie(auth.COOKIE_NAME, tok, httponly=True, max_age=30 * 86400)
    return resp


@router.get("/logout")
async def logout(request: Request):
    from app.web import auth
    auth.destroy_session(request.cookies.get(auth.COOKIE_NAME))
    resp = RedirectResponse("/admin/login", status_code=302)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


# ------------------------------------------------------------- dashboard --
@router.get("")
async def dashboard(request: Request):
    s = _db()
    try:
        users = s.query(User).count()
        total_deposit = sum(o.amount or 0 for o in s.query(Order).filter(Order.kind == "deposit",
                                                                         Order.status == "approved").all())
        total_withdraw = sum(o.amount or 0 for o in s.query(Order).filter(Order.kind == "withdraw",
                                                                          Order.status == "approved").all())
        wins = sum(b.payout or 0 for b in s.query(Bet).filter(Bet.status == "won").all())
        bonus = sum(o.amount or 0 for o in s.query(Order).filter(
            Order.kind.in_(wallet.BONUS_KINDS)).all())
        total_rewarded = wins + bonus
        pending_dep = s.query(Order).filter(Order.kind == "deposit", Order.status == "pending").count()
        pending_wdr = s.query(Order).filter(Order.kind == "withdraw", Order.status == "pending").count()
        recent = s.query(Order).order_by(Order.created_at.desc()).limit(10).all()
        # weekly deposits for the mini bar chart
        from datetime import datetime, timedelta
        today = datetime.utcnow().date()
        week = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            nxt = day + timedelta(days=1)
            d0, d1 = datetime.combine(day, datetime.min.time()), datetime.combine(nxt, datetime.min.time())
            total = sum((o.amount or 0) for o in s.query(Order).filter(
                Order.kind == "deposit", Order.status == "approved",
                Order.created_at >= d0, Order.created_at < d1).all())
            week.append({"label": day.strftime("%a"), "total": round(total, 2)})
        maxw = max([w["total"] for w in week] + [1])
        game_stats = {}
        for g in ("rank", "mvp", "herole"):
            bets = s.query(Bet).filter(Bet.game == g).count()
            paid = sum(b.payout or 0 for b in s.query(Bet).filter(Bet.game == g, Bet.status == "won").all())
            game_stats[g] = {"bets": bets, "paid": round(paid, 2)}
        return tpl(request, "dashboard.html", {
            "stats": {
                "users": users, "deposits": round(total_deposit, 2),
                "withdrawals": round(total_withdraw, 2), "rewarded": round(total_rewarded, 2),
                "pending_dep": pending_dep, "pending_wdr": pending_wdr,
            },
            "week": week, "maxw": maxw, "recent": recent, "game_stats": game_stats,
        })
    finally:
        s.close()


# ----------------------------------------------------------------- users --
@router.get("/users")
async def users(request: Request, q: str = "", page: int = 1):
    s = _db()
    try:
        size = 50
        query = s.query(User)
        if q:
            q = q.strip()
            if q.isdigit():
                query = query.filter(User.tg_id == int(q))
            else:
                like = f"%{q}%"
                query = query.filter(User.tg_fullname.like(like) | User.tg_username.like(like))
        total = query.count()
        pages = max(1, (total + size - 1) // size)
        rows = query.order_by(User.joined_at.desc()).offset((page - 1) * size).limit(size).all()
        enriched = []
        for u in rows:
            d = u.to_dict(include_private=True)
            d["rank"] = rank_for(u)
            enriched.append(d)
        return tpl(request, "users.html", {"users": enriched, "q": q, "page": page,
                                           "pages": pages, "total": total, "ranks": RANKS})
    finally:
        s.close()


@router.post("/users/action")
async def user_action(request: Request):
    body = await request.json()
    tg_id = int(body.get("tg_id", 0))
    action = body.get("action", "")
    title = body.get("title", "")
    remark = body.get("remark", "")
    amount = float(body.get("amount", 0) or 0)
    s = _db()
    try:
        target = wallet.user_by_id(s, tg_id)
        if not target:
            return {"ok": False, "error": "User not found"}
        if action in ("unsuspend",) and not target.is_suspended:
            return {"ok": False, "error": "User is not suspended"}
        ok, err = wallet.admin_user_action(s, target, action, title, remark, amount, admin="Panel")
        return {"ok": ok, "error": err or ""}
    finally:
        s.close()


@router.post("/users/bind")
async def user_bind(request: Request):
    body = await request.json()
    tg_id = int(body.get("tg_id", 0))
    s = _db()
    try:
        target = wallet.user_by_id(s, tg_id)
        if not target:
            return {"ok": False, "error": "User not found"}
        ok, err = wallet.admin_set_bind(s, target, "Panel",
                                        str(body.get("bind_name", "")),
                                        str(body.get("bind_account", "")),
                                        str(body.get("bind_holder", "") or ""))
        return {"ok": ok, "error": err or ""}
    finally:
        s.close()


@router.post("/rankbonus/save")
async def rankbonus_save(request: Request):
    """Per-rank reach bonuses, editable by admins."""
    body = await request.json()
    s = _db()
    try:
        cur = dict(get_setting(s, "rank_bonus", {}))
        for r in RANKS:
            key = r["key"]
            try:
                cur[key] = float(body.get(key, cur.get(key, 0)))
            except Exception:
                pass
        set_setting(s, "rank_bonus", cur)
        return {"ok": True}
    finally:
        s.close()


# ------------------------------------------------------------ approvals --
@router.get("/deposits")
async def deposits(request: Request, status: str = "pending"):
    return await _approvals(request, "deposit", status)


@router.get("/withdrawals")
async def withdrawals(request: Request, status: str = "pending"):
    return await _approvals(request, "withdraw", status)


async def _approvals(request: Request, kind: str, status: str):
    s = _db()
    try:
        q = s.query(Order).filter(Order.kind == kind)
        if status in ("pending", "approved", "rejected"):
            q = q.filter(Order.status == status)
        rows = q.order_by(Order.created_at.desc()).limit(100).all()
        items = []
        for o in rows:
            d = o.to_dict()
            u = s.get(User, o.user_id)
            d["user"] = {
                "tg_id": u.tg_id if u else 0, "fullname": u.tg_fullname if u else "",
                "username": u.tg_username if u else "", "balance": u.balance if u else 0,
            }
            try:
                d["detail_obj"] = json.loads(o.detail or "{}")
            except Exception:
                d["detail_obj"] = {}
            items.append(d)
        return tpl(request, "approvals.html", {"kind": kind, "status": status, "rows": items})
    finally:
        s.close()


@router.post("/order/action")
async def order_action(request: Request):
    body = await request.json()
    oid = int(body.get("order_id", 0))
    action = body.get("action", "")
    remark = body.get("remark", "") or ""
    s = _db()
    try:
        order = s.get(Order, oid)
        if not order:
            return {"ok": False, "error": "Order not found"}
        if order.status != "pending":
            return {"ok": False, "error": f"Already {order.status}"}
        if action == "approve":
            if order.kind == "deposit":
                wallet.approve_deposit(s, order, admin_label="Panel", remark=remark)
            else:
                wallet.approve_withdraw(s, order, admin_label="Panel", remark=remark)
        elif action in ("reject", "reject_ban"):
            ban = action == "reject_ban"
            if order.kind == "deposit":
                wallet.reject_deposit(s, order, admin_label="Panel", remark=remark, ban=ban)
            else:
                wallet.reject_withdraw(s, order, admin_label="Panel", remark=remark, ban=ban)
        else:
            return {"ok": False, "error": "Unknown action"}
        return {"ok": True}
    finally:
        s.close()


# ---------------------------------------------------------- promotions --
@router.get("/promotions")
async def promotions(request: Request):
    s = _db()
    try:
        ps = s.query(Promotion).order_by(Promotion.created_at.desc()).all()
        codes = s.query(Promo).order_by(Promo.created_at.desc()).all()
        return tpl(request, "promotions.html", {"promotions": ps, "promos": codes})
    finally:
        s.close()


@router.post("/promotions/add")
async def promo_add(request: Request):
    form = await request.form()
    s = _db()
    try:
        p = Promotion(title=str(form.get("title", "")),
                      text=str(form.get("text", "")),
                      url=str(form.get("url", "")),
                      active=str(form.get("active", "0")) == "1")
        p.image_path = _save_upload(form.get("image"), "promo")
        s.add(p)
        s.commit()
        return RedirectResponse("/admin/promotions", status_code=302)
    finally:
        s.close()


@router.post("/promotions/toggle")
async def promo_toggle(request: Request):
    body = await request.json()
    s = _db()
    try:
        p = s.get(Promotion, int(body.get("id", 0)))
        if p:
            p.active = not p.active
            s.commit()
        return {"ok": True}
    finally:
        s.close()


@router.post("/promotions/delete")
async def promo_delete(request: Request):
    body = await request.json()
    s = _db()
    try:
        p = s.get(Promotion, int(body.get("id", 0)))
        if p:
            s.delete(p)
            s.commit()
        return {"ok": True}
    finally:
        s.close()


@router.post("/promos/add")
async def code_add(request: Request):
    from datetime import datetime
    form = await request.form()
    s = _db()
    try:
        expires = None
        e = str(form.get("expires", "") or "")
        if e:
            try:
                expires = datetime.strptime(e, "%Y-%m-%d")
            except Exception:
                expires = None
        code = str(form.get("code", "")).strip().upper()
        if not code:
            return RedirectResponse("/admin/promotions", status_code=302)
        p = Promo(code=code, title=str(form.get("title", "")),
                  amount=float(form.get("amount", 0) or 0),
                  uses_max=int(form.get("uses_max", 0) or 0),
                  expires_at=expires, active=True)
        s.add(p)
        s.commit()
        return RedirectResponse("/admin/promotions", status_code=302)
    finally:
        s.close()


@router.post("/promos/toggle")
async def code_toggle(request: Request):
    body = await request.json()
    s = _db()
    try:
        p = s.get(Promo, int(body.get("id", 0)))
        if p:
            p.active = not p.active
            s.commit()
        return {"ok": True}
    finally:
        s.close()


@router.post("/promos/delete")
async def code_delete(request: Request):
    body = await request.json()
    s = _db()
    try:
        p = s.get(Promo, int(body.get("id", 0)))
        if p:
            s.delete(p)
            s.commit()
        return {"ok": True}
    finally:
        s.close()


# ----------------------------------------------------------------- games --
@router.get("/games")
async def games(request: Request):
    s = _db()
    try:
        winrate = get_setting(s, "winrate", {})
        rank_bonus = get_setting(s, "rank_bonus", {})
        overrides = s.query(User).filter(User.winrate_override.isnot(None)).all()
        stats = {}
        for g in ("rank", "mvp", "herole"):
            bets = s.query(Bet).filter(Bet.game == g).count()
            won = s.query(Bet).filter(Bet.game == g, Bet.status == "won").count()
            paid = sum(b.payout or 0 for b in s.query(Bet).filter(Bet.game == g, Bet.status == "won").all())
            taken = sum(b.amount or 0 for b in s.query(Bet).filter(Bet.game == g).all())
            stats[g] = {"bets": bets, "won": won, "paid": round(paid, 2), "taken": round(taken, 2)}
        return tpl(request, "games.html", {"winrate": winrate, "rank_bonus": rank_bonus,
                                           "stats": stats,
                                           "overrides": overrides, "ranks": RANKS})
    finally:
        s.close()


@router.post("/winrate/save")
async def winrate_save(request: Request):
    body = await request.json()
    s = _db()
    try:
        cur = dict(get_setting(s, "winrate", {}))
        for g in ("rank", "mvp", "herole"):
            cur[g] = max(0.0, min(1.0, float(body.get(g, cur.get(g, 0.3)))))
        set_setting(s, "winrate", cur)
        return {"ok": True}
    finally:
        s.close()


@router.post("/winrate/user")
async def winrate_user(request: Request):
    body = await request.json()
    s = _db()
    try:
        u = wallet.user_by_id(s, int(body.get("tg_id", 0)))
        if not u:
            return {"ok": False, "error": "User not found"}
        game = body.get("game", "rank")
        rate = float(body.get("rate", 0.3))
        set_winrate_override(s, u, game, rate)
        return {"ok": True}
    finally:
        s.close()


@router.post("/winrate/user/remove")
async def winrate_user_remove(request: Request):
    body = await request.json()
    s = _db()
    try:
        u = wallet.user_by_id(s, int(body.get("tg_id", 0)))
        if u:
            u.winrate_override = None
            s.commit()
        return {"ok": True}
    finally:
        s.close()


# -------------------------------------------------------------- rankings --
@router.get("/rankings")
async def rankings(request: Request, tab: str = "balance"):
    s = _db()
    try:
        keys = {"balance": User.balance, "referral": User.referral_balance,
                "bets": User.valid_bets, "deposits": User.total_deposit}
        col = keys.get(tab, User.balance)
        rows = s.query(User).order_by(col.desc()).limit(20).all()
        items = []
        for i, u in enumerate(rows, 1):
            d = u.to_dict()
            d["rank_name"] = rank_for(u)["name"]
            d["pos"] = i
            items.append(d)
        return tpl(request, "rankings.html", {"tab": tab, "rows": items})
    finally:
        s.close()


# -------------------------------------------------------------- broadcast --
@router.get("/broadcast")
async def broadcast(request: Request):
    s = _db()
    try:
        jobs = s.query(BroadcastJob).order_by(BroadcastJob.created_at.desc()).limit(20).all()
        return tpl(request, "broadcast.html", {"jobs": jobs, "ranks": RANKS})
    finally:
        s.close()


@router.post("/broadcast/send")
async def broadcast_send(request: Request):
    form = await request.form()
    s = _db()
    try:
        job = BroadcastJob(
            text=str(form.get("text", "")),
            button_text=str(form.get("button_text", "")),
            button_url=str(form.get("button_url", "")),
            target_rank=str(form.get("target_rank", "") or ""),
        )
        job.image_path = _save_upload(form.get("image"), "broadcast")
        s.add(job)
        s.commit()
        return RedirectResponse("/admin/broadcast", status_code=302)
    finally:
        s.close()


@router.post("/broadcast/cancel")
async def broadcast_cancel(request: Request):
    body = await request.json()
    s = _db()
    try:
        job = s.get(BroadcastJob, int(body.get("id", 0)))
        if job and job.status in ("pending", "running"):
            job.status = "cancelled"
            s.commit()
        return {"ok": True}
    finally:
        s.close()


# ------------------------------------------------------------ customize --
@router.get("/customize")
async def customize(request: Request):
    s = _db()
    try:
        return tpl(request, "customize.html", {"settings": get_all_settings(s)})
    finally:
        s.close()


@router.post("/customize/general")
async def customize_general(request: Request):
    form = await request.form()
    s = _db()
    try:
        token = str(form.get("bot_token", "")).strip()
        if token:
            set_setting(s, "bot_token", token)
        set_setting(s, "webapp_url", str(form.get("webapp_url", "")).strip())
        set_setting(s, "welcome_text", str(form.get("welcome_text", "")).strip())
        try:
            set_setting(s, "referral_pct", float(form.get("referral_pct", 5)))
        except Exception:
            pass
        try:
            set_setting(s, "daily_bonus", float(form.get("daily_bonus", 2)))
        except Exception:
            pass
        set_setting(s, "maintenance", str(form.get("maintenance", "0")) == "1")
        logo = form.get("logo")
        if logo and logo.filename:
            logo_path = _save_upload(logo, "logo")
            set_setting(s, "logo_path", logo_path)
        media = form.get("welcome_media")
        if media and media.filename:
            path = _save_upload(media, "promo")
            # keep an absolute path for the bot to read
            abs_path = os.path.join(UPLOADS_DIR, "promo", os.path.basename(path))
            set_setting(s, "welcome_media_path", abs_path)
        if str(form.get("reset_welcome", "0")) == "1":
            set_setting(s, "welcome_media_path", "")
        return RedirectResponse("/admin/customize", status_code=302)
    finally:
        s.close()


@router.post("/customize/channels")
async def customize_channels(request: Request):
    form = await request.form()
    s = _db()
    try:
        set_setting(s, "game_channel", str(form.get("game_channel", "")).strip())
        set_setting(s, "tx_group", str(form.get("tx_group", "")).strip())
        set_setting(s, "action_group", str(form.get("action_group", "")).strip())
        return RedirectResponse("/admin/customize?tab=channels", status_code=302)
    finally:
        s.close()


@router.post("/customize/csr")
async def customize_csr(request: Request):
    form = await request.form()
    s = _db()
    try:
        set_setting(s, "csr_group", str(form.get("csr_group", "")).strip())
        set_setting(s, "csr_channel", str(form.get("csr_channel", "")).strip())
        set_setting(s, "csr1", str(form.get("csr1", "")).strip())
        set_setting(s, "csr2", str(form.get("csr2", "")).strip())
        set_setting(s, "csr3", str(form.get("csr3", "")).strip())
        return RedirectResponse("/admin/customize?tab=csr", status_code=302)
    finally:
        s.close()


@router.post("/customize/admins")
async def customize_admins(request: Request):
    form = await request.form()
    s = _db()
    try:
        raw = str(form.get("admin_ids", ""))
        ids = []
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit() and part not in ids and len(ids) < 10:
                ids.append(int(part))
        set_setting(s, "admin_ids", ids)
        return RedirectResponse("/admin/customize?tab=admins", status_code=302)
    finally:
        s.close()


# ----------------------------------------------------------------- heroes --
@router.get("/heroes")
async def heroes(request: Request):
    s = _db()
    try:
        hs = s.query(Hero).order_by(Hero.role.asc(), Hero.name.asc()).all()
        return tpl(request, "heroes.html", {"heroes": hs})
    finally:
        s.close()


@router.post("/heroes/add")
async def heroes_add(request: Request):
    form = await request.form()
    s = _db()
    try:
        from app.heroes import slugify
        name = str(form.get("name", "")).strip()[:80]
        if not name:
            return RedirectResponse("/admin/heroes", status_code=302)
        key = slugify(name)
        exists = s.query(Hero).filter(Hero.key == key).first()
        if exists:
            key = f"{key}-{int(__import__('time').time())}"
        h = Hero(
            key=key, name=name,
            title=str(form.get("title", ""))[:120] or "New Challenger",
            role=str(form.get("role", "fighter")) or "fighter",
            emoji=str(form.get("emoji", "⚔️"))[:8],
            color1=str(form.get("color1", "#7C3AED")) or "#7C3AED",
            color2=str(form.get("color2", "#1E1B4B")) or "#1E1B4B",
            hp=int(form.get("hp", 800) or 800),
            atk=int(form.get("atk", 120) or 120),
            spd=int(form.get("spd", 70) or 70),
            active=True,
        )
        img = form.get("image")
        if img and img.filename:
            h.image_path = _save_upload(img, "heroes")
        s.add(h)
        s.commit()
        return RedirectResponse("/admin/heroes", status_code=302)
    finally:
        s.close()


@router.post("/heroes/save")
async def heroes_save(request: Request):
    form = await request.form()
    s = _db()
    try:
        hid = int(form.get("id", 0))
        h = s.get(Hero, hid)
        if not h:
            return RedirectResponse("/admin/heroes", status_code=302)
        h.name = str(form.get("name", h.name))[:80]
        h.title = str(form.get("title", h.title))[:120]
        h.role = str(form.get("role", h.role))
        h.emoji = str(form.get("emoji", h.emoji))[:8]
        h.color1 = str(form.get("color1", h.color1))
        h.color2 = str(form.get("color2", h.color2))
        h.hp = int(form.get("hp", h.hp) or h.hp)
        h.atk = int(form.get("atk", h.atk) or h.atk)
        h.spd = int(form.get("spd", h.spd) or h.spd)
        h.active = str(form.get("active", "1")) == "1"
        img = form.get("image")
        if img and img.filename:
            path = _save_upload(img, "heroes")
            h.image_path = path
        if str(form.get("reset_image", "0")) == "1":
            h.image_path = None
        s.commit()
        return RedirectResponse("/admin/heroes", status_code=302)
    finally:
        s.close()


# --------------------------------------------------------------- payments --
@router.get("/payments")
async def payments(request: Request):
    s = _db()
    try:
        dep = s.query(DepositMethod).order_by(DepositMethod.sort.asc()).all()
        wdr = s.query(WithdrawChannel).order_by(WithdrawChannel.sort.asc()).all()
        return tpl(request, "payments.html", {"methods": dep, "channels": wdr})
    finally:
        s.close()


@router.post("/payments/method")
async def payment_method(request: Request):
    form = await request.form()
    s = _db()
    try:
        mid = int(form.get("id", 0) or 0)
        m = s.get(DepositMethod, mid) if mid else DepositMethod()
        if not m:
            m = DepositMethod()
        m.name = str(form.get("name", ""))
        m.detail = str(form.get("detail", ""))
        m.min_amount = float(form.get("min", 1) or 1)
        m.max_amount = float(form.get("max", 50000) or 50000)
        m.active = str(form.get("active", "1")) == "1"
        img = form.get("image")
        if img and img.filename:
            m.image_path = _save_upload(img, "promo")
        s.add(m)
        s.commit()
        return RedirectResponse("/admin/payments", status_code=302)
    finally:
        s.close()


@router.post("/payments/channel")
async def payment_channel(request: Request):
    form = await request.form()
    s = _db()
    try:
        cid = int(form.get("id", 0) or 0)
        c = s.get(WithdrawChannel, cid) if cid else WithdrawChannel()
        if not c:
            c = WithdrawChannel()
        c.name = str(form.get("name", ""))
        c.min_amount = float(form.get("min", 1) or 1)
        c.max_amount = float(form.get("max", 50000) or 50000)
        c.active = str(form.get("active", "1")) == "1"
        raw_fields = str(form.get("fields", "[]"))
        try:
            fields = json.loads(raw_fields)
            assert isinstance(fields, list)
            c.fields = json.dumps(fields, ensure_ascii=False)
        except Exception:
            c.fields = "[]"
        s.add(c)
        s.commit()
        return RedirectResponse("/admin/payments", status_code=302)
    finally:
        s.close()


@router.post("/payments/toggle")
async def payment_toggle(request: Request):
    body = await request.json()
    s = _db()
    try:
        kind, pid = body.get("kind", ""), int(body.get("id", 0))
        if kind == "method":
            m = s.get(DepositMethod, pid)
            if m:
                m.active = not m.active
        else:
            c = s.get(WithdrawChannel, pid)
            if c:
                c.active = not c.active
        s.commit()
        return {"ok": True}
    finally:
        s.close()


@router.post("/payments/delete")
async def payment_delete(request: Request):
    body = await request.json()
    s = _db()
    try:
        kind, pid = body.get("kind", ""), int(body.get("id", 0))
        if kind == "method":
            m = s.get(DepositMethod, pid)
            if m:
                s.delete(m)
        else:
            c = s.get(WithdrawChannel, pid)
            if c:
                s.delete(c)
        s.commit()
        return {"ok": True}
    finally:
        s.close()


# ------------------------------------------------------------------- logs --
@router.get("/logs")
async def logs(request: Request):
    s = _db()
    try:
        rows = s.query(ActionLog).order_by(ActionLog.created_at.desc()).limit(200).all()
        return tpl(request, "logs.html", {"rows": rows})
    finally:
        s.close()