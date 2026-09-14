"""
Wallet & administration engine — all money movement, request approvals,
promo codes, referral rewards, rank-up notifications, user actions.
Every function is sync (SQLAlchemy) and pushes Telegram notifications
through the async notifier bridge, so both the bot and the web admin
panel use exactly the same logic.
"""
import json
import logging
import random
from datetime import date, datetime

from app.db import SessionLocal
from app.heroes import GAME_MULTIPLIERS, hero_by_key
from app.models import ActionLog, Bet, Order, User, WithdrawChannel
from app.notifier import esc, kb, resolve_target, send_photo, send_text
from app.ranks import RANK_EMOJI, daily_bets_left, daily_limit, rank_for, can_play
from app.settings_svc import get_setting, is_admin_tg, set_setting, winrate_for

logger = logging.getLogger("wallet")

GAME_LABEL = {"rank": "⚔️ Rank Game", "mvp": "🏆 Who's The MVP?", "herole": "🎭 HeRole"}
GAME_EMOJI = {"rank": "⚔️", "mvp": "🏆", "herole": "🎭"}

# order kinds counted as "rewards / bonus sources"
BONUS_KINDS = ["promo", "daily", "referral", "convert", "reward", "bind", "rank"]


def mk_no(prefix: str) -> str:
    import random as r
    return f"{prefix}-{datetime.utcnow().strftime('%y%m%d')}-{r.randint(100000, 999999)}"


# ------------------------------------------------------------------ users --
def get_or_create_user(session, tg_id: int, chat_id: int = 0, tg_username: str = "",
                       tg_fullname: str = "") -> User:
    u = session.query(User).filter(User.tg_id == tg_id).first()
    if u:
        upd = False
        if chat_id and u.chat_id != chat_id:
            u.chat_id = chat_id
            upd = True
        if tg_username is not None and u.tg_username != tg_username:
            u.tg_username = tg_username
            upd = True
        if tg_fullname and u.tg_fullname != tg_fullname:
            u.tg_fullname = tg_fullname
            upd = True
        if upd:
            session.commit()
        return u
    u = User(tg_id=tg_id, chat_id=chat_id, tg_username=tg_username or "",
             tg_fullname=tg_fullname or "")
    session.add(u)
    session.commit()
    return u


def user_by_id(session, tg_id: int) -> User | None:
    return session.query(User).filter(User.tg_id == tg_id).first()


def _invite_stats(session, user: User):
    invited = session.query(User).filter(User.inviter_tg_id == user.tg_id).all()
    valid = [x for x in invited if (x.total_deposit or 0) > 0]
    return len(invited), len(valid)


def top_referrers(session, n=5):
    rows = session.query(User).filter(User.inviter_tg_id.isnot(None)) \
        .with_entities(User.inviter_tg_id) \
        .group_by(User.inviter_tg_id).all()
    out = []
    for (inviter_id,) in rows[:40]:
        inviter = user_by_id(session, inviter_id)
        if not inviter:
            continue
        income = session.query(User).filter(User.inviter_tg_id == inviter_id,
                                            User.total_deposit > 0).count()
        reward = 0.0
        for o in session.query(Order).filter(Order.kind == "referral",
                                             Order.user_id == inviter.id).all():
            reward += o.amount or 0
        name = inviter.tg_fullname or f"@{inviter.tg_username}" or f"ID {inviter_id}"
        out.append((name, reward, income))
    out.sort(key=lambda x: -x[1])
    return out[:n]


# -------------------------------------------------------------- betting ----
def effective_winrate(session, user, game: str) -> float:
    return winrate_for(session, user, game)


def place_bet(session, user: User, game: str, amount: float, match_id, pick) -> tuple[Bet | None, str | None]:
    """Freeze balance, roll the result (seeded at placement), create pending Bet."""
    amt = round(float(amount), 2)
    rank = rank_for(user)

    if not can_play(user, game):
        return None, f"🔒 Your rank **{rank['name']}** can't play {GAME_LABEL[game]} yet. Rank up!"
    if amt < 1:
        return None, "⚠️ Minimum bet is **₱1.00**."
    if amt > rank["max_bet"]:
        return None, f"⚠️ Your rank allows max **₱{rank['max_bet']:,.2f}** per bet."
    lim = daily_limit(user)
    left = daily_bets_left(user)
    if lim is not None and left is not None and left <= 0:
        return None, f"⏳ Daily bet limit reached (**{lim}**). Come back tomorrow, champion!"
    if user.balance_frozen:
        return None, "⛔ Your balance is frozen — contact support."
    if (user.balance or 0) < amt:
        return None, "💰 Insufficient balance. Deposit to keep playing!"

    pending = session.query(Bet).filter(Bet.user_id == user.id, Bet.status == "pending").first()
    if pending:
        return None, f"⏳ You have a pending bet (`{pending.order_no}`) — wait for the result!"

    if game == "rank":
        dup = session.query(Bet).filter(Bet.user_id == user.id, Bet.match_id == match_id,
                                        Bet.game == "rank").first()
        if dup:
            return None, "🎯 You already bet on this match!"

    wr = effective_winrate(session, user, game)
    won = random.random() < wr
    mult = GAME_MULTIPLIERS[game]

    # compute the *displayed* result so the reveal is deterministic & restart-safe
    hero_key = ""
    if game == "rank":
        hero_key = ""
    elif game == "mvp":
        hero_key = pick if won else _random_other_hero(session, pick)
    else:  # herole
        if won:
            h = _random_hero_of_role(session, pick)
            hero_key = h.key if h else ""
        else:
            h = _random_other_role_hero(session, pick)
            hero_key = h.key if h else ""

    bet = Bet(order_no=mk_no(f"{game.upper()}"),
              user_id=user.id, game=game, match_id=match_id,
              pick=pick, amount=amt, status="pending", winrate=wr,
              outcome=json.dumps({"won": won, "hero_key": hero_key}))
    session.add(bet)

    user.balance = round((user.balance or 0) - amt, 2)
    user.turnover = round((user.turnover or 0) + amt, 2)
    if user.daily_bets_date != date.today():
        user.daily_bets_date = date.today()
        user.daily_bets_used = 0
    user.daily_bets_used = (user.daily_bets_used or 0) + 1
    session.commit()
    session.refresh(bet)
    return bet, None


def _random_other_hero(session, pick):
    from app.heroes import get_hero_pool
    pool = get_hero_pool(session)
    others = [h for h in pool if h.key != pick]
    return random.choice(others) if others else None


def _random_hero_of_role(session, role):
    from app.heroes import get_hero_pool
    pool = get_hero_pool(session, role)
    return random.choice(pool) if pool else None


def _random_other_role_hero(session, picked_role):
    from app.heroes import ROLES, get_hero_pool
    roles = [r for r in ROLES if r != picked_role]
    random.shuffle(roles)
    for r in roles:
        pool = get_hero_pool(session, r)
        if pool:
            return random.choice(pool)
    return None


def settle_bet(session, bet: Bet) -> bool:
    """Settle a pending bet (idempotent). Returns True if newly settled."""
    if bet.status != "pending":
        return False
    try:
        outcome = json.loads(bet.outcome or "{}")
    except Exception:
        outcome = {}
    won = bool(outcome.get("won"))
    bet.status = "won" if won else "lost"
    bet.settled_at = datetime.utcnow()
    if won:
        mult = GAME_MULTIPLIERS.get(bet.game, 2.0)
        bet.payout = round(bet.amount * mult, 2)
        user = session.get(User, bet.user_id)
        user.balance = round((user.balance or 0) + bet.payout, 2)
        order = Order(order_no=mk_no("WIN"), user_id=bet.user_id, kind="win",
                      amount=bet.payout, direction="in", status="completed",
                      title=f"{GAME_LABEL.get(bet.game, bet.game)} win",
                      ref=bet.order_no, detail=json.dumps(outcome))
        session.add(order)
    user = session.get(User, bet.user_id)
    user.valid_bets = (user.valid_bets or 0) + 1
    session.commit()
    maybe_rank_up(session, user)
    _notify_bet_result(session, bet)
    return True


def bet_result_payload(session, bet: Bet) -> dict:
    """Human-readable reveal for the settled bet."""
    outcome = json.loads(bet.outcome or "{}")
    won = outcome.get("won")
    hero_key = outcome.get("hero_key", "")
    hero = hero_by_key(session, hero_key) if hero_key else None
    if bet.game == "rank":
        if won:
            headline = f"🏆 {str(bet.pick).upper()} TEAM WINS!"
            sub = "Your side dominated the battlefield!"
        else:
            other = "🔴 RED" if bet.pick == "blue" else "🔵 BLUE"
            headline = f"{other} TEAM TAKES THE WIN"
            sub = "Tough defeat — revenge time!"
        hero_disp = None
    elif bet.game == "mvp":
        if won and hero:
            headline = f"🏆 MVP: {hero.name}!"
            sub = f"Your pick {hero.name} carried the game!"
        elif hero:
            headline = f"🏆 MVP: {hero.name}"
            sub = f"The spotlight went to {hero.name} this time."
        else:
            headline = "MVP REVEALED"
            sub = ""
        hero_disp = hero
    else:
        if won and hero:
            headline = f"🎭 {hero.name} ({hero.role.title()})!"
            sub = f"Your {bet.pick.title()} pick nailed it!"
        elif hero:
            headline = f"🎭 Result: {hero.name} — {hero.role.title()}"
            sub = f"A {hero.role.title()} took the crown this round."
        else:
            headline = "ROLE REVEALED"
            sub = ""
        hero_disp = hero
    mult = GAME_MULTIPLIERS.get(bet.game, 2.0)
    if won:
        payout = f"+₱{bet.payout:,.2f}  (x{mult:g})"
    else:
        payout = f"-₱{bet.amount:,.2f}"
    extra = {"headline": headline, "sub": sub, "payout": payout, "hero": hero_disp,
             "won": won, "game": bet.game, "order_no": bet.order_no}
    return extra


def _notify_bet_result(session, bet: Bet):
    from app.cards import result_card
    user = session.get(User, bet.user_id)
    if not user or not user.chat_id:
        return
    p = bet_result_payload(session, bet)
    hero = p.get("hero")
    card = result_card(p["headline"], p["sub"], p["payout"],
                       hero=hero.to_dict() if hero else None, win=p["won"])
    caption = (
        f"{p['headline']}\n"
        f"{p['sub']}\n\n"
        f"🎫 Bet: `{bet.order_no}`  •  {GAME_EMOJI.get(bet.game, '')} {GAME_LABEL.get(bet.game, bet.game)}\n"
        f"💵 Bet amount: ₱{bet.amount:,.2f}\n"
        f"{'🎉 ' + 'PAYOUT ' + p['payout'] + '!' if p['won'] else '💔 Better luck next match!'}\n\n"
        f"⚡ New balance: **₱{user.balance:,.2f}**"
    )
    send_photo(user.chat_id, card, caption)


# ------------------------------------------------------------ deposits ----
def submit_deposit(session, user: User, method_id: int, amount: float,
                   receipt_path: str, fields: dict | None = None) -> tuple[Order | None, str | None]:
    from app.models import DepositMethod
    method = session.get(DepositMethod, method_id)
    if not method or not method.active:
        return None, "Payment method not available."
    amt = round(float(amount), 2)
    if amt < (method.min_amount or 1):
        return None, f"Min deposit for this method is ₱{method.min_amount:,.2f}."
    if amt > (method.max_amount or 50000):
        return None, f"Max deposit for this method is ₱{method.max_amount:,.2f}."
    order = Order(order_no=mk_no("DEP"), user_id=user.id, kind="deposit", amount=amt,
                  direction="in", status="pending", title=f"Deposit via {method.name}",
                  detail=json.dumps(fields or {}), receipt_path=receipt_path)
    session.add(order)
    session.commit()
    session.refresh(order)
    _post_tx_request(session, order, f"💰 **New Deposit Request**\n\n"
                                     f"🧑 User: {_user_label(user)}\n"
                                     f"📥 Amount: **₱{amt:,.2f}**\n"
                                     f"💳 Method: {method.name}\n"
                                     f"🎫 Order: `{order.order_no}`\n"
                                     f"🕐 Time: {order.created_at:%Y-%m-%d %H:%M}")
    return order, None


def approve_deposit(session, order: Order, admin_label: str = "", remark: str = ""):
    if order.kind != "deposit" or order.status != "pending":
        return False
    user = session.get(User, order.user_id)
    order.status = "approved"
    order.handled_by = admin_label
    order.handled_at = datetime.utcnow()
    if remark:
        order.remark = remark
    first_deposit = (user.total_deposit or 0) <= 0
    user.balance = round((user.balance or 0) + (order.amount or 0), 2)
    user.total_deposit = round((user.total_deposit or 0) + (order.amount or 0), 2)

    # referral reward on the invitee's FIRST deposit
    bonus_text = ""
    if first_deposit and user.inviter_tg_id:
        inviter = user_by_id(session, user.inviter_tg_id)
        if inviter:
            pct = float(get_setting(session, "referral_pct", 5.0))
            bonus = round((order.amount or 0) * pct / 100.0, 2)
            if bonus > 0:
                inviter.referral_balance = round((inviter.referral_balance or 0) + bonus, 2)
                bonus_order = Order(order_no=mk_no("REF"), user_id=inviter.id, kind="referral",
                                    amount=bonus, direction="in", status="completed",
                                    title=f"Referral reward — {_user_label(user)}'s first deposit",
                                    ref=order.order_no)
                session.add(bonus_order)
                bonus_text = (f"\n\n🤝 Referral bonus **₱{bonus:,.2f}** sent to your inviter!")
                send_text(inviter.chat_id,
                          f"🤝 **REFERRAL BONUS!**\n\n"
                          f"Your invitee made their first deposit! 🎉\n"
                          f"You earned **+₱{bonus:,.2f}** referral rewards!\n"
                          f"🔗 Check your Referral page in the bot.")
    session.commit()
    maybe_rank_up(session, user)
    _post_tx_request(session, order, f"✅ **Deposit Approved**\n\n"
                                     f"🧑 User: {_user_label(user)}\n"
                                     f"💰 Amount: **₱{order.amount:,.2f}**\n"
                                     f"🎫 Order: `{order.order_no}`\n"
                                     f"👨‍💼 By: {admin_label or 'Admin'}"
                                     + (f"\n📝 Remark: {remark}" if remark else ""))
    rank = rank_for(user)
    send_text(user.chat_id,
              f"✅ **DEPOSIT APPROVED!** 🎉\n\n"
              f"Your deposit of **₱{order.amount:,.2f}** is confirmed!\n"
              f"New balance: **₱{user.balance:,.2f}**\n"
              f"Current rank: {RANK_EMOJI.get(rank['key'], '')} **{rank['name']}**\n"
              f"🎫 Order: `{order.order_no}`"
              + (f"\n📝 {remark}" if remark else "")
              + bonus_text
              + f"\n\n⚔️ Go make some plays, legend!")
    return True


def reject_deposit(session, order: Order, admin_label: str = "", remark: str = "", ban: bool = False):
    if order.kind != "deposit" or order.status != "pending":
        return False
    user = session.get(User, order.user_id)
    order.status = "rejected"
    order.handled_by = admin_label
    order.handled_at = datetime.utcnow()
    order.remark = remark
    if ban:
        user.is_banned = True
    session.commit()
    _post_tx_request(session, order, f"❌ **Deposit Rejected**\n\n"
                                     f"🧑 User: {_user_label(user)}\n"
                                     f"💰 Amount: **₱{order.amount:,.2f}**\n"
                                     f"🎫 Order: `{order.order_no}`\n"
                                     f"📝 Reason: {remark or 'Not approved'}\n"
                                     f"👨‍💼 By: {admin_label or 'Admin'}"
                                     + ("\n⛔ **User banned!**" if ban else ""))
    send_text(user.chat_id,
              f"❌ **DEPOSIT REJECTED**\n\n"
              f"Your deposit of **₱{order.amount:,.2f}** was rejected.\n"
              f"🎫 Order: `{order.order_no}`\n"
              + (f"📝 Reason: {remark}\n" if remark else "")
              + (f"\n⛔ Your account has been banned. Contact support." if ban else
                 "\n💬 Contact customer service if you believe this is a mistake."))
    return True


# ----------------------------------------------------------- withdrawals --
def submit_withdraw(session, user: User, channel_id: int = 0, amount: float = 0.0,
                    fields: dict | None = None) -> tuple[Order | None, str | None]:
    """Withdrawals can ONLY be sent to the user's one-time bound wallet/bank.
    The bound details are used automatically — submitted fields are ignored."""
    if not user.bind_account:
        return None, ("🔒 **No wallet bound yet.**\n\n"
                      "Withdrawals are sent ONLY to your permanently bound wallet/bank.\n"
                      "Open the bot → **Profile → 🏦 Bind Wallet/Bank** to set it up (one-time, +₱30 bonus!).")
    amt = round(float(amount), 2)
    # limits: use the selected channel when provided, else global defaults
    min_amt, max_amt = 1.0, 50000.0
    if channel_id:
        channel = session.get(WithdrawChannel, channel_id)
        if not channel or not channel.active:
            return None, "Withdrawal channel not available."
        min_amt, max_amt = channel.min_amount or 1.0, channel.max_amount or 50000.0
    if amt < min_amt:
        return None, f"Min withdrawal is ₱{min_amt:,.2f}."
    if amt > max_amt:
        return None, f"Max withdrawal is ₱{max_amt:,.2f}."
    if user.balance_frozen:
        return None, "⛔ Your balance is frozen — contact support."
    if (user.balance or 0) < amt:
        return None, "Insufficient balance."
    user.balance = round((user.balance or 0) - amt, 2)
    bound = {
        "wallet": user.bind_name or "",
        "account": user.bind_account,
        "holder": user.bind_holder or "",
    }
    order = Order(order_no=mk_no("WDR"), user_id=user.id, kind="withdraw", amount=amt,
                  direction="out", status="pending",
                  title=f"Withdraw → {user.bind_name or 'Bound wallet'}",
                  detail=json.dumps(bound))
    session.add(order)
    session.commit()
    session.refresh(order)
    _post_tx_request(session, order, f"💸 **New Withdrawal Request**\n\n"
                                     f"🧑 User: {_user_label(user)}\n"
                                     f"📤 Amount: **₱{amt:,.2f}**\n"
                                     f"🏦 Bound wallet: **{esc(user.bind_name or '')}**\n"
                                     f"🔢 Account: **{esc(user.bind_account)}**\n"
                                     f"👤 Holder: **{esc(user.bind_holder or '')}**\n"
                                     f"🎫 Order: `{order.order_no}`\n"
                                     f"🕐 Time: {order.created_at:%Y-%m-%d %H:%M}")
    return order, None


def approve_withdraw(session, order: Order, admin_label: str = "", remark: str = ""):
    if order.kind != "withdraw" or order.status != "pending":
        return False
    user = session.get(User, order.user_id)
    order.status = "approved"
    order.handled_by = admin_label
    order.handled_at = datetime.utcnow()
    if remark:
        order.remark = remark
    user.total_withdraw = round((user.total_withdraw or 0) + (order.amount or 0), 2)
    session.commit()
    _post_tx_request(session, order, f"✅ **Withdrawal Approved**\n\n"
                                     f"🧑 User: {_user_label(user)}\n"
                                     f"📤 Amount: **₱{order.amount:,.2f}**\n"
                                     f"🎫 Order: `{order.order_no}`\n"
                                     f"👨‍💼 By: {admin_label or 'Admin'}"
                                     + (f"\n📝 Remark: {remark}" if remark else ""))
    send_text(user.chat_id,
              f"✅ **WITHDRAWAL APPROVED!** 🎉\n\n"
              f"Your withdrawal of **₱{order.amount:,.2f}** is approved & being processed.\n"
              f"🎫 Order: `{order.order_no}`\n"
              + (f"📝 {remark}\n" if remark else "")
              + f"\n💸 Funds will reach your {order.title.replace('Withdraw via ', '')} shortly!")
    return True


def reject_withdraw(session, order: Order, admin_label: str = "", remark: str = "", ban: bool = False):
    if order.kind != "withdraw" or order.status != "pending":
        return False
    user = session.get(User, order.user_id)
    order.status = "rejected"
    order.handled_by = admin_label
    order.handled_at = datetime.utcnow()
    order.remark = remark
    user.balance = round((user.balance or 0) + (order.amount or 0), 2)  # refund
    if ban:
        user.is_banned = True
    session.commit()
    _post_tx_request(session, order, f"❌ **Withdrawal Rejected**\n\n"
                                     f"🧑 User: {_user_label(user)}\n"
                                     f"📤 Amount: **₱{order.amount:,.2f}** (refunded)\n"
                                     f"🎫 Order: `{order.order_no}`\n"
                                     f"📝 Reason: {remark or 'Not approved'}\n"
                                     f"👨‍💼 By: {admin_label or 'Admin'}"
                                     + ("\n⛔ **User banned!**" if ban else ""))
    send_text(user.chat_id,
              f"❌ **WITHDRAWAL REJECTED**\n\n"
              f"Your withdrawal of **₱{order.amount:,.2f}** was rejected and refunded to your balance.\n"
              f"New balance: **₱{user.balance:,.2f}**\n"
              f"🎫 Order: `{order.order_no}`\n"
              + (f"📝 Reason: {remark}\n" if remark else "")
              + (f"\n⛔ Your account has been banned. Contact support." if ban else
                 "\n💬 Contact customer service if you believe this is a mistake."))
    return True


# ------------------------------------------------------------- promo / rewards --
def redeem_promo(session, user: User, code: str) -> tuple[float | None, str | None]:
    from app.models import Promo
    p = session.query(Promo).filter(Promo.code.ilike(code.strip())).first()
    if not p or not p.active:
        return None, "❌ Invalid promo code."
    if p.expires_at and p.expires_at < datetime.utcnow():
        return None, "⌛ This promo code has expired."
    if p.uses_max and (p.uses_count or 0) >= p.uses_max:
        return None, "🚫 This promo code has reached its usage limit."
    p.uses_count = (p.uses_count or 0) + 1
    user.balance = round((user.balance or 0) + (p.amount or 0), 2)
    user.total_rewards = round((user.total_rewards or 0) + (p.amount or 0), 2)
    order = Order(order_no=mk_no("PRO"), user_id=user.id, kind="promo", amount=p.amount,
                  direction="in", status="completed", title=p.title or p.code, ref=p.code)
    session.add(order)
    session.commit()
    send_text(user.chat_id,
              f"🎁 **PROMO REDEEMED!** 🎉\n\n"
              f"Code **{p.code}** applied!\n"
              f"Reward: **+₱{p.amount:,.2f}** 💰\n"
              f"New balance: **₱{user.balance:,.2f}**\n\n"
              f"🎫 Order: `{order.order_no}`")
    return p.amount, None


def daily_claim(session, user: User) -> tuple[float | None, str | None]:
    today = date.today()
    if user.last_daily_claim == today:
        return None, "⏳ You already claimed today's reward!"
    bonus = float(get_setting(session, "daily_bonus", 2.0))
    user.last_daily_claim = today
    user.balance = round((user.balance or 0) + bonus, 2)
    user.total_rewards = round((user.total_rewards or 0) + bonus, 2)
    order = Order(order_no=mk_no("DLY"), user_id=user.id, kind="daily", amount=bonus,
                  direction="in", status="completed", title="Daily reward")
    session.add(order)
    session.commit()
    send_text(user.chat_id,
              f"🎁 **DAILY REWARD CLAIMED!** ✨\n\n"
              f"You received **+₱{bonus:,.2f}**!\n"
              f"💰 New balance: **₱{user.balance:,.2f}**\n\n"
              f"🔥 Come back tomorrow for more!")
    return bonus, None


def convert_referral(session, user: User) -> tuple[float | None, str | None]:
    amt = round(user.referral_balance or 0, 2)
    if amt < 1:
        return None, "Your referral rewards balance is below ₱1.00."
    user.referral_balance = 0.0
    user.balance = round((user.balance or 0) + amt, 2)
    order = Order(order_no=mk_no("CNV"), user_id=user.id, kind="convert", amount=amt,
                  direction="in", status="completed", title="Referral rewards converted")
    session.add(order)
    session.commit()
    send_text(user.chat_id,
              f"🔄 **REFERRAL REWARDS CONVERTED!**\n\n"
              f"**₱{amt:,.2f}** moved to your main balance!\n"
              f"💰 New balance: **₱{user.balance:,.2f}**\n\n"
              f"🤝 Invite more friends to earn more!")
    return amt, None


# ------------------------------------------------------------- admin actions --
def admin_user_action(session, target: User, action: str, title: str, remark: str,
                      amount: float = 0.0, admin: str = "") -> tuple[bool, str]:
    title = title.strip() or "MLPlay Notice"
    log = ActionLog(admin=admin, action=action, target_tg_id=target.tg_id,
                    title=title, remark=remark)
    session.add(log)
    chat = target.chat_id
    msg = ""
    if action == "ban":
        target.is_banned = True
        target.is_suspended = False
        msg = f"⛔ **{title}**\n\nYou have been **banned** from MLPlay.\n📝 {remark}\n\nContact support for appeal."
    elif action == "unban":
        target.is_banned = False
        msg = f"✅ **{title}**\n\nYour account has been **unbanned**. Welcome back! 🎉\n📝 {remark}"
    elif action == "suspend":
        target.is_suspended = True
        msg = f"⏸️ **{title}**\n\nYour account is **suspended** temporarily.\n📝 {remark}"
    elif action == "unsuspend":
        target.is_suspended = False
        msg = f"▶️ **{title}**\n\nYour account suspension has been **lifted**.\n📝 {remark}"
    elif action == "freeze":
        target.balance_frozen = True
        msg = f"⛔ **{title}**\n\nYour **balance has been frozen**.\n📝 {remark}"
    elif action == "unfreeze":
        target.balance_frozen = False
        msg = f"✅ **{title}**\n\nYour balance has been **unfrozen**.\n📝 {remark}"
    elif action == "add_balance":
        amt = round(float(amount), 2)
        target.balance = round((target.balance or 0) + amt, 2)
        order = Order(order_no=mk_no("ADJ"), user_id=target.id, kind="reward", amount=amt,
                      direction="in", status="completed", title=title, remark=remark)
        session.add(order)
        msg = f"🎁 **{title}**\n\n**+₱{amt:,.2f}** credited to your balance!\n💰 New balance: **₱{target.balance:,.2f}**\n📝 {remark}"
    elif action == "remove_balance":
        amt = round(float(amount), 2)
        if amt > (target.balance or 0):
            return False, "Amount exceeds the user's balance."
        target.balance = round((target.balance or 0) - amt, 2)
        order = Order(order_no=mk_no("ADJ"), user_id=target.id, kind="reward", amount=-amt,
                      direction="out", status="completed", title=title, remark=remark)
        session.add(order)
        msg = (f"⚠️ **{title}**\n\n**-₱{amt:,.2f}** deducted from your balance.\n"
               f"💰 New balance: **₱{target.balance:,.2f}**\n📝 {remark}")
    session.commit()
    if chat and msg:
        send_text(chat, msg)
    group = get_setting(session, "action_group", "")
    if group:
        send_text(resolve_target(group),
                  f"🔔 **ACTION: {action.upper()}**\n\n👤 Target: {_user_label(target)}\n"
                  f"📢 {title}\n📝 {remark}\n👨‍💼 By: {admin or 'Admin'}")
    return True, ""


def admin_set_bind(session, target: User, admin: str, bind_name: str, bind_account: str,
                   bind_holder: str) -> tuple[bool, str]:
    """Admins may change/overwrite a user's bound wallet (the only way to change it)."""
    if not bind_name or not bind_account:
        return False, "Wallet name and account number are required."
    old = f"{target.bind_name or ''} {target.bind_account or ''}".strip()
    target.bind_name = bind_name.strip()[:120]
    target.bind_account = bind_account.strip()[:120]
    target.bind_holder = (bind_holder or bind_name).strip()[:120]
    target.bound_at = datetime.utcnow()
    log = ActionLog(admin=admin, action="set_bind", target_tg_id=target.tg_id,
                    title="Wallet binding updated",
                    remark=f"From [{old}] to [{target.bind_name}/{target.bind_account}]")
    session.add(log)
    session.commit()
    send_text(target.chat_id,
              f"🏦 **WALLET DETAILS UPDATED BY ADMIN**\n\n"
              f"Wallet/Bank: **{esc(target.bind_name)}**\n"
              f"Account: **{esc(target.bind_account)}**\n"
              f"Holder: **{esc(target.bind_holder)}**\n\n"
              f"📝 Contact support if you have questions.")
    group = get_setting(session, "action_group", "")
    if group:
        send_text(resolve_target(group),
                  f"🏦 **BINDING UPDATED BY ADMIN** — {_user_label(target)} → {esc(target.bind_name)}/{esc(target.bind_account)}")
    return True, ""


def _post_tx_request(session, order: Order, text: str):
    """Post a request/update to the transaction group with approval buttons."""
    group = get_setting(session, "tx_group", "")
    if not group:
        return
    if order.status == "pending":
        k = "d" if order.kind == "deposit" else "w"
        rows = [
            [{"t": f"✅ Approve {order.amount:,.0f}", "cb": f"ap{k}:{order.id}"},
             {"t": "❌ Reject", "cb": f"rj{k}:{order.id}"},
             {"t": "⛔ Reject+Ban", "cb": f"rb{k}:{order.id}"}],
        ]
    else:
        rows = None
    send_text(resolve_target(group), text, kb=kb(rows) if rows else None)


def _user_label(u: User) -> str:
    name = u.tg_fullname or f"@{u.tg_username}" or f"ID {u.tg_id}"
    return f"{esc(name)} (tg:{u.tg_id})"


# ---------------------------------------------------------- rank bonuses ----
def maybe_rank_up(session, user: User) -> bool:
    """After deposits/bets change, credit the rank-reach bonus when the user
    climbs to a new rank. Returns True if a bonus was awarded."""
    from app.ranks import RANKS, rank_for

    new_rank = rank_for(user)
    new_key = new_rank["key"]
    old_key = user.rank_key or "warrior"
    old_idx = next((i for i, r in enumerate(RANKS) if r["key"] == old_key), 0)
    new_idx = next((i for i, r in enumerate(RANKS) if r["key"] == new_key), 0)
    if new_key == old_key:
        return False
    user.rank_key = new_key
    if new_idx <= old_idx:  # demotion or equal — no bonus
        session.commit()
        return False
    bonus_map = dict(get_setting(session, "rank_bonus", {}))
    bonus = float(bonus_map.get(new_key, 0) or 0)
    if bonus > 0:
        user.balance = round((user.balance or 0) + bonus, 2)
        user.total_rewards = round((user.total_rewards or 0) + bonus, 2)
        order = Order(order_no=mk_no("RNK"), user_id=user.id, kind="rank", amount=bonus,
                      direction="in", status="completed",
                      title=f"{new_rank['tier']} {new_rank['name']} rank-up bonus")
        session.add(order)
        session.commit()
        send_text(user.chat_id,
                  f"🎖️ **RANK UP BONUS!**\n\n"
                  f"Congratulations! You reached **{RANK_EMOJI.get(new_key, '')} {new_rank['tier']} {new_rank['name']}**!\n"
                  f"Rank bonus: **+₱{bonus:,.2f}** 💰\n"
                  f"💰 New balance: **₱{user.balance:,.2f}**\n\n"
                  f"⚔️ Your limits just got bigger — keep climbing!")
    else:
        session.commit()
        send_text(user.chat_id,
                  f"🎖️ **RANK UP!**\n\n"
                  f"You reached **{RANK_EMOJI.get(new_key, '')} {new_rank['tier']} {new_rank['name']}**!\n"
                  f"⚔️ New betting limits unlocked — keep playing, legend!")
    group = get_setting(session, "action_group", "")
    if group:
        send_text(resolve_target(group),
                  f"🎖️ **RANK UP** — {_user_label(user)} reached **{new_rank['tier']} {new_rank['name']}**"
                  + (f" (+₱{bonus:,.2f} bonus)" if bonus > 0 else ""))
    return True


# -------------------------------------------------------- bank binding ----
def bind_wallet(session, user: User, bind_name: str, bind_account: str,
                bind_holder: str) -> tuple[float | None, str | None]:
    """One-time bank/wallet binding. Returns (bonus_amount, error)."""
    bind_name = (bind_name or "").strip()[:120]
    bind_account = (bind_account or "").strip()[:120]
    bind_holder = (bind_holder or "").strip()[:120]
    if not bind_name or not bind_account:
        return None, "Missing wallet/bank details."
    if user.bind_account:
        return None, "🔒 You already bound your wallet — binding can only be set up once."
    user.bind_name = bind_name
    user.bind_account = bind_account
    user.bind_holder = bind_holder or bind_name
    user.bound_at = datetime.utcnow()
    bonus = round(float(get_setting(session, "bind_bonus", 30.0)), 2)
    user.balance = round((user.balance or 0) + bonus, 2)
    user.total_rewards = round((user.total_rewards or 0) + bonus, 2)
    order = Order(order_no=mk_no("BND"), user_id=user.id, kind="bind", amount=bonus,
                  direction="in", status="completed",
                  title="Wallet binding bonus", ref=f"{bind_name}/{bind_account}")
    session.add(order)
    session.commit()
    send_text(user.chat_id,
              f"🏦 **WALLET BOUND!** 🔗\n\n"
              f"Wallet/Bank: **{esc(bind_name)}**\n"
              f"Account: **{esc(bind_account)}**\n"
              f"Holder: **{esc(bind_holder)}**\n\n"
              f"🎁 Binding bonus: **+₱{bonus:,.2f}**!\n"
              f"💰 New balance: **₱{user.balance:,.2f}**\n\n"
              f"🔒 Note: binding is permanent — contact support if it needs changes.")
    return bonus, None