"""
GameLoop — the live match engine.

- A new Rank Game match is born every MATCH_INTERVAL (120 s), aligned to the
  clock, exactly like a real-time esports schedule. Every player on the
  platform bets on the SAME match id.
- While the match is OPEN the bot accepts bets; when the window closes the
  match is RESOLVED and the result is posted to the configured game channel
  with a deep-link button straight back into the bot.
- A sweeper settles any bet that was left pending (e.g. server restart
  during the 10-second fight) so nothing is ever lost.
"""
import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta

from app.config import FIGHT_DURATION, MATCH_BET_WINDOW, MATCH_INTERVAL
from app.db import get_session
from app.heroes import LINEUP_ROLES, hero_by_key
from app.models import Bet, Match, User
from app.notifier import kb, resolve_target, send_photo, send_text
from app.settings_svc import get_setting

logger = logging.getLogger("games")

ROLE_POOLS = {
    "tank_support": ["tank", "support"],
    "fighter": ["fighter"],
    "assassin": ["assassin"],
    "mage": ["mage"],
    "marksman": ["marksman"],
}


def generate_teams(session) -> dict:
    """Blue & Red 5v5 lineups, one hero per role slot, no hero twice.”"""
    from app.heroes import get_hero_pool

    used: set = set()
    blue, red = [], []

    def pick_for(slot_role):
        pool = []
        for r in ROLE_POOLS[slot_role]:
            pool += get_hero_pool(session, r)
        avail = [h for h in pool if h.key not in used]
        if not avail:
            avail = [h for h in pool]
        if not avail:
            return None
        h = random.choice(avail)
        used.add(h.key)
        return h.key

    for slot in LINEUP_ROLES:
        b = pick_for(slot)
        r = pick_for(slot)
        if b:
            blue.append(b)
        if r:
            red.append(r)
    return {"blue": blue, "red": red}


def teams_display(session, teams: dict) -> tuple[list, list]:
    def load(keys):
        out = []
        for k in keys:
            h = hero_by_key(session, k)
            if h:
                out.append(h.to_dict())
        return out
    return load(teams.get("blue", [])), load(teams.get("red", []))


def next_match_in() -> int:
    now = int(time.time())
    return MATCH_INTERVAL - (now % MATCH_INTERVAL)


class GameLoop:
    def __init__(self):
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        await asyncio.sleep(3)
        while True:
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001
                logger.exception("game loop tick failed: %s", e)
            await asyncio.sleep(4)

    # ------------------------------------------------------------ tick --
    def _tick(self):
        now = time.time()
        sess = get_session()
        try:
            self._sweep_pending(sess)
            match = sess.query(Match).filter(Match.status == "open").first()
            if match is None:
                slot = int(now // MATCH_INTERVAL)
                if (now - slot * MATCH_INTERVAL) < MATCH_BET_WINDOW:
                    self._open_match(sess, slot)
            else:
                opened = match.opened_at.timestamp() if match.opened_at else 0
                if now - opened > MATCH_BET_WINDOW:
                    self._resolve_match(sess, match)
        finally:
            sess.close()

    def _open_match(self, sess, slot: int):
        teams = generate_teams(sess)
        match = Match(match_no=slot, status="open",
                      teams=json.dumps(teams),
                      resolves_at=datetime.utcnow() + timedelta(seconds=MATCH_BET_WINDOW))
        sess.add(match)
        sess.commit()
        sess.refresh(match)
        self._announce_match(sess, match)

    def _resolve_match(self, sess, match: Match):
        match.status = "resolved"
        match.winner = random.choice(["blue", "red"])
        match.resolved_at = datetime.utcnow()
        sess.commit()
        self._announce_result(sess, match)

    # ------------------------------------------------------- channel posts --
    def _announce_match(self, sess, match: Match):
        group = get_setting(sess, "game_channel", "")
        if not group:
            return
        blue, red = teams_display(sess, json.loads(match.teams or "{}"))
        from app.cards import lineup_card
        image = lineup_card(match.match_no, blue, red, closes_in=MATCH_BET_WINDOW)
        username = get_setting(sess, "bot_username", "")
        rows = []
        if username:
            rows = [[{"t": "⚔️ PLACE YOUR BET NOW", "u": f"https://t.me/{username}?start=bet_{match.match_no}"}]]
        else:
            rows = [[{"t": "⚔️ PLACE YOUR BET NOW", "cb": f"mb:{match.match_no}"}]]
        caption = (
            f"⚡ **MATCH #{match.match_no} IS LIVE!** ⚡\n\n"
            f"🔵 BLUE TEAM vs 🔴 RED TEAM — 5 vs 5\n"
            f"🕐 Betting closes in {MATCH_BET_WINDOW}s!\n\n"
            f"💰 Pick the winning side and DOUBLE your bet!\n"
            f"👇 Tap below to bet in the bot!"
        )
        send_photo(resolve_target(group), image, caption, kb=kb(rows))

    def _announce_result(self, sess, match: Match):
        group = get_setting(sess, "game_channel", "")
        if not group:
            return
        blue, red = teams_display(sess, json.loads(match.teams or "{}"))
        winner = "BLUE" if match.winner == "blue" else "RED"
        from app.cards import result_card
        image = result_card(
            f"🏆 {winner} TEAM WINS MATCH #{match.match_no} 🏆",
            "The arena roars for the victors!",
            "CONGRATULATIONS TO ALL WINNING BETTORS",
        )
        username = get_setting(sess, "bot_username", "")
        rows = []
        if username:
            rows = [[{"t": "⚔️ BET ON THE NEXT MATCH", "u": f"https://t.me/{username}?start=bet"}]]
        caption = (
            f"🏆 **MATCH #{match.match_no} RESULT** 🏆\n\n"
            f"Winner: **{winner} TEAM** {'🔵' if match.winner == 'blue' else '🔴'}\n"
            f"🎫 Match id: `{match.match_no}`\n\n"
            f"⚡ Next match starts in {MATCH_INTERVAL}s — stay ready!"
        )
        send_photo(resolve_target(group), image, caption, kb=kb(rows))

    # --------------------------------------------------------- sweeper --
    def _sweep_pending(self, sess):
        cutoff = datetime.utcnow() - timedelta(seconds=FIGHT_DURATION + 8)
        from app.wallet import settle_bet
        pending = sess.query(Bet).filter(Bet.status == "pending",
                                         Bet.created_at < cutoff).all()
        for bet in pending:
            try:
                settle_bet(sess, bet)
            except Exception as e:  # noqa: BLE001
                logger.exception("sweep settle failed %s: %s", bet.id, e)


# ------------------------------------------------------------ helpers ----
def open_match_or_none(sess) -> Match | None:
    return sess.query(Match).filter(Match.status == "open").first()