from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from core.config import ADMIN_IDS
from core.keyboards import build_number_grid, build_review_kb
from core.texts import build_board_text
from db import repository as repo
from services import draw_service, round_service

router = Router(name="admin")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.message(Command("newround"))
async def cmd_newround(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    try:
        price = int(parts[1])
        prizes = [int(parts[2]), int(parts[3]), int(parts[4])]
        total_numbers = int(parts[5]) if len(parts) > 5 else 20
    except (IndexError, ValueError):
        await message.answer("Usage: /newround price prize1 prize2 prize3 [total_numbers]")
        return

    round_doc, error = await round_service.start_new_round(message.chat.id, price, prizes, total_numbers)
    if error:
        await message.answer(error)
        return

    board_msg = await message.answer(
        build_board_text(round_doc),
        reply_markup=build_number_grid(round_doc),
    )
    await repo.set_board_message_id(round_doc["_id"], board_msg.message_id)


@router.message(Command("closeregistration"))
async def cmd_close(message: Message):
    if not is_admin(message.from_user.id):
        return

    round_doc = await repo.get_active_round(message.chat.id)
    if not round_doc or round_doc["status"] != "registration_open":
        await message.answer("No open round to close.")
        return

    await round_service.close_registration(round_doc)
    await message.answer("Registration closed. Run /startdraw when ready.")


@router.message(Command("startdraw"))
async def cmd_startdraw(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    round_doc = await repo.get_active_round(message.chat.id)
    if not round_doc or round_doc["status"] != "registration_closed":
        await message.answer("Close registration first with /closeregistration.")
        return

    results, error = await draw_service.commit_and_draw(round_doc, bot, message.chat.id)
    if error:
        await message.answer(error)
        return

    # Reflect winning numbers on the original board keyboard too.
    fresh = await repo.get_round(round_doc["_id"])
    board_id = fresh["message_refs"].get("board_message_id")
    if board_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=message.chat.id, message_id=board_id, reply_markup=build_number_grid(fresh)
            )
        except Exception:
            pass

    for r in results:
        try:
            await bot.send_message(
                r["telegram_id"],
                f"🎉 You won {r['prize']} ETB (place #{r['place']}, number {r['number']:02d})!\n"
                f"Reply here with your payout account (Telebirr/CBE/bank) to claim it.",
            )
        except Exception:
            pass


@router.message(Command("pending"))
async def cmd_pending(message: Message):
    if not is_admin(message.from_user.id):
        return

    round_doc = await repo.get_active_round(message.chat.id)
    if not round_doc:
        await message.answer("No active round.")
        return

    pending = await repo.get_pending_payments(round_doc["_id"])
    if not pending:
        await message.answer("No payments awaiting review.")
        return

    for p in pending:
        await message.answer(
            f"Number {p['number']:02d} — @{p.get('username') or p['telegram_id']} — {p['amount']} ETB",
            reply_markup=build_review_kb(str(p["_id"])),
        )


@router.message(Command("cancelround"))
async def cmd_cancel(message: Message):
    if not is_admin(message.from_user.id):
        return

    round_doc = await repo.get_active_round(message.chat.id)
    if not round_doc:
        await message.answer("No active round.")
        return

    await repo.set_round_status(round_doc["_id"], "cancelled")
    await message.answer(f"Round #{round_doc['round_number']} cancelled.")


@router.message(Command("payout"))
async def cmd_payout(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    try:
        round_number = int(parts[1])
        telegram_id = int(parts[2])
    except (IndexError, ValueError):
        await message.answer("Usage: /payout round_number telegram_id")
        return

    round_doc = await repo.get_round_by_number(message.chat.id, round_number)
    if not round_doc:
        await message.answer("Round not found.")
        return

    await repo.mark_payout_paid(round_doc["_id"], telegram_id)
    await message.answer("Marked as paid ✅")
    try:
        await bot.send_message(telegram_id, "✅ Your prize has been paid out. Thank you for playing Fetan Eta!")
    except Exception:
        pass


@router.callback_query(F.data.startswith("rev:"))
async def on_review(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Admins only.", show_alert=True)
        return

    _, action, payment_id = callback.data.split(":")
    payment = await repo.get_payment(payment_id)
    if not payment or payment["status"] != "awaiting_review":
        await callback.answer("Already handled.", show_alert=True)
        return

    if action == "approve":
        await round_service.approve_payment(payment, callback.from_user.id)
        await callback.answer("Approved ✅")
        try:
            await bot.send_message(
                payment["telegram_id"],
                f"✅ Your payment for number {payment['number']:02d} was approved. You're in!",
            )
        except Exception:
            pass
    else:
        await round_service.reject_payment(payment, callback.from_user.id)
        await callback.answer("Rejected ❌")
        try:
            await bot.send_message(
                payment["telegram_id"],
                f"❌ Your payment for number {payment['number']:02d} was rejected. "
                f"The number is available again.",
            )
        except Exception:
            pass

    fresh = await repo.get_round(payment["round_id"])
    board_id = fresh["message_refs"].get("board_message_id") if fresh else None
    if fresh and board_id:
        try:
            await bot.edit_message_text(
                build_board_text(fresh), chat_id=fresh["chat_id"], message_id=board_id
            )
            await bot.edit_message_reply_markup(
                chat_id=fresh["chat_id"], message_id=board_id, reply_markup=build_number_grid(fresh)
            )
        except Exception:
            pass

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
