from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from core import config as core_config
from core.deeplink import parse_reserve_payload
from core.i18n import SUPPORTED_LANGS, t
from core.keyboards import build_language_kb
from db import repository as repo
from services.reservation_flow import reserve_number_and_notify
from services import round_service

import logging

logger = logging.getLogger("fetan-eta.common")

router = Router(name="common")


@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, bot: Bot):
    lang = await repo.get_chat_language(message.chat.id)
    parsed = parse_reserve_payload(command.args)
    if not parsed:
        await message.answer(t(lang, "welcome"))
        return

    # This /start came from tapping a number in the group (see
    # core/routers/selection.py + core/deeplink.py). The link is generated
    # fresh per-tap and carries exactly who it's for — verify that before
    # doing anything, so a link that ends up in someone else's hands (e.g.
    # forwarded, or the same deep link is naively re-tapped by an alert
    # dialog on someone else's device) can't reserve on their behalf.
    if parsed["user_id"] != message.from_user.id:
        await message.answer(t(lang, "link_not_yours"))
        return

    await _start_and_reserve(message, bot, parsed, lang)


async def _start_and_reserve(message: Message, bot: Bot, parsed: dict, lang: str):
    chat_id = parsed["chat_id"]
    round_number = parsed["round_number"]
    number = parsed["number"]

    round_doc = await repo.get_active_round(chat_id)
    if not round_doc or round_doc["round_number"] != round_number:
        await message.answer(t(lang, "welcome") + t(lang, "round_closed_suffix"))
        return

    try:
        await repo.expire_pending_reservations(round_doc["_id"], core_config.RESERVATION_TTL_MINUTES)
    except Exception:
        logger.exception("expire_pending_reservations failed for round_id=%s", round_doc["_id"])
    round_doc = await repo.get_active_round(chat_id)

    number_doc = next((n for n in round_doc["numbers"] if n["number"] == number), None)
    if not number_doc:
        await message.answer(t(lang, "welcome"))
        return

    status = number_doc.get("status")
    owner_id = number_doc.get("telegram_id")

    if status == "available":
        result = await reserve_number_and_notify(bot, round_doc, number, message.from_user, lang)
        if result["status"] == "reserved":
            await message.answer(t(lang, "number_reserved_for_you", number=f"{number:02d}"))
            await round_service.refresh_board(bot, chat_id)
        elif result["status"] == "taken":
            await message.answer(result["message"])
        else:
            # Extremely unlikely here (we're already inside the DM that would
            # have failed), but handle it gracefully just in case.
            await message.answer(t(lang, "reserve_generic_error"))
        return

    if owner_id == message.from_user.id:
        if status == "pending":
            await message.answer(t(lang, "you_already_hold_pending", number=f"{number:02d}"))
        else:
            await message.answer(t(lang, "you_own_confirmed", number=f"{number:02d}"))
        return

    who = number_doc.get("display_name") or number_doc.get("username") or t(lang, "other_player")
    if status == "pending":
        await message.answer(t(lang, "number_pending_other", number=f"{number:02d}", who=who))
    else:
        await message.answer(t(lang, "number_reserved_other", number=f"{number:02d}", who=who))


@router.message(Command("help"))
async def cmd_help(message: Message):
    lang = await repo.get_chat_language(message.chat.id)
    await message.answer(t(lang, "help"))


@router.message(Command("language", "lang"))
async def cmd_language(message: Message):
    lang = await repo.get_chat_language(message.chat.id)
    await message.answer(t(lang, "choose_language"), reply_markup=build_language_kb())


@router.callback_query(F.data.startswith("setlang:"))
async def on_set_language(callback: CallbackQuery):
    _, code = callback.data.split(":", 1)
    if code not in SUPPORTED_LANGS:
        await callback.answer()
        return

    chat = callback.message.chat
    # Groups affect everyone in them, so only admins may change the group's
    # language. Private chats are the user's own, so no restriction there.
    if chat.type != "private" and not await repo.is_user_admin(callback.from_user.id):
        current_lang = await repo.get_chat_language(chat.id)
        await callback.answer(t(current_lang, "language_admin_only"), show_alert=True)
        return

    await repo.set_chat_language(chat.id, code)
    from core.i18n import language_display_name

    await callback.answer()
    try:
        await callback.message.edit_text(t(code, "language_set", language=language_display_name(code, code)))
    except Exception:
        await callback.message.answer(t(code, "language_set", language=language_display_name(code, code)))
