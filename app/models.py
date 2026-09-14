"""SQLAlchemy models for MLPlay."""
from datetime import datetime, date

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(BigInteger, unique=True, index=True, nullable=False)
    tg_username = Column(String(80), nullable=True)
    tg_fullname = Column(String(255), default="")
    chat_id = Column(BigInteger, default=0)

    balance = Column(Float, default=0.0)              # main playable balance
    referral_balance = Column(Float, default=0.0)     # referral rewards wallet
    total_rewards = Column(Float, default=0.0)        # lifetime bonus rewards (promo/daily/referral/convert)
    total_deposit = Column(Float, default=0.0)        # lifetime approved deposits
    total_withdraw = Column(Float, default=0.0)       # lifetime approved withdrawals
    turnover = Column(Float, default=0.0)             # lifetime wagered amount
    valid_bets = Column(Integer, default=0)           # lifetime settled bets
    joined_at = Column(DateTime, default=datetime.utcnow)

    inviter_tg_id = Column(BigInteger, nullable=True, index=True)

    # one-time bank/wallet binding (admin can still edit)
    bind_name = Column(String(120), nullable=True)     # e.g. GCash / Maya / Bank
    bind_holder = Column(String(120), nullable=True)   # account holder name
    bind_account = Column(String(120), nullable=True)  # account/wallet number
    bound_at = Column(DateTime, nullable=True)

    rank_key = Column(String(32), default="warrior")   # cached rank (for bonuses)

    is_banned = Column(Boolean, default=False)
    is_suspended = Column(Boolean, default=False)
    balance_frozen = Column(Boolean, default=False)

    daily_bets_used = Column(Integer, default=0)
    daily_bets_date = Column(Date, nullable=True)
    last_daily_claim = Column(Date, nullable=True)

    winrate_override = Column(Text, nullable=True)  # JSON: {"rank": 0.5, "mvp": 0.3}

    note = Column(Text, default="")

    def to_dict(self, include_private=False):
        d = {
            "id": self.id,
            "tg_id": self.tg_id,
            "tg_username": self.tg_username or "",
            "tg_fullname": self.tg_fullname or "",
            "balance": round(self.balance or 0, 2),
            "referral_balance": round(self.referral_balance or 0, 2),
            "total_rewards": round(self.total_rewards or 0, 2),
            "total_deposit": round(self.total_deposit or 0, 2),
            "total_withdraw": round(self.total_withdraw or 0, 2),
            "turnover": round(self.turnover or 0, 2),
            "valid_bets": self.valid_bets or 0,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
            "inviter_tg_id": self.inviter_tg_id,
            "is_banned": self.is_banned,
            "is_suspended": self.is_suspended,
            "balance_frozen": self.balance_frozen,
        }
        if include_private:
            d["chat_id"] = self.chat_id
            d["note"] = self.note
        return d


class Hero(Base):
    __tablename__ = "heroes"

    id = Column(Integer, primary_key=True)
    key = Column(String(40), unique=True, index=True)
    name = Column(String(80))
    title = Column(String(120), default="")
    role = Column(String(20), index=True)   # tank / fighter / assassin / mage / support / marksman
    emoji = Column(String(8), default="")
    color1 = Column(String(7), default="#7C3AED")
    color2 = Column(String(7), default="#1E1B4B")
    hp = Column(Integer, default=500)
    atk = Column(Integer, default=100)
    spd = Column(Integer, default=80)
    image_path = Column(String(255), nullable=True)  # custom admin-uploaded image
    active = Column(Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "title": self.title,
            "role": self.role,
            "emoji": self.emoji,
            "color1": self.color1,
            "color2": self.color2,
            "hp": self.hp,
            "atk": self.atk,
            "spd": self.spd,
            "active": self.active,
        }


class Order(Base):
    """Wallet ledger: deposits, withdrawals, promo credits, daily, referral, converts, game payouts."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(32), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    kind = Column(String(20), index=True)   # deposit/withdraw/promo/daily/referral/convert/win
    amount = Column(Float, default=0.0)
    direction = Column(String(8), default="in")  # in / out
    status = Column(String(20), default="pending", index=True)  # pending/approved/rejected/completed
    title = Column(String(255), default="")
    remark = Column(Text, default="")
    detail = Column(Text, default="")        # JSON: method fields etc.
    receipt_path = Column(String(255), nullable=True)
    ref = Column(String(80), default="")     # order ref (bet id / promo code ...)
    handled_by = Column(String(80), default="")
    handled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "order_no": self.order_no,
            "kind": self.kind,
            "amount": round(self.amount or 0, 2),
            "direction": self.direction,
            "status": self.status,
            "title": self.title,
            "remark": self.remark,
            "detail": self.detail,
            "receipt_path": self.receipt_path,
            "ref": self.ref,
            "handled_by": self.handled_by,
            "handled_at": self.handled_at.isoformat() if self.handled_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Bet(Base):
    __tablename__ = "bets"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(32), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    game = Column(String(20), index=True)     # rank / mvp / herole
    match_id = Column(Integer, nullable=True, index=True)
    pick = Column(String(64), default="")     # "blue"/"red"/hero_key/role
    amount = Column(Float, default=0.0)
    status = Column(String(20), default="pending", index=True)  # pending/won/lost
    outcome = Column(Text, default="")        # JSON {"won": bool, "show": "...", "hero_key": "..."}
    payout = Column(Float, default=0.0)
    winrate = Column(Float, default=0.3)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    settled_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "match_id", "game", name="uq_user_match_game"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "order_no": self.order_no,
            "game": self.game,
            "match_id": self.match_id,
            "pick": self.pick,
            "amount": round(self.amount or 0, 2),
            "status": self.status,
            "outcome": self.outcome,
            "payout": round(self.payout or 0, 2),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
        }


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True)
    match_no = Column(Integer, unique=True, index=True)   # epoch-slot based
    status = Column(String(20), default="open", index=True)  # open / resolved
    teams = Column(Text, default="")   # JSON {"blue": [...5 hero keys...], "red": [...]}
    winner = Column(String(10), nullable=True)  # blue / red
    opened_at = Column(DateTime, default=datetime.utcnow)
    resolves_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)


class DepositMethod(Base):
    __tablename__ = "deposit_methods"

    id = Column(Integer, primary_key=True)
    name = Column(String(120))
    detail = Column(Text, default="")     # account/QR text
    image_path = Column(String(255), nullable=True)
    min_amount = Column(Float, default=1.0)
    max_amount = Column(Float, default=50000.0)
    active = Column(Boolean, default=True)
    sort = Column(Integer, default=0)


class WithdrawChannel(Base):
    __tablename__ = "withdraw_channels"

    id = Column(Integer, primary_key=True)
    name = Column(String(120))
    fields = Column(Text, default="[]")   # JSON [{"key","label","placeholder","type"}]
    min_amount = Column(Float, default=1.0)
    max_amount = Column(Float, default=50000.0)
    active = Column(Boolean, default=True)
    sort = Column(Integer, default=0)


class Promo(Base):
    __tablename__ = "promos"

    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, index=True)
    title = Column(String(255), default="")
    amount = Column(Float, default=0.0)
    uses_max = Column(Integer, default=0)     # 0 = unlimited
    uses_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Promotion(Base):
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    text = Column(Text, default="")
    image_path = Column(String(255), nullable=True)
    url = Column(String(255), default="")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")   # JSON-serialized


class ActionLog(Base):
    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True)
    admin = Column(String(80), default="")
    action = Column(String(40))
    target_tg_id = Column(BigInteger, nullable=True)
    title = Column(String(255), default="")
    remark = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class BroadcastJob(Base):
    __tablename__ = "broadcast_jobs"

    id = Column(Integer, primary_key=True)
    text = Column(Text, default="")
    image_path = Column(String(255), nullable=True)
    button_text = Column(String(80), default="")
    button_url = Column(String(255), default="")
    target_rank = Column(String(40), default="")   # "" = all users
    status = Column(String(20), default="pending")  # pending/running/done/cancelled
    total = Column(Integer, default=0)
    done = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)