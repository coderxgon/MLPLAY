"""
Bot core — welcome & registration, main menu, Profile / Referral / Contact
Services / Promotions pages, daily reward, deep-link routing.
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app import cards, wallet
from app.db import SessionLocal
from app.heroes import hero_by_key
from app.models import Match, User
from app.notifier import esc, kb
from app.ranks import RANK_EMOJI, rank_for
from app.settings_svc import effective_webapp_url, get_setting, is_admin_tg

logger = logging.getLogger("bot_core")

router = Router()

BIND_TYPES = [("GCash", "Gcash"), ("Maya", "Maya"), ("Bank Transfer", "Bank / Traditional")]


class BindFSM(StatesGroup):
    name = State()
    account = State()
    holder = State()


def wb_url(session, request_host=""):
    return effective_webapp_url(session, request_host)


async def _user(sm, tg_id: int) -> User | None:
    sess = sm()
    try:
        return wallet.user_by_id(sess, tg_id)
    finally:
        sess.close()


def menu_kb(session) -> list:
    return [
        [{"t": "👤 Profile", "cb": "pg:profile"}, {"t": "🔗 Referral", "cb": "pg:referral"}],
        [{"t": "🎮 Games", "cb": "pg:games"}, {"t": "🎁 Promotions", "cb": "pg:promo"}],
        [{"t": "📞 Contact Services", "cb": "pg:contact"}],
        [{"t": "🎁 Daily Reward", "cb": "dly"}, {"t": "⚔️ Live Match", "cb": "g:rank"}],
    ]


async def send_menu(message: Message, sm):
    sess = sm()
    try:
        user = wallet.user_by_id(sess, message.from_user.id)
        rank = rank_for(user)
        text = (
            f"⚡ **WELCOME TO THE MLPLAY MENU** ⚡\n\n"
            f"👤 Player: {esc(user.tg_fullname or '')} {f'(@{esc(user.tg_username)})' if user.tg_username else ''}\n"
            f"{RANK_EMOJI.get(rank['key'], '')} Rank: **{rank['tier']} {rank['name']}**\n"
            f"💰 Balance: **₱{user.balance:,.2f}**\n\n"
            f"👇 Pick a page, legend!"
        )
        await message.answer(text, reply_markup=kb(menu_kb(sess)))
    finally:
        sess.close()


# ------------------------------------------------------------ /start -----
@router.message(CommandStart())
async def cmd_start(message: Message, sm, state: FSMContext, command=None):
    await state.clear()
    payload = (command.args if command and hasattr(command, "args") else "") or ""
    if payload and payload.startswith("bet_") and not payload[4:].isdigit():
        payload = ""  # sanitize

    sess = sm()
    try:
        user = wallet.user_by_id(sess, message.from_user.id)
        # remember pending invite / match intent for the register callback
        if user:
            user.chat_id = message.chat.id
            if user.tg_username != (message.from_user.username or ""):
                user.tg_username = message.from_user.username or ""
            if user.tg_fullname != (message.from_user.full_name or ""):
                user.tg_fullname = message.from_user.full_name or ""
            sess.commit()

        rank = rank_for(user) if user else {"name": "Warrior", "tier": "Beginner", "key": "warrior"}
        image = welcome_media(sess)
        if user:
            await message.answer_photo(
                BufferedInputFile(image, "welcome.png"),
                caption=welcome_text(sess),
            )
            await send_menu(message, sm)
            if payload.startswith("bet_") and payload[4:].isdigit():
                from app.bot_games import ask_rank_amount_message
                await ask_rank_amount_message(message, sm, state, int(payload[4:]))
            return
        # new user -> register
        cb = "reg" if not payload else f"reg:{payload[:32]}"
        await message.answer_photo(
            BufferedInputFile(image, "welcome.png"),
            caption=welcome_text(sess),
            reply_markup=kb([[{"t": "🚀 Register to MLPlay", "cb": cb}]]),
        )
    finally:
        sess.close()


def welcome_text(sess) -> str:
    return get_setting(sess, "welcome_text", "") or (
        "⚡ **WELCOME TO THE MLPLAY ARENA!** ⚡\n\n"
        "Register now and start your journey to legend status! 🏆")


def welcome_media(sess) -> bytes:
    path = get_setting(sess, "welcome_media_path", "") or ""
    if path:
        try:
            import os
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
        except Exception:
            pass
    return cards.welcome_card(is_new=True)


@router.callback_query(F.data == "menu")
async def cb_menu(cq: CallbackQuery, sm):
    await cq.answer()
    await send_menu(cq.message, sm)


@router.callback_query(F.data.startswith("reg"))
async def cb_register(cq: CallbackQuery, sm, state: FSMContext):
    await cq.answer()
    payload = cq.data.split(":", 1)[1] if ":" in cq.data else ""
    inviter_id = None
    if payload.startswith("ref_") and payload[4:].isdigit():
        inviter_id = int(payload[4:])
    if inviter_id == cq.from_user.id:
        inviter_id = None

    sess = sm()
    try:
        user = wallet.get_or_create_user(
            sess, cq.from_user.id, chat_id=cq.message.chat.id,
            tg_username=cq.from_user.username or "",
            tg_fullname=cq.from_user.full_name or "")
        if inviter_id and not user.inviter_tg_id:
            inviter = wallet.user_by_id(sess, inviter_id)
            if inviter:
                user.inviter_tg_id = inviter_id
                sess.commit()
        rank = rank_for(user)
        await cq.message.answer(
            f"🎉 **REGISTRATION COMPLETE!**\n\n"
            f"Welcome to the Arena, {esc(user.tg_fullname or 'Champion')}! ⚡\n"
            f"{RANK_EMOJI.get(rank['key'], '')} Your rank: **{rank['tier']} {rank['name']}**\n"
            f"💰 Starting balance: **₱0.00** (deposit to climb!)\n\n"
            f"🎁 Daily reward is waiting — don't forget to claim it!\n"
            f"🔥 Explore the menu below:")
        await send_menu(cq.message, sm)
    finally:
        sess.close()


# ------------------------------------------------------------- pages ------
@router.callback_query(F.data.startswith("pg:"))
async def cb_page(cq: CallbackQuery, sm):
    page = cq.data.split(":", 1)[1]
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        if not user:
            await cq.answer("Register first!")
            return
        await cq.answer()
        if page == "profile":
            await page_profile(cq, sess, user)
        elif page == "referral":
            await page_referral(cq, sess, user)
        elif page == "contact":
            await page_contact(cq, sess)
        elif page == "promo":
            await page_promo(cq, sess)
        elif page == "games":
            from app.bot_games import page_games
            await page_games(cq, sess, user)
    finally:
        sess.close()


async def page_profile(cq: CallbackQuery, sess, user: User):
    rank = rank_for(user)
    invited, valid = wallet._invite_stats(sess, user)
    type_label = "ADMIN" if is_admin_tg(sess, user.tg_id) else "PLAYER"
    inviter = wallet.user_by_id(sess, user.inviter_tg_id) if user.inviter_tg_id else None
    bu = get_setting(sess, "bot_username", "")
    ref = f"https://t.me/{bu}?start=ref_{user.tg_id}" if bu else f"tg://openmessage?user_id={user.tg_id}"
    bind_label = ""
    if user.bind_account:
        bind_label = f"{user.bind_name or ''} • {user.bind_account}"
    card = cards.profile_card(
        fullname=user.tg_fullname or (f"Player {user.tg_id}"),
        username=user.tg_username or "",
        rank=rank,
        balance=user.balance or 0, turnover=user.turnover or 0,
        rewards=user.total_rewards or 0, deposited=user.total_deposit or 0,
        withdrawn=user.total_withdraw or 0, valid_bets=user.valid_bets or 0,
        joined=(user.joined_at.strftime("%Y-%m-%d") if user.joined_at else "-"),
        type_label=type_label,
        inviter=inviter.tg_fullname or f"@{inviter.tg_username}" if inviter else "",
        ref_link=ref, frozen=user.balance_frozen, bind_label=bind_label)
    base = wb_url(sess)
    buttons = [
        [{"t": "💰 Deposit", "wa": f"{base}/mini#deposit"}, {"t": "💸 Withdraw", "wa": f"{base}/mini#withdraw"}],
        [{"t": "🎁 Enter Promo Code", "wa": f"{base}/mini#promo"}, {"t": "🧾 Transaction History", "wa": f"{base}/mini#history"}],
    ]
    if not user.bind_account:
        buttons.append([{"t": "🏦 Bind Wallet/Bank  (+₱30)", "cb": "bind:start"}])
    buttons.append([{"t": "◀️ Back", "cb": "menu"}])
    caption = (
        f"👤 **YOUR PROFILE** — {esc(user.tg_fullname or '')}\n"
        f"{RANK_EMOJI.get(rank['key'], '')} Rank: **{rank['tier']} {rank['name']}**\n"
        f"💰 Balance: **₱{user.balance:,.2f}**\n"
        + (f"🏦 Wallet: **{esc(user.bind_name or '')} • {esc(user.bind_account)}**\n" if user.bind_account else "🏦 Wallet: not bound yet — bind & get ₱30!\n")
        + f"\n👇 Deposit, withdraw or track your history!"
    )
    await cq.message.answer_photo(BufferedInputFile(card, "profile.png"), caption=caption,
                                  reply_markup=kb(buttons))


# ----------------------------------------------------------- bind wallet --
@router.callback_query(F.data == "bind:start")
async def bind_start(cq: CallbackQuery, sm, state: FSMContext):
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        if not user:
            await cq.answer("Register first!")
            return
        if user.bind_account:
            await cq.answer()
            await cq.message.answer("🔒 You already bound your wallet — binding can only be set up once. (Admins can update it.)")
            return
        bind_bonus = float(get_setting(sess, "bind_bonus", 30.0) or 0)
        await state.set_state(BindFSM.name)
        await cq.answer()
        buttons = [[{"t": "💚 GCash", "cb": "bind:pty:GCash"},
                    {"t": "🟠 Maya", "cb": "bind:pty:Maya"}],
                   [{"t": "🏦 Bank / Other", "cb": "bind:pty:Bank / Other"}],
                   [{"t": "✖️ Cancel", "cb": "cancel"}]]
        await cq.message.answer(
            f"🏦 **BIND YOUR WALLET/BANK** 🔗\n\n"
            f"Earn a **+₱{bind_bonus:,.2f}** bonus for binding! 🎁\n\n"
            f"1️⃣ First, choose your wallet or bank type 👇",
            reply_markup=kb(buttons))
    finally:
        sess.close()


@router.callback_query(F.data.startswith("bind:pty:"))
async def bind_type_cb(cq: CallbackQuery, sm, state: FSMContext):
    name = cq.data.split(":", 2)[2]
    await state.set_state(BindFSM.account)
    await state.update_data(bind_name=name)
    await cq.answer()
    await cq.message.answer(
        f"🏦 **{esc(name)}** selected!\n\n"
        f"2️⃣ Type your **account / wallet number** 👇 (e.g. `0917 123 4567`)",
        reply_markup=kb([[{"t": "✖️ Cancel", "cb": "cancel"}]]))


@router.message(BindFSM.name)
async def bind_name_typed(msg: Message, sm, state: FSMContext):
    name = (msg.text or "").strip()[:120]
    if not name:
        await msg.answer("Please type your wallet/bank name.")
        return
    await state.set_state(BindFSM.account)
    await state.update_data(bind_name=name)
    await msg.answer(
        f"🏦 **{esc(name)}** noted!\n\n"
        f"2️⃣ Type your **account / wallet number** 👇",
        reply_markup=kb([[{"t": "✖️ Cancel", "cb": "cancel"}]]))


@router.message(BindFSM.account)
async def bind_account_typed(msg: Message, sm, state: FSMContext):
    account = (msg.text or "").strip()[:120]
    if len(account) < 3:
        await msg.answer("⚠️ That account number looks too short — please type it again.")
        return
    await state.update_data(bind_account=account)
    await state.set_state(BindFSM.holder)
    await msg.answer(
        f"3️⃣ Almost done! Type the **account holder name** 👇\n"
        f"(the name registered on this account)",
        reply_markup=kb([[{"t": "✖️ Cancel", "cb": "cancel"}]]))


@router.message(BindFSM.holder)
async def bind_holder_typed(msg: Message, sm, state: FSMContext):
    holder = (msg.text or "").strip()[:120]
    if len(holder) < 2:
        await msg.answer("⚠️ Please type the real account holder name.")
        return
    data = await state.get_data()
    await state.clear()
    sess = sm()
    try:
        user = wallet.user_by_id(sess, msg.from_user.id)
        if not user:
            await msg.answer("Register first!")
            return
        bonus, err = wallet.bind_wallet(sess, user,
                                        data.get("bind_name", ""),
                                        data.get("bind_account", ""),
                                        holder)
        if err:
            await msg.answer(err)
        else:
            await msg.answer(f"✅ **WALLET BOUND!** 🎉 +₱{bonus:,.2f} bonus credited.")
    finally:
        sess.close()


async def page_referral(cq: CallbackQuery, sess, user: User):
    rank = rank_for(user)
    invited, valid = wallet._invite_stats(sess, user)
    bu = get_setting(sess, "bot_username", "")
    ref = f"https://t.me/{bu}?start=ref_{user.tg_id}" if bu else f"tg://openmessage?user_id={user.tg_id}"
    top5 = wallet.top_referrers(sess, 5)
    card = cards.referral_card(rank["name"], user.referral_balance or 0, invited, valid, ref, top5)
    buttons = [
        [{"t": "📋 Copy Link", "cb": "rf:cp"}, {"t": "📣 Copy Link w/ Text", "cb": "rf:cpt"}],
        [{"t": "🔄 Convert Rewards to Balance", "cb": "rf:cv"}],
        [{"t": "◀️ Back", "cb": "menu"}],
    ]
    caption = (
        f"🔗 **REFERRAL PROGRAM**\n\n"
        f"💰 Rewards balance: **₱{user.referral_balance:,.2f}**\n"
        f"👥 Invites: **{invited}**  •  ✅ Valid: **{valid}**\n\n"
        f"🤝 Earn up to **{get_setting(sess, 'referral_pct', 5):g}%** of your invitee's first deposit!\n"
        f"🏆 Top 5 referrers get the spotlight!"
    )
    await cq.message.answer_photo(BufferedInputFile(card, "referral.png"), caption=caption,
                                  reply_markup=kb(buttons))


@router.callback_query(F.data.startswith("rf:"))
async def cb_referral_actions(cq: CallbackQuery, sm):
    action = cq.data.split(":", 1)[1]
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        if not user:
            await cq.answer("Register first!")
            return
        bu = get_setting(sess, "bot_username", "")
        ref = f"https://t.me/{bu}?start=ref_{user.tg_id}" if bu else f"tg://openmessage?user_id={user.tg_id}"
        if action == "cp":
            await cq.answer()
            await cq.message.answer(
                f"📋 **YOUR REFERRAL LINK**\n\n`{ref}`\n\n"
                f"Share it with friends — they register & deposit, you earn! 🤝")
        elif action == "cpt":
            await cq.answer()
            text = get_setting(sess, "referral_text", "") or (
                "🎮 Ready to join the MLPlay Arena? Register now and let's dominate! 💥\n{link}")
            promo = text.replace("{link}", ref)
            await cq.message.answer(promo)
        elif action == "cv":
            amt, err = wallet.convert_referral(sess, user)
            if err:
                await cq.answer()
                await cq.message.answer(err)
            else:
                await cq.answer("Converted! 🎉")
    finally:
        sess.close()


async def page_contact(cq: CallbackQuery, sess):
    g = get_setting(sess, "csr_group", "")
    ch = get_setting(sess, "csr_channel", "")
    c1, c2, c3 = (get_setting(sess, k, "") for k in ("csr1", "csr2", "csr3"))
    buttons = []
    if g:
        buttons.append([{"t": "👥 Official Group", "u": g}])
    if ch:
        buttons.append([{"t": "📢 Official Channel", "u": ch}])
    for i, url in enumerate((c1, c2, c3), 1):
        if url:
            buttons.append([{"t": f"🎧 CSR {i}", "u": url}])
    buttons.append([{"t": "◀️ Back", "cb": "menu"}])
    from app.cards import banner_card
    img = banner_card("CONTACT SERVICES", "We're always here for you!", (34, 211, 238), "📞")
    await cq.message.answer_photo(
        BufferedInputFile(img, "contact.png"),
        caption="📞 **NEED HELP?**\n\nOur support team is ready 24/7!\n👇 Tap to connect:",
        reply_markup=kb(buttons))


async def page_promo(cq: CallbackQuery, sess):
    base = wb_url(sess)
    buttons = [
        [{"t": "🎁 Open Promotions", "wa": f"{base}/mini#promotions"}],
        [{"t": "◀️ Back", "cb": "menu"}],
    ]
    from app.cards import banner_card
    img = banner_card("PROMOTIONS", "Bonuses, events, giveaways!", (251, 191, 36), "🎁")
    await cq.message.answer_photo(
        BufferedInputFile(img, "promo.png"),
        caption="🎁 **PROMOTIONS & GIVEAWAYS!**\n\n"
                "Exclusive bonuses, promo codes and events are waiting!\n"
                "👇 Tap to open the Promotions page:",
        reply_markup=kb(buttons))


# ----------------------------------------------------------- daily --------
@router.callback_query(F.data == "dly")
async def cb_daily(cq: CallbackQuery, sm):
    sess = sm()
    try:
        user = wallet.user_by_id(sess, cq.from_user.id)
        if not user:
            await cq.answer("Register first!")
            return
        amt, err = wallet.daily_claim(sess, user)
        if err:
            await cq.answer()
            await cq.message.answer(err)
        else:
            await cq.answer(f"Claimed ₱{amt:,.2f}! 🎉")
    finally:
        sess.close()


@router.callback_query(F.data == "cancel")
async def cb_cancel(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.answer()
    await cq.message.answer("❌ Cancelled.")