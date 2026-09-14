"""Mini App (Telegram WebApp) API — user-side: me/deposit/withdraw/promo/history/promotions/leaderboard."""
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import wallet
from app.config import DEBUG_WEBAPP_DEV, UPLOADS_DIR
from app.db import get_session
from app.models import Bet, Order, Promotion, User
from app.ranks import RANK_EMOJI, daily_bets_left, rank_for
from app.settings_svc import effective_webapp_url, get_setting

router = APIRouter(prefix="/miniapp", tags=["miniapp"])

AUTH_HEADER = "x-init-data"
DEV_UID_HEADER = "x-dev-uid"


def _validate_init_data(init_data: str, token: str) -> dict | None:
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received_hash = data.get("hash", "")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs) if k != "hash")
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, received_hash):
            return None
        user = data.get("user")
        return json.loads(user) if user else None
    except Exception:
        return None


def _resolve_user(request: Request):
    """Returns (user, error_response_or_None)."""
    sess = get_session()
    try:
        init_data = request.headers.get(AUTH_HEADER, "")
        token = str(get_setting(sess, "bot_token", "") or "")
        if init_data:
            tg_user = _validate_init_data(init_data, token) if token else None
            if tg_user is None and token:
                return None, JSONResponse({"ok": False, "error": "AUTH_FAILED"}, status_code=401)
            if tg_user is None and DEBUG_WEBAPP_DEV:
                dev_uid = request.headers.get(DEV_UID_HEADER, "")
                tg_user = {"id": int(dev_uid), "first_name": "Dev", "last_name": "", "username": "dev"} if dev_uid.isdigit() else None
                if tg_user is None:
                    return None, JSONResponse({"ok": False, "error": "DEV_UID_REQUIRED"}, status_code=401)
        else:
            dev_uid = request.headers.get(DEV_UID_HEADER, "")
            if not (DEBUG_WEBAPP_DEV and dev_uid.isdigit()):
                return None, JSONResponse({"ok": False, "error": "AUTH_FAILED"}, status_code=401)
            tg_user = {"id": int(dev_uid), "first_name": "Dev", "last_name": "", "username": "dev"}
        if not tg_user:
            return None, JSONResponse({"ok": False, "error": "AUTH_FAILED"}, status_code=401)
        fullname = " ".join(x for x in [tg_user.get("first_name", ""), tg_user.get("last_name", "")] if x)
        user = wallet.get_or_create_user(sess, int(tg_user["id"]),
                                         tg_username=tg_user.get("username", "") or "",
                                         tg_fullname=fullname)
        return user, None
    finally:
        sess.close()


def _me_payload(sess, user: User) -> dict:
    rank = rank_for(user)
    return {
        "ok": True,
        "user": {
            "tg_id": user.tg_id,
            "fullname": user.tg_fullname or f"Player {user.tg_id}",
            "username": user.tg_username or "",
            "balance": round(user.balance or 0, 2),
            "referral_balance": round(user.referral_balance or 0, 2),
            "total_rewards": round(user.total_rewards or 0, 2),
            "total_deposit": round(user.total_deposit or 0, 2),
            "total_withdraw": round(user.total_withdraw or 0, 2),
            "turnover": round(user.turnover or 0, 2),
            "valid_bets": user.valid_bets or 0,
            "joined": user.joined_at.strftime("%Y-%m-%d") if user.joined_at else "-",
            "is_banned": user.is_banned,
            "is_suspended": user.is_suspended,
            "frozen": user.balance_frozen,
        },
        "rank": {
            "key": rank["key"], "name": rank["name"], "tier": rank["tier"],
            "emoji": RANK_EMOJI.get(rank["key"], ""),
            "max_bet": rank["max_bet"],
            "daily_left": daily_bets_left(user),
        },
        "maintenance": bool(get_setting(sess, "maintenance", False)),
        "bot_name": get_setting(sess, "bot_name", "MLPlay"),
    }


@router.get("/me")
async def me(request: Request):
    user, err = _resolve_user(request)
    if err:
        return err
    sess = get_session()
    try:
        return _me_payload(sess, user)
    finally:
        sess.close()


@router.get("/deposit-methods")
async def deposit_methods(request: Request):
    user, err = _resolve_user(request)
    if err:
        return err
    from app.models import DepositMethod
    sess = get_session()
    try:
        methods = sess.query(DepositMethod).filter(DepositMethod.active.is_(True)) \
            .order_by(DepositMethod.sort.asc()).all()
        return {"ok": True, "methods": [
            {"id": m.id, "name": m.name, "min": m.min_amount, "max": m.max_amount,
             "qr": f"/media/qr/{m.id}.png", "image": m.image_path or "",
             "detail": (m.detail or "")[:80]}
            for m in methods]}
    finally:
        sess.close()


@router.post("/deposit")
async def deposit(request: Request):
    user, err = _resolve_user(request)
    if err:
        return err
    if user.is_banned or user.is_suspended:
        return JSONResponse({"ok": False, "error": "Your account is restricted."}, status_code=403)
    sess0 = get_session()
    try:
        maintenance = get_setting(sess0, "maintenance", False)
    finally:
        sess0.close()
    if maintenance:
        return JSONResponse({"ok": False, "error": "Deposits temporarily paused."}, status_code=403)
    body = await request.json()
    amount = float(body.get("amount", 0))
    method_id = int(body.get("method_id", 0))
    receipt_b64 = str(body.get("receipt", "") or "")
    receipt_path = None
    if receipt_b64:
        try:
            raw = base64.b64decode(receipt_b64.split(",")[-1])
            fname = f"receipt_{user.tg_id}_{datetime.utcnow():%Y%m%d%H%M%S}.png"
            os.makedirs(os.path.join(UPLOADS_DIR, "receipts"), exist_ok=True)
            path = os.path.join(UPLOADS_DIR, "receipts", fname)
            with open(path, "wb") as f:
                f.write(raw)
            receipt_path = f"/media/receipts/{fname}"
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid receipt image."}, status_code=400)
    sess = get_session()
    try:
        order, err_text = wallet.submit_deposit(sess, user, method_id, amount, receipt_path)
        if err_text:
            return JSONResponse({"ok": False, "error": err_text}, status_code=400)
        return {"ok": True, "order_no": order.order_no, "status": "pending"}
    finally:
        sess.close()


@router.get("/withdraw-channels")
async def withdraw_channels(request: Request):
    user, err = _resolve_user(request)
    if err:
        return err
    sess = get_session()
    try:
        # withdrawals go ONLY to the user's permanently bound wallet/bank
        if not user.bind_account:
            return {"ok": True, "bound": False,
                    "channels": [], "hint": "Bind your wallet/bank first (open the bot → Profile → 🏦 Bind Wallet/Bank) — one-time setup, +₱30 bonus!"}
        mask = (user.bind_account[:4] + "••••" + user.bind_account[-4:]) if len(user.bind_account or "") > 8 else user.bind_account
        return {"ok": True, "bound": True, "binding": {
                    "wallet": user.bind_name or "Bound wallet",
                    "account": user.bind_account or "",
                    "account_masked": mask,
                    "holder": user.bind_holder or "", },
                "channels": []}
    finally:
        sess.close()


@router.post("/withdraw")
async def withdraw(request: Request):
    user, err = _resolve_user(request)
    if err:
        return err
    if user.is_banned or user.is_suspended or user.balance_frozen:
        return JSONResponse({"ok": False, "error": "Your account is restricted."}, status_code=403)
    if not user.bind_account:
        return JSONResponse({"ok": False, "error": "Bind your wallet first — open the bot → Profile → 🏦 Bind Wallet/Bank (one-time, +₱30)."}, status_code=403)
    body = await request.json()
    amount = float(body.get("amount", 0))
    channel_id = int(body.get("channel_id", 0) or 0)
    sess = get_session()
    try:
        order, err_text = wallet.submit_withdraw(sess, user, channel_id, amount)
        if err_text:
            return JSONResponse({"ok": False, "error": err_text}, status_code=400)
        return {"ok": True, "order_no": order.order_no, "status": "pending"}
    finally:
        sess.close()


@router.post("/promo")
async def promo(request: Request):
    user, err = _resolve_user(request)
    if err:
        return err
    body = await request.json()
    code = str(body.get("code", "") or "")
    sess = get_session()
    try:
        amt, err_text = wallet.redeem_promo(sess, user, code)
        if err_text:
            return JSONResponse({"ok": False, "error": err_text}, status_code=400)
        return {"ok": True, "amount": amt}
    finally:
        sess.close()


@router.get("/history")
async def history(request: Request, kind: str = "all", limit: int = 50):
    user, err = _resolve_user(request)
    if err:
        return err
    sess = get_session()
    try:
        rows = []
        if kind in ("all", "deposit", "withdraw", "reward"):
            q = sess.query(Order).filter(Order.user_id == user.id)
            if kind == "deposit":
                q = q.filter(Order.kind == "deposit")
            elif kind == "withdraw":
                q = q.filter(Order.kind == "withdraw")
            elif kind == "reward":
                q = q.filter(Order.kind.in_(wallet.BONUS_KINDS))
            for o in q.order_by(Order.created_at.desc()).limit(limit).all():
                rows.append({
                    "id": o.order_no, "kind": o.kind, "amount": round(o.amount or 0, 2),
                    "direction": o.direction, "status": o.status, "title": o.title,
                    "time": o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
                    "remark": o.remark or "",
                })
        if kind in ("all", "bet"):
            q = sess.query(Bet).filter(Bet.user_id == user.id, Bet.status.in_(["won", "lost"]))
            if kind == "bet":
                q = q.filter(Bet.status.in_(["won", "lost"]))
            for b in q.order_by(Bet.created_at.desc()).limit(limit if kind == "bet" else 25).all():
                rows.append({
                    "id": b.order_no, "kind": "bet", "amount": -abs(b.amount or 0),
                    "direction": "out", "status": b.status, "title": f"{b.game} bet",
                    "time": b.created_at.strftime("%Y-%m-%d %H:%M") if b.created_at else "",
                    "remark": f"Match #{b.match_id}" if b.match_id else b.pick,
                })
        rows.sort(key=lambda x: x["time"], reverse=True)
        return {"ok": True, "rows": rows[:limit]}
    finally:
        sess.close()


@router.get("/promotions")
async def promotions(request: Request):
    user, err = _resolve_user(request)
    if err:
        return err
    sess = get_session()
    try:
        ps = sess.query(Promotion).filter(Promotion.active.is_(True)) \
            .order_by(Promotion.created_at.desc()).all()
        return {"ok": True, "promotions": [
            {"id": p.id, "title": p.title, "text": p.text, "image": p.image_path or "",
             "url": p.url or ""}
            for p in ps]}
    finally:
        sess.close()


@router.get("/leaderboard")
async def leaderboard(request: Request, by: str = "balance"):
    user, err = _resolve_user(request)
    if err:
        return err
    sess = get_session()
    try:
        key = {"balance": User.balance, "turnover": User.turnover,
               "deposit": User.total_deposit, "bets": User.valid_bets}.get(by, User.balance)
        top = sess.query(User).order_by(key.desc()).limit(10).all()
        rank_map = {u.tg_id: rank_for(u) for u in top}
        return {"ok": True, "rows": [
            {"tg_id": u.tg_id, "name": u.tg_fullname or f"@{u.tg_username}" or f"ID {u.tg_id}",
             "value": round(getattr(u, by, 0) or 0, 2), "rank": rank_map[u.tg_id]["name"]}
            for u in top]}
    finally:
        sess.close()