"""Rank system — every limit in the spec lives here."""
from datetime import date

RANKS = [
    {"key": "warrior", "name": "Warrior", "tier": "Beginner", "max_bet": 10, "daily_bets": 5,
     "games": ["rank"], "need_deposit": 0, "need_bets": 0},
    {"key": "elite", "name": "Elite", "tier": "Level 1", "max_bet": 50, "daily_bets": 10,
     "games": ["rank"], "need_deposit": 0, "need_bets": 100},
    {"key": "master", "name": "Master", "tier": "Level 2", "max_bet": 70, "daily_bets": 50,
     "games": ["rank"], "need_deposit": 0, "need_bets": 300},
    {"key": "grandmaster", "name": "Grandmaster", "tier": "Level 3", "max_bet": 100, "daily_bets": 70,
     "games": ["rank"], "need_deposit": 0, "need_bets": 500},
    {"key": "epic", "name": "Epic", "tier": "Level 4", "max_bet": 150, "daily_bets": None,
     "games": ["rank", "herole"], "need_deposit": 100, "need_bets": 1000},
    {"key": "legend", "name": "Legend", "tier": "Level 5", "max_bet": 300, "daily_bets": None,
     "games": ["rank", "herole"], "need_deposit": 300, "need_bets": 1000},
    {"key": "mythic", "name": "Mythic", "tier": "VIP 1", "max_bet": 500, "daily_bets": None,
     "games": ["rank", "herole", "mvp"], "need_deposit": 500, "need_bets": 3000},
    {"key": "honor", "name": "Honor", "tier": "VIP 2", "max_bet": 1000, "daily_bets": None,
     "games": ["rank", "herole", "mvp"], "need_deposit": 1000, "need_bets": 3000},
    {"key": "glory", "name": "Glory", "tier": "VIP 3", "max_bet": 5000, "daily_bets": None,
     "games": ["rank", "herole", "mvp"], "need_deposit": 5000, "need_bets": 5000},
    {"key": "immortal", "name": "Immortal", "tier": "SVIP", "max_bet": 50_000, "daily_bets": None,
     "games": ["rank", "herole", "mvp"], "need_deposit": 50_000, "need_bets": 10_000},
]

RANK_BY_KEY = {r["key"]: r for r in RANKS}


def rank_for(user) -> dict:
    """Highest rank whose conditions the user meets (deposits + settled bets)."""
    deposits = user.total_deposit or 0
    bets = user.valid_bets or 0
    current = RANKS[0]
    for r in RANKS:
        if deposits >= r["need_deposit"] and bets >= r["need_bets"]:
            current = r
    return current


def rank_index(user) -> int:
    key = rank_for(user)["key"]
    for i, r in enumerate(RANKS):
        if r["key"] == key:
            return i
    return 0


def can_play(user, game: str) -> bool:
    return game in rank_for(user)["games"]


def max_bet_for(user) -> float:
    return float(rank_for(user)["max_bet"])


def daily_limit(user) -> int | None:
    return rank_for(user)["daily_bets"]


def daily_bets_left(user) -> int | None:
    lim = daily_limit(user)
    if lim is None:
        return None
    if user.daily_bets_date != date.today():
        return lim
    return max(0, lim - (user.daily_bets_used or 0))


def next_rank(user):
    idx = rank_index(user)
    return RANKS[idx + 1] if idx + 1 < len(RANKS) else None


def rank_up_progress(user) -> tuple[float, dict]:
    """(progress 0..1, next_rank_or_null)"""
    nxt = next_rank(user)
    if not nxt:
        return 1.0, None
    dep = user.total_deposit or 0
    bets = user.valid_bets or 0
    dep_need = nxt["need_deposit"]
    bet_need = nxt["need_bets"]
    if dep_need <= 0 and bet_need <= 0:
        return 1.0, nxt
    frac = min(1.0, max(
        (dep / dep_need) if dep_need > 0 else 1.0,
        (bets / bet_need) if bet_need > 0 else 1.0,
    ))
    return frac, nxt


RANK_EMOJI = {
    "warrior": "🟤", "elite": "🟢", "master": "🔵", "grandmaster": "🟣",
    "epic": "🟡", "legend": "🟠", "mythic": "🔮", "honor": "💎",
    "glory": "👑", "immortal": "♾️",
}