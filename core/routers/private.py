from aiogram import Bot, F, Router
from aiogram.types import Message

from core.config import ADMIN_IDS
from core.keyboards import build_review_kb
from core.texts import CLAIM_RECEIVED, NO_PENDING_ACTION, PROOF_RECEIVED, format_user_identity
from db import repository as repo

router = Router(name="private")


@router.message(F.chat.type == "private")
async def on_private_message(message: Message, bot: Bot):
    user = message.from_user

    # 1) Is this user a winner who still needs to submit payout details?
    claim_round = await repo.find_round_awaiting_claim_for_user(user.id)
    if claim_round and message.text:
        await repo.set_payout_account(claim_round["_id"], user.id, message.text.strip())
        await message.answer(CLAIM_RECEIVED)
        display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or None
        user_str = format_user_identity(display_name, user.username, user.id)
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    "💰 Payout details submitted\n"
                    f"Round #{claim_round['round_number']}\n"
                    f"User: {user_str}\n"
                    f"Account: {message.text.strip()}\n\n"
                    f"Mark as paid with:\n/payout {claim_round['round_number']} {user.id}",
                )
            except Exception:
                pass
        return

    # 2) Is this user mid-payment (needs to submit proof)?
    payment = await repo.get_awaiting_proof_payment_for_user(user.id)
    if payment:
        if message.photo:
            proof = {"type": "photo", "value": message.photo[-1].file_id}
        elif message.text:
            proof = {"type": "text", "value": message.text.strip()}
        else:
            await message.answer("Please send a payment screenshot or type your transaction ID.")
            return

        await repo.submit_proof(payment["_id"], proof)
        await message.answer(PROOF_RECEIVED.format(number=payment["number"]))

        display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or None
        user_str = format_user_identity(display_name, user.username, user.id)
        caption = (
            "🧾 New payment for review\n"
            f"Number: {payment['number']}\n"
            f"User: {user_str}\n"
            f"Amount: {payment['amount']} ETB"
        )
        kb = build_review_kb(str(payment["_id"]))
        for admin_id in ADMIN_IDS:
            try:
                if proof["type"] == "photo":
                    await bot.send_photo(admin_id, proof["value"], caption=caption, reply_markup=kb)
                else:
                    await bot.send_message(admin_id, caption + f"\nTx: {proof['value']}", reply_markup=kb)
            except Exception:
                pass
        return

    # 3) Nothing pending for this user right now.
    await message.answer(NO_PENDING_ACTION)
