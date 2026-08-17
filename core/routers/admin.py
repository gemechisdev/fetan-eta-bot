from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from core import config as core_config
from core.i18n import t
from core.keyboards import build_number_grid, build_review_kb
from core.texts import build_board_text, format_user_identity
from db import repository as repo
from services import draw_service, round_service
from services.user_identity import resolve_user_identity

router = Router(name="admin")


async def is_admin(user_id: int) -> bool:
    return await repo.is_user_admin(user_id)


def _parse_optional_chat_id(parts: list[str], current_chat_id: int, min_payload_args: int) -> tuple[int, list[str]]:
    """Return (target_chat_id, payload_parts).

    If the last token looks like a chat id and there are extra arguments beyond
    the required payload, treat it as an explicit target chat.
    """
    if len(parts) > min_payload_args:
        try:
            target_chat_id = int(parts[-1])
            return target_chat_id, parts[:-1]
        except ValueError:
            pass
    return current_chat_id, parts


def _format_draw_result_line(result: dict, lang: str) -> str:
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(result.get("place"), "🎖")
    who = format_user_identity(result.get("display_name"), result.get("username"), result.get("telegram_id"))
    return (
        f"{medal} #{result['place']}: {result['number']:02d} — {who} — {result['prize']} {t(lang, 'currency')}"
    )


def _resolve_round_chat_id(parts: list[str], current_chat_id: int, min_tokens_without_chat: int) -> tuple[int, list[str]]:
    """Resolve optional explicit chat_id for round commands.

    If the command is sent in PM, allow the final token to be a target chat id.
    `min_tokens_without_chat` is the minimum number of tokens a valid command
    must have before an explicit chat_id can be appended.
    """
    if current_chat_id < 0:
        return current_chat_id, parts

    # In private chat, accept the last token as an explicit target chat id.
    if len(parts) > min_tokens_without_chat:
        try:
            return int(parts[-1]), parts[:-1]
        except ValueError:
            pass
    return current_chat_id, parts


def _private_chat_id_required(message: Message, target_chat_id: int) -> bool:
    return message.chat.type == "private" and target_chat_id == message.chat.id


@router.message(Command("newround", "nr"))
async def cmd_newround(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    try:
        price = int(parts[1])
        if len(parts) < 4:
            raise ValueError("not enough arguments")
        if message.chat.type == "private" and parts[-1].startswith("-"):
            target_chat_id = int(parts[-1])
            total_numbers = int(parts[-2])
            prizes = [int(x) for x in parts[2:-2]]
        else:
            target_chat_id = message.chat.id
            total_numbers = int(parts[-1])
            prizes = [int(x) for x in parts[2:-1]]
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_newround"))
        return

    if not prizes:
        await message.answer(t(lang, "usage_newround"))
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_newround"))
        return

    target_lang = await repo.get_chat_language(target_chat_id)
    round_doc, error = await round_service.start_new_round(target_chat_id, price, prizes, total_numbers, lang=lang)
    if error:
        await message.answer(error)
        return

    board_msg = await message.bot.send_message(
        target_chat_id,
        build_board_text(round_doc, target_lang),
        reply_markup=build_number_grid(round_doc),
    )
    # pin the board message
    try:
        await message.bot.pin_chat_message(chat_id=target_chat_id, message_id=board_msg.message_id)
    except Exception:
        pass
    await repo.set_board_message_id(round_doc["_id"], board_msg.message_id)


@router.message(Command("closeregistration", "cr"))
async def cmd_close(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_closeregistration"))
        return
    round_doc = await repo.get_active_round(target_chat_id)
    if not round_doc or round_doc["status"] != "registration_open":
        await message.answer(t(lang, "no_open_round_to_close"))
        return

    await round_service.close_registration(round_doc)
    await message.answer(t(lang, "registration_closed_confirm"))


@router.message(Command("startdraw", "sd"))
async def cmd_startdraw(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_startdraw"))
        return
    round_doc = await repo.get_active_round(target_chat_id)
    if not round_doc or round_doc["status"] != "registration_closed":
        await message.answer(t(lang, "must_close_registration_first"))
        return

    target_lang = await repo.get_chat_language(target_chat_id)
    results, error = await draw_service.commit_and_draw(round_doc, bot, target_chat_id, target_lang)
    if error:
        await message.answer(error)
        return

    # Reflect winning numbers on the original board keyboard too.
    fresh = await repo.get_round(round_doc["_id"])
    board_id = fresh["message_refs"].get("board_message_id")
    if board_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=target_chat_id, message_id=board_id, reply_markup=build_number_grid(fresh)
            )
        except Exception:
            pass

    for r in results:
        winner_lang = await repo.get_chat_language(r["telegram_id"])
        win_text = t(
            winner_lang,
            "win_announcement",
            prize=r["prize"],
            currency=t(winner_lang, "currency"),
            place=r["place"],
            number=r["number"],
        )
        try:
            # Message effects (the fun full-screen animations) only work in
            # private chats, which is exactly where this DM is sent — so
            # give the win announcement the same festive effect used for
            # the group results message.
            send_kwargs = {}
            if core_config.RESULT_MESSAGE_EFFECT_ID:
                send_kwargs["message_effect_id"] = core_config.RESULT_MESSAGE_EFFECT_ID
            await bot.send_message(r["telegram_id"], win_text, **send_kwargs)
        except Exception:
            try:
                await bot.send_message(r["telegram_id"], win_text)
            except Exception:
                pass


@router.message(Command("pending", "pd"))
async def cmd_pending(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_pending"))
        return
    round_doc = await repo.get_active_round(target_chat_id)
    if not round_doc:
        await message.answer(t(lang, "no_active_round"))
        return

    try:
        await repo.expire_pending_reservations(round_doc["_id"], core_config.RESERVATION_TTL_MINUTES)
    except Exception:
        pass

    pending = await repo.get_pending_payments(round_doc["_id"])
    if not pending:
        await message.answer(t(lang, "no_pending_payments"))
        return

    for p in pending:
        resolved = await resolve_user_identity(
            bot,
            target_chat_id,
            telegram_id=p.get("telegram_id"),
            username=p.get("username"),
            display_name=p.get("display_name"),
        )
        who = format_user_identity(resolved.get("display_name"), resolved.get("username"), resolved.get("telegram_id"))
        await message.answer(
            t(lang, "pending_payment_line", number=p["number"], who=who, amount=p["amount"], currency=t(lang, "currency")),
            reply_markup=build_review_kb(str(p["_id"])),
        )


@router.message(Command("cancelround", "cancel"))
async def cmd_cancel(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_cancelround"))
        return
    round_doc = await repo.get_active_round(target_chat_id)
    if not round_doc:
        await message.answer(t(lang, "no_active_round"))
        return

    await repo.set_round_status(round_doc["_id"], "cancelled")
    # Also close out any open payments so they don't linger as
    # "awaiting_proof" and get swept into an unrelated future round.
    await repo.cancel_round_payments(round_doc["_id"])
    await message.answer(t(lang, "round_cancelled", round_number=round_doc["round_number"]))


@router.message(Command("listrounds", "rounds"))
async def cmd_listrounds(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_listrounds"))
        return
    rounds = await repo.list_rounds(target_chat_id)
    if not rounds:
        await message.answer(t(lang, "no_rounds_yet"))
        return
    lines = [
        t(lang, "round_list_line", round_number=r["round_number"], status=r["status"], created_at=r["created_at"])
        for r in rounds
    ]
    await message.answer("\n".join(lines))


@router.message(Command("showround", "round"))
async def cmd_showround(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    try:
        rn = int(parts[1])
        target_chat_id, _ = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=2)
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_showround"))
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_showround"))
        return

    round_doc = await repo.get_round_by_number(target_chat_id, rn)
    if not round_doc:
        await message.answer(t(lang, "round_not_found"))
        return

    try:
        await repo.expire_pending_reservations(round_doc["_id"], core_config.RESERVATION_TTL_MINUTES)
    except Exception:
        pass
    round_doc = await repo.get_round_by_number(target_chat_id, rn)

    # Build details
    nums = []
    for n in round_doc['numbers']:
        resolved = await resolve_user_identity(
            bot,
            target_chat_id,
            telegram_id=n.get('telegram_id'),
            username=n.get('username'),
            display_name=n.get('display_name'),
        )
        owner = format_user_identity(resolved.get('display_name'), resolved.get('username'), resolved.get('telegram_id'))
        nums.append(t(lang, "round_number_line", number=n["number"], status=n["status"], owner=owner))
    await message.answer(
        t(lang, "round_detail_header", round_number=round_doc["round_number"], status=round_doc["status"], numbers="\n".join(nums))
    )


@router.message(Command("deleteround", "delround"))
async def cmd_deleteround(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    try:
        rn = int(parts[1])
        target_chat_id, _ = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=2)
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_deleteround"))
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_deleteround"))
        return

    round_doc = await repo.get_round_by_number(target_chat_id, rn)
    if not round_doc:
        await message.answer(t(lang, "round_not_found"))
        return

    # delete stored board message if present
    board_id = round_doc.get('message_refs', {}).get('board_message_id')
    if board_id:
        try:
            await bot.delete_message(chat_id=target_chat_id, message_id=board_id)
        except Exception:
            pass

    # Close out any open payments before deleting the round doc, otherwise
    # they'd be left pointing at a round_id that no longer exists and could
    # still get swept into a later, unrelated payment for the same user.
    await repo.cancel_round_payments(round_doc['_id'])
    await repo.delete_round(round_doc['_id'])
    await message.answer(t(lang, "round_deleted", round_number=rn))


@router.message(Command("resendboard", "board"))
async def cmd_resendboard(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    try:
        rn = int(parts[1])
        target_chat_id, _ = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=2)
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_resendboard"))
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_resendboard"))
        return

    round_doc = await repo.get_round_by_number(target_chat_id, rn)
    if not round_doc:
        await message.answer(t(lang, "round_not_found"))
        return

    target_lang = await repo.get_chat_language(target_chat_id)
    prev_id = round_doc.get('message_refs', {}).get('board_message_id')
    board_msg = await bot.send_message(
        target_chat_id, build_board_text(round_doc, target_lang), reply_markup=build_number_grid(round_doc)
    )
    # unpin previous board if exists
    if prev_id and prev_id != board_msg.message_id:
        try:
            await bot.unpin_chat_message(chat_id=target_chat_id, message_id=prev_id)
        except Exception:
            pass
    # pin new board
    try:
        await bot.pin_chat_message(chat_id=target_chat_id, message_id=board_msg.message_id)
    except Exception:
        pass
    await repo.set_board_message_id(round_doc['_id'], board_msg.message_id)


@router.message(Command("assignnumber", "assign"))
async def cmd_assignnumber(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    # Usage: /assignnumber round_number number telegram_id|@username [display_name]
    try:
        rn = int(parts[1])
        number = int(parts[2])
        who = parts[3]
        target_chat_id, payload_parts = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=4)
        display_name = " ".join(payload_parts[4:]) if len(payload_parts) > 4 else None
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_assignnumber"))
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_assignnumber"))
        return

    round_doc = await repo.get_round_by_number(target_chat_id, rn)
    if not round_doc:
        await message.answer(t(lang, "round_not_found"))
        return

    telegram_id = None
    username = None
    if who.startswith("@"):
        username = who[1:]
    else:
        try:
            telegram_id = int(who)
        except ValueError:
            username = who

    resolved = await resolve_user_identity(
        bot,
        target_chat_id,
        telegram_id=telegram_id,
        username=username,
        display_name=display_name,
    )

    await repo.assign_number(
        round_doc['_id'],
        number,
        telegram_id=resolved.get("telegram_id"),
        username=resolved.get("username"),
        display_name=resolved.get("display_name"),
    )
    # update board message display
    fresh = await repo.get_round(round_doc['_id'])
    target_lang = await repo.get_chat_language(target_chat_id)
    board_id = fresh['message_refs'].get('board_message_id')
    if board_id:
        try:
            await bot.edit_message_text(build_board_text(fresh, target_lang), chat_id=target_chat_id, message_id=board_id)
            await bot.edit_message_reply_markup(chat_id=target_chat_id, message_id=board_id, reply_markup=build_number_grid(fresh))
        except Exception:
            pass

    # Send DM to user if we have a telegram id
    if resolved.get("telegram_id"):
        try:
            user_str = format_user_identity(resolved.get("display_name"), resolved.get("username"), resolved.get("telegram_id"))
            winner_lang = await repo.get_chat_language(resolved.get("telegram_id"))
            await bot.send_message(
                resolved.get("telegram_id"),
                t(winner_lang, "assign_dm_notify", round_number=rn, number=number, who=user_str),
            )
        except Exception:
            pass
    assigned_to = format_user_identity(resolved.get("display_name"), resolved.get("username"), resolved.get("telegram_id"))
    await message.answer(t(lang, "assign_confirm", number=number, round_number=rn, who=assigned_to, chat_id=target_chat_id))


@router.message(Command("revoke", "rv"))
async def cmd_revoke(message: Message, bot: Bot):
    """Opposite of /assignnumber: force-releases a number back to available,
    notifying whoever previously held it."""
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    try:
        rn = int(parts[1])
        number = int(parts[2])
        target_chat_id, _ = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=3)
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_revoke"))
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_revoke"))
        return

    round_doc = await repo.get_round_by_number(target_chat_id, rn)
    if not round_doc:
        await message.answer(t(lang, "round_not_found"))
        return

    previous_holder = await repo.revoke_number(round_doc["id"], number)
    if previous_holder is None:
        await message.answer(t(lang, "revoke_number_not_found", number=number, round_number=rn))
        return

    if not previous_holder.get("released_ok"):
        await message.answer(t(lang, "revoke_failed_verify", number=number, round_number=rn))
        return

    # Reflect the release on the board.
    fresh = await repo.get_round(round_doc["id"])
    target_lang = await repo.get_chat_language(target_chat_id)
    board_id = fresh["message_refs"].get("board_message_id")
    if board_id:
        try:
            await bot.edit_message_text(build_board_text(fresh, target_lang), chat_id=target_chat_id, message_id=board_id)
            await bot.edit_message_reply_markup(chat_id=target_chat_id, message_id=board_id, reply_markup=build_number_grid(fresh))
        except Exception:
            pass

    # Let the previous holder know, if we have a telegram id for them.
    if previous_holder.get("telegram_id"):
        try:
            holder_lang = await repo.get_chat_language(previous_holder["telegram_id"])
            await bot.send_message(
                previous_holder["telegram_id"],
                t(holder_lang, "revoke_notify_previous_holder", number=number, round_number=rn),
            )
        except Exception:
            pass

    if previous_holder.get("telegram_id"):
        who = format_user_identity(
            previous_holder.get("display_name"), previous_holder.get("username"), previous_holder.get("telegram_id")
        )
        status_label = t(lang, "status_pending_label") if previous_holder.get("status") == "pending" else t(lang, "status_reserved_label")
        was_text = t(lang, "revoke_was_text_with_status", who=who, status=status_label)
    else:
        who = t(lang, "revoke_no_previous_holder")
        was_text = t(lang, "revoke_was_text", who=who)
    await message.answer(t(lang, "revoke_confirm", number=number, round_number=rn, was_text=was_text))


@router.message(Command("payout", "paid"))
async def cmd_payout(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    try:
        round_number = int(parts[1])
        telegram_id = int(parts[2])
        target_chat_id, _ = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=3)
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_payout"))
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer(t(lang, "usage_payout"))
        return

    round_doc = await repo.get_round_by_number(target_chat_id, round_number)
    if not round_doc:
        await message.answer(t(lang, "round_not_found"))
        return

    await repo.mark_payout_paid(round_doc["_id"], telegram_id)
    await message.answer(t(lang, "payout_marked_paid"))
    try:
        winner = next((r for r in round_doc.get("draw", {}).get("results", []) if r.get("telegram_id") == telegram_id), None)
        winner_lang = await repo.get_chat_language(telegram_id)
        prize_text = ""
        if winner:
            prize_text = t(
                winner_lang,
                "payout_prize_details",
                prize=winner.get("prize", 0),
                place=winner.get("place"),
                number=winner.get("number"),
                currency=t(winner_lang, "currency"),
            )
        await bot.send_message(telegram_id, t(winner_lang, "payout_notify_user") + prize_text)
    except Exception:
        pass


@router.message(Command("addadmin", "aadmin"))
async def cmd_addadmin(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    try:
        aid = int(parts[1])
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_addadmin"))
        return

    await repo.add_admin(aid)
    await message.answer(t(lang, "admin_added", admin_id=aid))


@router.message(Command("deladmin", "dadmin"))
async def cmd_deladmin(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    try:
        aid = int(parts[1])
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_deladmin"))
        return

    await repo.remove_admin(aid)
    await message.answer(t(lang, "admin_removed", admin_id=aid))


@router.message(Command("listadmins", "admins"))
async def cmd_listadmins(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    admins = await repo.get_admins()
    lines = [str(a) for a in admins]
    await message.answer(t(lang, "admins_list_header", list="\n".join(lines)))


@router.message(Command("chat", "msg"))
async def cmd_chat(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split(maxsplit=2)
    try:
        target = int(parts[1])
    except (IndexError, ValueError):
        await message.answer(t(lang, "usage_chat"))
        return

    # If text provided inline, send it; otherwise forward/copy the replied-to message
    if len(parts) > 2 and parts[2].strip():
        txt = parts[2].strip()
        try:
            await bot.send_message(target, txt)
            await message.answer(t(lang, "chat_sent"))
        except Exception:
            await message.answer(t(lang, "chat_send_failed"))
        return

    # No inline text: expect this message is a reply to something to forward/copy
    if not message.reply_to_message:
        await message.answer(t(lang, "chat_need_reply_or_text"))
        return

    rm = message.reply_to_message
    try:
        # Use copy_message to preserve media and caption but attribute to bot
        await bot.copy_message(chat_id=target, from_chat_id=rm.chat.id, message_id=rm.message_id)
        await message.answer(t(lang, "chat_forwarded"))
    except Exception:
        try:
            await bot.forward_message(chat_id=target, from_chat_id=rm.chat.id, message_id=rm.message_id)
            await message.answer(t(lang, "chat_forwarded"))
        except Exception:
            await message.answer(t(lang, "chat_forward_failed"))


# ---------------------------------------------------------------------------
# Payment method management (universal, bot-wide - see db/repository.py and
# services/round_service.py build_payment_instructions_text)
# ---------------------------------------------------------------------------

def _split_pipe_args(text: str, expected_parts: int) -> list[str] | None:
    """Splits 'Name | Details' (or 'id | Name | Details') style arguments on
    '|', trimming whitespace. Returns None if the piece count doesn't match."""
    pieces = [p.strip() for p in text.split("|")]
    if len(pieces) != expected_parts or any(not p for p in pieces):
        return None
    return pieces


@router.message(Command("addpayment"))
async def cmd_addpayment(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    _, _, rest = message.text.partition(" ")
    parts = _split_pipe_args(rest, 2)
    if not parts:
        await message.answer(t(lang, "usage_addpayment"))
        return

    name, details = parts
    doc = await repo.add_payment_method(name, details)
    await message.answer(t(lang, "payment_added", payment_id=str(doc["_id"]), name=name))


@router.message(Command("editpayment"))
async def cmd_editpayment(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    _, _, rest = message.text.partition(" ")
    parts = _split_pipe_args(rest, 3)
    if not parts:
        await message.answer(t(lang, "usage_editpayment"))
        return

    payment_id, name, details = parts
    ok = await repo.update_payment_method(payment_id, name=name, details=details)
    if not ok:
        await message.answer(t(lang, "payment_not_found"))
        return
    await message.answer(t(lang, "payment_updated", name=name))


@router.message(Command("delpayment"))
async def cmd_delpayment(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(t(lang, "usage_delpayment"))
        return

    ok = await repo.delete_payment_method(parts[1].strip())
    if not ok:
        await message.answer(t(lang, "payment_not_found"))
        return
    await message.answer(t(lang, "payment_removed"))


@router.message(Command("togglepayment"))
async def cmd_togglepayment(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(t(lang, "usage_togglepayment"))
        return

    method = await repo.get_payment_method(parts[1].strip())
    if not method:
        await message.answer(t(lang, "payment_not_found"))
        return

    new_active = not method.get("active", True)
    await repo.set_payment_method_active(method["_id"], new_active)
    state = t(lang, "state_active") if new_active else t(lang, "state_inactive")
    await message.answer(t(lang, "payment_toggled", name=method["name"], state=state))


@router.message(Command("listpayments", "payments"))
async def cmd_listpayments(message: Message):
    if not await is_admin(message.from_user.id):
        return
    lang = await repo.get_chat_language(message.chat.id)

    methods = await repo.list_payment_methods(active_only=False)
    if not methods:
        await message.answer(t(lang, "payment_list_empty"))
        return

    lines = [t(lang, "payment_list_header")]
    for m in methods:
        state = t(lang, "state_active") if m.get("active", True) else t(lang, "state_inactive")
        lines.append(t(lang, "payment_list_line", payment_id=str(m["_id"]), name=m["name"], details=m["details"], state=state))
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("rev:"))
async def on_review(callback: CallbackQuery, bot: Bot):
    admin_lang = await repo.get_chat_language(callback.from_user.id)
    if not await is_admin(callback.from_user.id):
        await callback.answer(t(admin_lang, "admins_only"), show_alert=True)
        return

    # support multiple payment ids joined by commas in the third segment
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer(t(admin_lang, "invalid_action"), show_alert=True)
        return
    _, action, ids_raw = parts
    ids = [pid for pid in ids_raw.split(",") if pid]

    status_label_keys = {
        "awaiting_review": "status_awaiting_review",
        "approved": "status_approved",
        "rejected": "status_rejected",
        "cancelled": "status_cancelled",
    }

    async def _edit_review_message(status_text: str):
        try:
            if callback.message.photo:
                current_caption = callback.message.caption or ""
                new_caption = t(admin_lang, "review_status_suffix", status=status_text)
                new_caption = f"{current_caption}\n\n{new_caption}" if current_caption else new_caption
                await callback.message.edit_caption(caption=new_caption, reply_markup=None)
            else:
                current_text = callback.message.text or ""
                new_text = t(admin_lang, "review_status_suffix", status=status_text)
                new_text = f"{current_text}\n\n{new_text}" if current_text else new_text
                await callback.message.edit_text(text=new_text, reply_markup=None)
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

    async def _current_status_alert() -> str:
        for pid in ids:
            payment = await repo.get_payment(pid)
            if payment:
                st = payment.get("status", "unknown")
                label = t(admin_lang, status_label_keys.get(st, "status_cancelled")) if st in status_label_keys else st
                return t(admin_lang, "already_handled_by_admin", status=label)
        return t(admin_lang, "already_handled_generic")

    handled = 0
    affected_rounds = set()
    for pid in ids:
        payment = await repo.get_payment(pid)
        if not payment:
            continue
        if payment.get("status") != "awaiting_review":
            continue

        payer_lang = await repo.get_chat_language(payment["telegram_id"])
        if action == "approve":
            await round_service.approve_payment(payment, callback.from_user.id)
            try:
                await bot.send_message(
                    payment["telegram_id"],
                    t(payer_lang, "payment_approved_notify", number=payment["number"]),
                )
            except Exception:
                pass
        else:
            await round_service.reject_payment(payment, callback.from_user.id)
            try:
                await bot.send_message(
                    payment["telegram_id"],
                    t(payer_lang, "payment_rejected_notify", number=payment["number"]),
                )
            except Exception:
                pass

        handled += 1
        # track rounds that need their board refreshed
        if payment.get("round_id"):
            affected_rounds.add(str(payment.get("round_id")))

    if handled:
        await callback.answer(t(admin_lang, "handled_ok"))
    else:
        await callback.answer(await _current_status_alert(), show_alert=True)

    # Refresh boards for any affected rounds
    for rid in affected_rounds:
        try:
            fresh = await repo.get_round(rid)
            board_id = fresh["message_refs"].get("board_message_id") if fresh else None
            if fresh and board_id:
                board_lang = await repo.get_chat_language(fresh["chat_id"])
                await bot.edit_message_text(build_board_text(fresh, board_lang), chat_id=fresh["chat_id"], message_id=board_id)
                await bot.edit_message_reply_markup(
                    chat_id=fresh["chat_id"], message_id=board_id, reply_markup=build_number_grid(fresh)
                )
        except Exception:
            pass

    if handled:
        status_key = "status_approved" if action == "approve" else "status_rejected"
        await _edit_review_message(t(admin_lang, status_key))
