from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from core.keyboards import build_number_grid
from core.texts import PAYMENT_INSTRUCTIONS
from db import repository as repo
from services import round_service

router = Router(name="selection")


@router.callback_query(F.data.startswith("num:"))
async def on_number_tap(callback: CallbackQuery, bot: Bot):
    _, round_number_str, number_str = callback.data.split(":")
    number = int(number_str)
    chat_id = callback.message.chat.id

    round_doc = await repo.get_active_round(chat_id)
    if not round_doc or round_doc["round_number"] != int(round_number_str):
        await callback.answer("This round has ended.", show_alert=True)
        return

    user = callback.from_user
    payment, error = await round_service.select_number(round_doc, number, user.id, user.username)

    if error:
        await callback.answer(error, show_alert=True)
        fresh = await repo.get_active_round(chat_id)
        if fresh:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=callback.message.message_id,
                reply_markup=build_number_grid(fresh),
            )
        return

    await callback.answer(f"Number {number} reserved! Check your DM to pay.")

    fresh = await repo.get_active_round(chat_id)
    await bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=callback.message.message_id,
        reply_markup=build_number_grid(fresh),
    )

    try:
        await bot.send_message(
            user.id,
            PAYMENT_INSTRUCTIONS.format(number=number, amount=round_doc["config"]["ticket_price"]),
        )
    except Exception:
        # User hasn't opened a private chat with the bot yet — release the
        # number so it doesn't sit locked forever.
        await round_service.cancel_selection(round_doc, number)
        await bot.send_message(
            chat_id,
            f"@{user.username or user.id}, please start a private chat with me first "
            f"(search the bot and press Start), then tap the number again.",
        )
        fresh2 = await repo.get_active_round(chat_id)
        if fresh2:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=callback.message.message_id,
                reply_markup=build_number_grid(fresh2),
            )
