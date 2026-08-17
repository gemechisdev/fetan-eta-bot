from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from core import config as core_config
from core.deeplink import parse_reserve_payload
from core.texts import HELP, WELCOME
from db import repository as repo
from services.reservation_flow import reserve_number_and_notify
from services import round_service

import logging

logger = logging.getLogger("fetan-eta.common")

router = Router(name="common")


@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, bot: Bot):
    parsed = parse_reserve_payload(command.args)
    if not parsed:
        await message.answer(WELCOME)
        return

    # This /start came from tapping a number in the group (see
    # core/routers/selection.py + core/deeplink.py). The link is generated
    # fresh per-tap and carries exactly who it's for — verify that before
    # doing anything, so a link that ends up in someone else's hands (e.g.
    # forwarded, or the same deep link is naively re-tapped by an alert
    # dialog on someone else's device) can't reserve on their behalf.
    if parsed["user_id"] != message.from_user.id:
        await message.answer(
            "🚫 ይህ የምዝገባ ሊንክ የእርስዎ አይደለም — ለሌላ ተጫዋች ጠቅ ማድረግ የተፈጠረ ነው።\n\n"
            "ወደ ግሩፑ በመሄድ እርስዎ ራስዎ ነጻ የሆነ ቁጥር ይንኩ እና ይምረጡ።"
        )
        return

    await _start_and_reserve(message, bot, parsed)


async def _start_and_reserve(message: Message, bot: Bot, parsed: dict):
    chat_id = parsed["chat_id"]
    round_number = parsed["round_number"]
    number = parsed["number"]

    round_doc = await repo.get_active_round(chat_id)
    if not round_doc or round_doc["round_number"] != round_number:
        await message.answer(
            WELCOME + "\n\nይህ ዙር ከእንግዲህ ክፍት አይደለም — ወደ ግሩፑ በመመለስ በአሁኑ ጊዜ የሚገኝ ቁጥር ይንኩ።"
        )
        return

    try:
        await repo.expire_pending_reservations(round_doc["_id"], core_config.RESERVATION_TTL_MINUTES)
    except Exception:
        logger.exception("expire_pending_reservations failed for round_id=%s", round_doc["_id"])
    round_doc = await repo.get_active_round(chat_id)

    number_doc = next((n for n in round_doc["numbers"] if n["number"] == number), None)
    if not number_doc:
        await message.answer(WELCOME)
        return

    status = number_doc.get("status")
    owner_id = number_doc.get("telegram_id")

    if status == "available":
        result = await reserve_number_and_notify(bot, round_doc, number, message.from_user)
        if result["status"] == "reserved":
            await message.answer(f"👋 እንኳን ደህና መጡ! ቁጥር {number:02d} ለእርስዎ ተይዟል — ከላይ የክፍያ መረጃውን ይመልከቱ ⬆️")
            await round_service.refresh_board(bot, chat_id)
        elif result["status"] == "taken":
            await message.answer(result["message"])
        else:
            # Extremely unlikely here (we're already inside the DM that would
            # have failed), but handle it gracefully just in case.
            await message.answer(
                "ያንን ቁጥር በመያዝ ላይ ችግር ተፈጥሯል። እባክዎ ወደ ግሩፑ ተመልሰው ቁጥሩን እንደገና ይንኩ።"
            )
        return

    if owner_id == message.from_user.id:
        if status == "pending":
            await message.answer(
                f"ቁጥር {number:02d}ን አስቀድመው ይዘዋል — የክፍያ መረጃውን ከላይ ይመልከቱ 👆"
            )
        else:
            await message.answer(f"🎉 ቁጥር {number:02d} የእርስዎ መሆኑ ተረጋግጧል!")
        return

    who = number_doc.get("display_name") or number_doc.get("username") or "ሌላ ተጫዋች"
    if status == "pending":
        await message.answer(
            f"🟡 ቁጥር {number:02d} በአሁኑ ጊዜ በመጠባበቅ ላይ ነው — {who} ከእርስዎ በፊት ነክቶታል እና ክፍያውን እያጠናቀቀ ነው። "
            "ወደ ግሩፑ ተመልሰው ሌላ ቁጥር ይምረጡ 👇"
        )
    else:
        await message.answer(
            f"🟢 ቁጥር {number:02d} አስቀድሞ በ{who} ተይዟል። ወደ ግሩፑ ተመልሰው ሌላ ቁጥር ይምረጡ 👇"
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP)
    