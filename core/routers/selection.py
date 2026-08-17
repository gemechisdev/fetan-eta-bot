import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from core.deeplink import build_reserve_payload
from core.keyboards import build_number_grid
from core import config as core_config
from db import repository as repo
from services import round_service

logger = logging.getLogger("fetan-eta.selection")

router = Router(name="selection")


def _deep_link_url(bot_username: str, chat_id: int, round_number: int, number: int, user_id: int) -> str:
    payload = build_reserve_payload(chat_id, round_number, number, user_id)
    return f"https://t.me/{bot_username}?start={payload}"


@router.callback_query(F.data.startswith("num:"))
async def on_number_tap(callback: CallbackQuery, bot: Bot):
    """Every tap on an *available* number opens the tapper's own private chat
    with the bot (via the `url` field of answerCallbackQuery, which Telegram
    treats as a t.me deep link — see core/deeplink.py) so the reservation and
    payment instructions land straight in their DM. That's the only way a
    bot can reliably reach a user who hasn't started it yet, and it's
    inherently exclusive: Telegram opens *that tapper's own* client, so
    there's no shared/public button anyone else could tap on their behalf.

    - Available number  -> open DM, /start reserves it there (see
      core/routers/common.py) and shows payment instructions.
    - Pending, owned by the tapper -> deselect instantly, in-group (no need
      to bounce through the DM just to cancel your own selection).
    - Pending, owned by someone else / already reserved -> just a quick
      alert in-group with the status. No DM — the number can't be taken
      anyway, so opening a chat for it would just waste a tap.
    """
    _, round_number_str, number_str = callback.data.split(":")
    number = int(number_str)
    chat_id = callback.message.chat.id
    user = callback.from_user

    # Expire old pending reservations so users don't get stuck behind a
    # no-show — do this before reading status so the check below is fresh.
    try:
        active = await repo.get_active_round(chat_id)
        if active:
            await repo.expire_pending_reservations(active["_id"], core_config.RESERVATION_TTL_MINUTES)
    except Exception:
        logger.exception("expire_pending_reservations failed for chat_id=%s", chat_id)

    fresh_round = await repo.get_active_round(chat_id)
    if not fresh_round or fresh_round["round_number"] != int(round_number_str):
        await callback.answer("ይህ ዙር አብቅቷል።", show_alert=True)
        return

    number_doc = next((n for n in fresh_round["numbers"] if n["number"] == number), None)
    if not number_doc:
        await callback.answer("ልክ ያልሆነ ቁጥር።", show_alert=True)
        return

    status = number_doc.get("status")
    owner_id = number_doc.get("telegram_id")

    if status == "available":
        me = await bot.get_me()
        url = _deep_link_url(me.username, chat_id, fresh_round["round_number"], number, user.id)
        await callback.answer(f"ቁጥር {number:02d}ን ለመያዝ የግል መልዕክትዎን በመክፈት ላይ…", url=url)

    elif status == "pending" and owner_id == user.id:
        # Owner tapping their own pending number = deselect. Handled
        # instantly in-group; no DM round-trip needed just to cancel.
        await round_service.cancel_selection(fresh_round, number)
        try:
            await repo.release_number(fresh_round["_id"], number)
        except Exception:
            pass
        await callback.answer(f"የቁጥር {number:02d} ምርጫ ተሰርዟል።")
        try:
            dm_text = await round_service.build_reservation_summary_text(fresh_round["_id"], user.id)
            await bot.send_message(user.id, dm_text)
        except Exception:
            pass

    elif status == "pending":
        # Already taken by someone else — just say so. No point opening a
        # DM for a number that can't be reserved anyway; that's wasted taps.
        who = number_doc.get("display_name") or number_doc.get("username") or "ሌላ ተጫዋች"
        await callback.answer(
            f"🟡 ቁጥር {number:02d} በመጠባበቅ ላይ ነው — በ{who} ተይዟል። ሌላ ቁጥር ይምረጡ።",
            show_alert=True,
        )

    else:
        # reserved (confirmed/green) or any other final state — same idea,
        # just inform them in-group, no DM needed.
        who = number_doc.get("display_name") or number_doc.get("username") or "ሌላ ተጫዋች"
        await callback.answer(
            f"🟢 ቁጥር {number:02d} አስቀድሞ በ{who} ተይዟል።",
            show_alert=True,
        )

    # Refresh the board markup
    fresh2 = await repo.get_active_round(chat_id)
    if fresh2:
        try:
            board_id = fresh2.get("message_refs", {}).get("board_message_id")
            target_message_id = board_id if board_id else callback.message.message_id
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=target_message_id,
                reply_markup=build_number_grid(fresh2),
            )
        except Exception:
            pass
        