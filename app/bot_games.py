"""
Bot games — Rank Game (live 2-min matches), Who's The MVP? and HeRole.

Flow for every game:
  click game -> bot asks bet amount (rank limits enforced)
            -> user picks side / hero / role
            -> balance is frozen, bet is placed (win rate rolled server-side)
            -> entertaining fight image + message
            -> 10 seconds later: result card is revealed & balance settled
"""
import asyncio
import json
import logging
import random

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app import cards, wallet
from app.games_svc import next_match_in, open_match_or_none, teams_display
from app.heroes import GAME_MULTIPLIERS, hero_by_key, hero_by_name
from app.models import Match, User
from app.notifier import esc, kb
from app.ranks import RANK_EMOJI, can_play, daily_bets_left, rank_for
from app.settings_svc import get_setting

logger = logging.getLogger("bot_games")

router = Router()

GAME_LABEL = {"rank": "Rank Game", "mvp": "Who's The MVP?", "herole": "HeRole"}
LOCK_HINTS = {
    "rank": "Rank Game is open to every warrior!",
    "mvp": "🔒 Reach **Mythic (VIP 1)** rank to unlock Who's The MVP?",
    "herole": "🔒 Reach **Epic (Level 4)** rank to unlock HeRole",
}


class BG(StatesGroup):
    rank_amt = State()
    rank_pick = State()
    mvp_amt = State()
    mvp_hero = State()
    hr_amt = State()
    hr_pick = State()


# ------------------------------------------------------------- games menu --
async def page_games(cq: CallbackQuery, sess, user: User):
    rank = rank_for(user)
    m = open_match_or_none(sess)
    live = f"🔴 LIVE — Match #{m.match_no} open!" if m else f"⏳ Next match in {next_match_in()}s"
    img = cards.banner_card("MLPLAY GAMES", live, (124, 58, 237), "🎮")
    buttons = [
        [{"t": "⚔️ Rank Game", "cb": "g:rank"}],
        [{"t": "🏆 Who's The MVP?", "cb": "g:mvp"}],
        [{"t": "🎭 HeRole", "cb": "g:herole"}],
        [{"t": "◀️ Back", "cb": "menu"}],
    ]
    caption = (
        f"🎮 **CHOOSE YOUR GAME**\n\n"
        f"{RANK_EMOJI.get(rank['key'], '')} Your rank: **{rank['name']}** — max bet **₱{rank['max_bet']:,.2f}**\n"
        f"{live}\n\n"
        f"⚔️ **Rank Game** — pick the winning team, win x2\n"
        f"🏆 **MVP** — guess the MVP hero, win **x71** (VIP 1+)\n"
        f"🎭 **HeRole** — guess the hero role, win **x3** (Level 4+)\n\n"
        f"🎯 Min bet ₱1 • Results every 2 minutes!"
    )
    await cq.message.answer_photo(BufferedInputFile(img, "games.png"), caption=caption,
                                  reply_markup=kb(buttons))


def _mtor(cq: CallbackQuery):
    return cq.message.chat.id


# ------------------------------------------------------------- rank game --
@router.callback_query(F.data.in_({"g:rank", "mb:r"}))
async def g_rank(cq: CallbackQuery, sm, state: FSMContext):
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        if not user:
            await cq.answer("Register first!")
            return
        if not can_play(user, "rank"):
            await cq.answer("Locked")
            return
        await cq.answer()
        m = open_match_or_none(sess)
        if not m:
            await cq.message.answer(
                f"⏳ **NO LIVE MATCH RIGHT NOW**\n\n"
                f"⚔️ Next match starts in **{next_match_in()}s**!\n"
                f"Set a reminder — every 2 minutes a new battle begins! 🔥")
            return
        await _ask_rank_amount(cq, sm, state, m.match_no)
    finally:
        sess.close()


@router.callback_query(F.data.startswith("mb:"))
async def g_rank_deep(cq: CallbackQuery, sm, state: FSMContext):
    """Channel 'place bet' button fallback (no bot username configured)."""
    try:
        mid = int(cq.data.split(":", 1)[1])
    except Exception:
        return
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        if not user:
            await cq.answer("Register first!")
            return
        await cq.answer()
        m = sess.query(Match).filter(Match.match_no == mid, Match.status == "open").first()
        if not m:
            await cq.message.answer("⏳ That match already closed — bet on the next one!")
            return
        await _ask_rank_amount(cq, sm, state, mid)
    finally:
        sess.close()


async def _ask_rank_amount(cq: CallbackQuery, sm, state: FSMContext, mid: int):
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        rank = rank_for(user)
        await state.set_state(BG.rank_amt)
        await state.update_data(game="rank", match_id=mid)
        await cq.message.answer(
            f"⚔️ **MATCH #{mid} — PLACE YOUR BET**\n\n"
            f"Type the amount you want to bet 🎯\n"
            f"💵 Min: **₱1** • Max (your rank): **₱{rank['max_bet']:,.2f}**\n"
            f"💰 Your balance: **₱{user.balance:,.2f}**\n"
            f"{'⏳ Daily bets left: ' + str(daily_bets_left(user)) if daily_bets_left(user) is not None else ''}\n\n"
            f"👆 Just type a number (e.g. `100`)",
            reply_markup=kb([[{"t": "✖️ Cancel", "cb": "cancel"}]]))
    finally:
        sess.close()


@router.message(BG.rank_amt)
async def on_rank_amount(msg: Message, sm, state: FSMContext):
    await _on_amount(msg, sm, state, "rank")


async def _on_amount(msg: Message, sm, state: FSMContext, game: str):
    try:
        amount = float(msg.text.replace(",", "").strip())
    except Exception:
        await msg.answer("⚠️ Please send a valid number (e.g. `150`).")
        return
    data = await state.get_data()
    sess = sm()
    try:
        user = wallet.user_by_id(sess, msg.from_user.id)
        if not user:
            await msg.answer("Register first!")
            return
        rank = rank_for(user)
        if amount < 1 or amount > rank["max_bet"]:
            await msg.answer(
                f"⚠️ Bet must be between **₱1** and **₱{rank['max_bet']:,.2f}** ({rank['tier']} {rank['name']} limit).")
            return
        if (user.balance or 0) < amount:
            await msg.answer(f"💰 Insufficient balance — you have **₱{user.balance:,.2f}**. Deposit to keep playing!")
            return
        await state.update_data(amount=round(amount, 2))

        if game == "rank":
            mid = int(data.get("match_id") or 0)
            m = open_match_or_none(sess)
            if not m or m.match_no != mid:
                await state.clear()
                await msg.answer(f"⏳ Match #{mid} closed — a new one starts in {next_match_in()}s! ⚡")
                return
            blue, red = teams_display(sess, json.loads(m.teams or "{}"))
            img = cards.lineup_card(mid, blue, red)
            await msg.answer_photo(
                BufferedInputFile(img, "lineup.png"),
                caption=(f"⚔️ **MATCH #{mid} LINEUPS**\n\n"
                         f"🔵 **BLUE TEAM** vs 🔴 **RED TEAM**\n\n"
                         f"Your bet: **₱{amount:,.2f}** — win = **x2** ⚡\n"
                         f"👇 Pick your side!"),
                reply_markup=kb([
                    [{"t": "🔵 BLUE TEAM", "cb": f"pk:rank:{mid}:blue"},
                     {"t": "🔴 RED TEAM", "cb": f"pk:rank:{mid}:red"}],
                    [{"t": "✖️ Cancel", "cb": "cancel"}],
                ]))
            await state.set_state(BG.rank_pick)
        elif game == "mvp":
            await state.set_state(BG.mvp_hero)
            await _ask_mvp_hero(msg, sm, state)
        else:  # herole
            await state.set_state(BG.hr_pick)
            await msg.answer(
                f"🎭 **HEROLE — PICK YOUR ROLE**\n\n"
                f"Your bet: **₱{amount:,.2f}** — correct role wins **x3** 🎯\n"
                f"Guess which hero role dominates the match!",
                reply_markup=kb(_role_buttons() + [[{"t": "✖️ Cancel", "cb": "cancel"}]]))
    finally:
        sess.close()


def _role_buttons():
    return [[{"t": "🛡️ Tank", "cb": "pk:herole:tank"},
             {"t": "⚔️ Fighter", "cb": "pk:herole:fighter"},
             {"t": "🗡️ Assassin", "cb": "pk:herole:assassin"}],
            [{"t": "🔮 Mage", "cb": "pk:herole:mage"},
             {"t": "💠 Support", "cb": "pk:herole:support"},
             {"t": "🎯 Marksman", "cb": "pk:herole:marksman"}]]


async def ask_rank_amount_message(msg: Message, sm, state: FSMContext, mid: int):
    """Deep-link entry: /start bet_<match_no>."""
    sess = sm()
    try:
        user = wallet.user_by_id(sess, msg.from_user.id)
        if not user:
            return
        m = sess.query(Match).filter(Match.match_no == mid, Match.status == "open").first()
        if not m:
            await msg.answer(f"⏳ That match already closed — the next one starts in {next_match_in()}s! ⚡")
            return
        rank = rank_for(user)
        await state.set_state(BG.rank_amt)
        await state.update_data(game="rank", match_id=mid)
        await msg.answer(
            f"⚔️ **MATCH #{mid} — PLACE YOUR BET**\n\n"
            f"Type the amount you want to bet 🎯\n"
            f"💵 Min: **₱1** • Max (your rank): **₱{rank['max_bet']:,.2f}**\n"
            f"💰 Your balance: **₱{user.balance:,.2f}**\n\n"
            f"👆 Just type a number (e.g. `100`)",
            reply_markup=kb([[{"t": "✖️ Cancel", "cb": "cancel"}]]))
    finally:
        sess.close()


# ------------------------------------------------------- MVP game --------
@router.callback_query(F.data == "g:mvp")
async def g_mvp(cq: CallbackQuery, sm, state: FSMContext):
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        if not user:
            await cq.answer("Register first!")
            return
        if not can_play(user, "mvp"):
            await cq.answer("Locked")
            await cq.message.answer(
                f"🔒 **WHO'S THE MVP? IS RANK-LOCKED**\n\n"
                f"This game unlocks at **Mythic (VIP 1)** rank (₱500 deposits + 3,000 valid bets).\n"
                f"Keep grinding, legend! 💪 {RANK_EMOJI.get(rank_for(user)['key'], '')}")
            return
        await cq.answer()
        rank = rank_for(user)
        await state.set_state(BG.mvp_amt)
        await state.update_data(game="mvp")
        await cq.message.answer(
            f"🏆 **WHO'S THE MVP?**\n\n"
            f"Guess the MVP hero and win **x71**!! 💥\n"
            f"Type your bet amount 🎯\n"
            f"💵 Min: **₱1** • Max: **₱{rank['max_bet']:,.2f}**\n"
            f"💰 Balance: **₱{user.balance:,.2f}**\n\n"
            f"👆 Type a number (e.g. `50`)",
            reply_markup=kb([[{"t": "✖️ Cancel", "cb": "cancel"}]]))
    finally:
        sess.close()


@router.message(BG.mvp_amt)
async def on_mvp_amount(msg: Message, sm, state: FSMContext):
    await _on_amount(msg, sm, state, "mvp")


async def _ask_mvp_hero(msg: Message, sm, state: FSMContext):
    sess = sm()
    try:
        heroes = _random_heroes(sess, 6)
        buttons = [[{"t": f"{h.emoji} {h.name}", "cb": f"hx:{h.key}"} for h in row] for row in _chunks(heroes, 2)]
        buttons.append([{"t": "✖️ Cancel", "cb": "cancel"}])
        names = ", ".join(h.name for h in heroes)
        await msg.answer(
            f"🏆 **NAME THE MVP HERO**\n\n"
            f"Type the hero's name, or tap a suggestion:\n\n"
            f"💡 Hints: `{names}`",
            reply_markup=kb(buttons))
    finally:
        sess.close()


def _random_heroes(sess, n=6):
    from app.heroes import get_hero_pool
    pool = get_hero_pool(sess)
    return random.sample(pool, min(n, len(pool)))


def _chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


@router.message(BG.mvp_hero)
async def on_mvp_hero_typed(msg: Message, sm, state: FSMContext):
    sess = sm()
    try:
        hero = hero_by_name(sess, msg.text or "")
        if not hero:
            await msg.answer("❌ Hero not found. Check the hint list and try again!")
            return
        await _do_pick(msg=msg, sm=sm, state=state, game="mvp", pick=hero.key)
    finally:
        sess.close()


@router.callback_query(F.data.startswith("hx:"))
async def on_mvp_hero_cb(cq: CallbackQuery, sm, state: FSMContext):
    key = cq.data.split(":", 1)[1]
    sess = sm()
    try:
        hero = hero_by_key(sess, key)
        if not hero:
            await cq.answer("Hero unavailable")
            return
        await _do_pick(msg=cq.message, sm=sm, state=state, game="mvp", pick=key)
        await cq.answer()
    finally:
        sess.close()


# ------------------------------------------------------- HeRole --------
@router.callback_query(F.data == "g:herole")
async def g_herole(cq: CallbackQuery, sm, state: FSMContext):
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        if not user:
            await cq.answer("Register first!")
            return
        if not can_play(user, "herole"):
            await cq.answer("Locked")
            await cq.message.answer(
                f"🔒 **HEROLE IS RANK-LOCKED**\n\n"
                f"This game unlocks at **Epic (Level 4)** rank (₱100 deposits + 1,000 valid bets).\n"
                f"Keep grinding, legend! 💪 {RANK_EMOJI.get(rank_for(user)['key'], '')}")
            return
        await cq.answer()
        rank = rank_for(user)
        await state.set_state(BG.hr_amt)
        await state.update_data(game="herole")
        await cq.message.answer(
            f"🎭 **HEROLE**\n\n"
            f"Guess the winning hero's ROLE and win **x3**! 💥\n"
            f"Type your bet amount 🎯\n"
            f"💵 Min: **₱1** • Max: **₱{rank['max_bet']:,.2f}**\n"
            f"💰 Balance: **₱{user.balance:,.2f}**\n\n"
            f"👆 Type a number (e.g. `30`)",
            reply_markup=kb([[{"t": "✖️ Cancel", "cb": "cancel"}]]))
    finally:
        sess.close()


@router.message(BG.hr_amt)
async def on_hr_amount(msg: Message, sm, state: FSMContext):
    await _on_amount(msg, sm, state, "herole")


# ------------------------------------------------------- pick & fight ----
@router.callback_query(F.data.startswith("pk:"))
async def on_pick_cb(cq: CallbackQuery, sm, state: FSMContext):
    parts = cq.data.split(":")
    game = parts[1]
    if game == "rank":
        mid = int(parts[2])
        pick = parts[3]
    else:
        pick = parts[2]
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        if not user:
            await cq.answer("Register first!")
            return
        data = await state.get_data()
        amount = float(data.get("amount") or 0)
        await state.clear()
        if game == "rank":
            await _do_pick(cq=cq, sm=sm, state=state, game="rank", pick=pick,
                           match_id=mid, amount=amount)
        else:
            await _do_pick(cq=cq, sm=sm, state=state, game=game, pick=pick, amount=amount)
        await cq.answer()
    finally:
        sess.close()


async def _do_pick(cq=None, msg=None, sm=None, state: FSMContext = None, game=None,
                   pick=None, match_id=None, amount=None):
    """Final bet placement + fight + scheduled result."""
    data_state = await state.get_data() if state else {}
    if amount is None:
        amount = float(data_state.get("amount") or 0)
    mtarget = cq.message if cq else msg
    sess = sm()
    try:
        user = wallet.user_by_id(sess, mtarget.from_user.id)
        bet, err = wallet.place_bet(sess, user, game, amount, match_id, pick)
        if err:
            await mtarget.answer(err)
            return
        if game == "mvp":
            hero = hero_by_key(sess, bet.pick)
            img = cards.fight_card("mvp", hero=hero.to_dict() if hero else None)
            caption = (f"🏆 **MATCH IN PROGRESS...**\n\n"
                       f"Your MVP pick: **{hero.name if hero else '?'}**\n"
                       f"Bet: **₱{bet.amount:,.2f}** → potential **x71**! 💎\n\n"
                       f"🔥 The battle is heating up…")
        elif game == "herole":
            img = cards.fight_card("herole", picked_role=pick)
            caption = (f"🎭 **ROLE BATTLE IN PROGRESS...**\n\n"
                       f"Your role pick: **{pick.upper()}**\n"
                       f"Bet: **₱{bet.amount:,.2f}** → potential **x3**! 💥\n\n"
                       f"🔥 Who will claim the spotlight?")
        else:  # rank
            m = sess.query(Match).filter(Match.match_no == match_id).first()
            if m:
                blue, red = teams_display(sess, json.loads(m.teams or "{}"))
            else:
                blue, red = [], []
            img = cards.fight_card("rank", match_no=match_id, blue=blue, red=red)
            caption = (f"⚔️ **MATCH #{match_id} IN PROGRESS...**\n\n"
                       f"Your side: **{'🔵 BLUE' if pick == 'blue' else '🔴 RED'}**\n"
                       f"Bet: **₱{bet.amount:,.2f}** → win = **x2** ⚡\n\n"
                       f"🔥 THE BATTLE RAGES ON...")
        sent = await mtarget.answer_photo(BufferedInputFile(img, "fight.png"), caption=caption)
        asyncio.create_task(deliver_result(bet.id, mtarget.chat.id))
    finally:
        sess.close()


async def deliver_result(bet_id: int, chat_id: int):
    """10-second fight timer, then reveal the result card."""
    from app.config import FIGHT_DURATION
    await asyncio.sleep(FIGHT_DURATION)
    from app.db import get_session
    from app.wallet import bet_result_payload, settle_bet
    sess = get_session()
    try:
        from app.models import Bet, User
        bet = sess.get(Bet, bet_id)
        if not bet:
            return
        user = sess.get(User, bet.user_id)
        settle_bet(sess, bet)  # idempotent
        p = bet_result_payload(sess, bet)
        hero = p.get("hero")
        card = cards.result_card(p["headline"], p["sub"], p["payout"],
                                 hero=hero.to_dict() if hero else None, win=p["won"])
        caption = (
            f"{p['headline']}\n{p['sub']}\n\n"
            f"🎫 Bet: `{bet.order_no}` • {GAME_LABEL.get(bet.game, bet.game)}\n"
            f"💵 Amount: **₱{bet.amount:,.2f}**\n"
            f"{'🎉 ' + p['payout'] + '!' if p['won'] else '💔 Next round is yours!'}\n\n"
            f"💰 New balance: **₱{user.balance:,.2f}**"
        )
        from app.notifier import get_bot
        bot = get_bot()
        if bot:
            await bot.send_photo(chat_id, BufferedInputFile(card, "result.png"), caption=caption)
    finally:
        sess.close()