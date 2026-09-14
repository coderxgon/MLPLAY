"""
Telegram admin approvals — deposit & withdrawal requests posted to the
transaction group carry inline buttons (Approve / Reject / Reject+Ban).
Only admin IDs (set in the panel) can act; rejections require a remark.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import wallet
from app.models import Order
from app.notifier import esc
from app.settings_svc import is_admin_tg

logger = logging.getLogger("bot_admin")

router = Router()


class AdminFSM(StatesGroup):
    remark = State()


@router.callback_query(F.data.regexp(r"^(apd|apw|rjd|rjw|rbd|rbw):\d+$"))
async def on_admin_request(cq: CallbackQuery, sm, state: FSMContext):
    sess = sm()
    try:
        if not is_admin_tg(sess, cq.from_user.id):
            await cq.answer("⛔ You are not an MLPlay admin.")
            return
        action, _, oid_s = cq.data.partition(":")
        order = sess.get(Order, int(oid_s))
        if not order:
            await cq.answer("Request not found.")
            return
        if order.status != "pending":
            await cq.answer(f"Already {order.status}.")
            return
        admin_label = f"{cq.from_user.full_name or cq.from_user.id} (TG)"
        if action in ("apd", "apw"):
            if action == "apd":
                wallet.approve_deposit(sess, order, admin_label=admin_label)
            else:
                wallet.approve_withdraw(sess, order, admin_label=admin_label)
            await cq.answer("✅ Request approved!")
            await cq.message.edit_text(f"{cq.message.text}\n\n✅ **APPROVED by {esc(admin_label)}**")
        else:
            ban = action.startswith("rb")
            await state.set_state(AdminFSM.remark)
            await state.update_data(order_id=order.id, ban=ban, admin_label=admin_label)
            await cq.answer()
            await cq.message.answer(
                f"📝 **Remark required**\n\nSend one message with the reason "
                f"for {'rejecting & banning this request' if ban else 'rejecting this request'}.")
    finally:
        sess.close()


@router.message(AdminFSM.remark)
async def on_admin_remark(msg: Message, sm, state: FSMContext):
    sess = sm()
    try:
        if not is_admin_tg(sess, msg.from_user.id):
            await state.clear()
            return
        data = await state.get_data()
        await state.clear()
        order = sess.get(Order, int(data.get("order_id") or 0))
        if not order:
            await msg.answer("Request not found.")
            return
        remark = (msg.text or "").strip()[:400]
        ban = bool(data.get("ban"))
        admin_label = data.get("admin_label") or f"{msg.from_user.id} (TG)"
        if order.kind == "deposit":
            wallet.reject_deposit(sess, order, admin_label=admin_label, remark=remark, ban=ban)
        else:
            wallet.reject_withdraw(sess, order, admin_label=admin_label, remark=remark, ban=ban)
        await msg.answer("✅ Request rejected" + (" & user banned." if ban else "."))
    finally:
        sess.close()