from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from core.deeplink import build_reserve_payload
from core.keyboards import build_number_grid, build_start_and_reserve_kb
from core.texts import PAYMENT_INSTRUCTIONS
from core import config as core_config
from db import repository as repo
from services import round_service
from services.reservation_flow import reserve_number_and_notify

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
        result = await reserve_number_and_notify(bot, fresh_round, number, user)

        if result["status"] == "taken":
            await callback.answer(result["message"], show_alert=True)

        elif result["status"] == "dm_failed":
            # User hasn't started a private chat with the bot yet. Instead of
            # the old "search @bot, press Start, then tap the number again"
            # dance, give them a single button that opens the DM AND
            # reserves this exact number via a deep link (core/deeplink.py +
            # core/routers/common.py). No need to come back and tap again.
            await callback.answer(
                "Tap 'Start bot' below to open our DM and grab this number 👇",
                show_alert=True,
            )
            me = await bot.get_me()
            payload = build_reserve_payload(chat_id, fresh_round["round_number"], number)
            user_ref = f"@{user.username}" if user.username else (user.first_name or "there")
            await bot.send_message(
                chat_id,
                f"👋 {user_ref}, one tap and number {number:02d} is yours — "
                "this opens a private chat with me and reserves it instantly:",
                reply_markup=build_start_and_reserve_kb(me.username, payload, number),
            )

        else:  # "reserved"
            await callback.answer(f"Number {number} reserved! Check your DM to pay.")

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
                dm_text = await round_service.build_reservation_summary_text(fresh_round["_id"], user.id)
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
            # Prefer editing the stored board message if available so all users
            # see the same updated board. Fall back to the message where the
            # callback originated.
            board_id = fresh2.get("message_refs", {}).get("board_message_id")
            target_message_id = board_id if board_id else callback.message.message_id
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=target_message_id,
                reply_markup=build_number_grid(fresh2),
            )
        except Exception:
            pass

        # Debug: log current numbers and statuses to assist troubleshooting
        try:
            nums = [(n.get("number"), n.get("status"), n.get("telegram_id")) for n in fresh2["numbers"]]
            print(f"[DEBUG] callback.data={callback.data} parsed_number={number} refreshed_numbers_sample={nums[:10]}")
        except Exception:
            pass
