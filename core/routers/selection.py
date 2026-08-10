from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from core.keyboards import build_number_grid
from core.texts import PAYMENT_INSTRUCTIONS
from core import config as core_config
from db import repository as repo
from services import round_service

router = Router(name="selection")


@router.callback_query(F.data.startswith("num:"))
async def on_number_tap(callback: CallbackQuery, bot: Bot):
    _, round_number_str, number_str = callback.data.split(":")
    number = int(number_str)
    chat_id = callback.message.chat.id

    # Expire old pending reservations so users don't get stuck.
    try:
        await repo.expire_pending_reservations((await repo.get_active_round(chat_id))["_id"], core_config.RESERVATION_TTL_MINUTES)
    except Exception:
        pass

    fresh_round = await repo.get_active_round(chat_id)
    if not fresh_round or fresh_round["round_number"] != int(round_number_str):
        await callback.answer("This round has ended.", show_alert=True)
        return

    # Find the number's current state
    number_doc = next((n for n in fresh_round["numbers"] if n["number"] == number), None)
    if not number_doc:
        await callback.answer("Invalid number.", show_alert=True)
        return

    user = callback.from_user
    display_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

    # Toggle behavior:
    # - If available -> try to reserve
    # - If pending and reserved by same user -> cancel (deselect)
    # - If pending and reserved by someone else -> inform
    # - If reserved -> cannot change
    status = number_doc.get("status")
    owner_id = number_doc.get("telegram_id")

    if status == "available":
        payment, error = await round_service.select_number(fresh_round, number, user.id, user.username, display_name=display_name)
        if error:
            await callback.answer(error, show_alert=True)
        else:
            await callback.answer(f"Number {number} reserved! Check your DM to pay.")
            try:
                pending_payments = await repo.get_awaiting_proof_payments_for_round_user(fresh_round["_id"], user.id)
                seen = set()
                numbers_list = []
                total = 0
                for p in pending_payments:
                    num = p["number"]
                    if num not in seen:
                        seen.add(num)
                        numbers_list.append(f"{num:02d}")
                    total += p["amount"]
                numbers = ", ".join(numbers_list)
                dm_text = (
                    f"You reserved number(s): {numbers}.\n\n"
                    f"Total: {total} ETB\n\n"
                    "Pay to:\n"
                    "Telebirr: 09xxxxxxxx\n"
                    "CBE: 100xxxxxxxx\n\n"
                    "After paying, send a screenshot of the payment OR type the transaction ID here."
                )
                await bot.send_message(user.id, dm_text)
            except Exception:
                # DM failed: cancel selection and inform in group
                await round_service.cancel_selection(fresh_round, number)
                user_ref = f"@{user.username}" if user.username else f"id:{user.id}"
                await bot.send_message(
                    chat_id,
                    f"{user.first_name or user_ref} ({user_ref}), please start a private chat with the bot first "
                    f"(search @{(await bot.get_me()).username} and press Start), then tap the number again.",
                )
            else:
                # After successful reservation DM, nothing more to do here
                pass

    elif status == "pending":
        if owner_id == user.id:
            # Deselect / cancel the pending reservation
            await round_service.cancel_selection(fresh_round, number)
            # Force-release as a safety net to ensure DB reflects cancellation
            try:
                await repo.release_number(fresh_round["_id"], number)
            except Exception:
                pass
            await callback.answer(f"Selection {number} cancelled.")
            # Send updated DM summarizing current awaiting payments for this user
            try:
                pending_payments = await repo.get_awaiting_proof_payments_for_round_user(fresh_round["_id"], user.id)
                seen = set()
                numbers_list = []
                total = 0
                for p in pending_payments:
                    num = p["number"]
                    if num not in seen:
                        seen.add(num)
                        numbers_list.append(f"{num:02d}")
                    total += p["amount"]
                numbers = ", ".join(numbers_list) if numbers_list else "(none)"
                dm_text = (
                    f"You reserved number(s): {numbers}.\n\n"
                    f"Total: {total} ETB\n\n"
                    "Pay to:\n"
                    "Telebirr: 09xxxxxxxx\n"
                    "CBE: 100xxxxxxxx\n\n"
                    "After paying, send a screenshot of the payment OR type the transaction ID here."
                )
                await bot.send_message(user.id, dm_text)
            except Exception:
                pass
        else:
            who = number_doc.get("display_name") or number_doc.get("username") or f"id:{owner_id}"
            await callback.answer(f"That number is pending (reserved by {who}).", show_alert=True)

    else:
        # reserved or other final state
        await callback.answer("That number is already reserved and cannot be changed.", show_alert=True)

    # Refresh the board markup
    fresh2 = await repo.get_active_round(chat_id)
    if fresh2:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=callback.message.message_id,
                reply_markup=build_number_grid(fresh2),
            )
        except Exception:
            pass
