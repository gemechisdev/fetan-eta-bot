from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

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


def _round_help(command: str) -> str:
    return f"Usage: {command} ... [chat_id]"


def _format_draw_result_line(result: dict) -> str:
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(result.get("place"), "🎖")
    who = format_user_identity(result.get("display_name"), result.get("username"), result.get("telegram_id"))
    return (
        f"{medal} Place #{result['place']}: Number {result['number']:02d} — {who} — Prize: {result['prize']} ETB"
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
        await message.answer("Usage: /newround price prize1 prize2 ... prizeN participants_count [chat_id]")
        return

    if not prizes:
        await message.answer("Usage: /newround price prize1 prize2 ... prizeN participants_count [chat_id]")
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /newround price prize1 prize2 ... prizeN participants_count [chat_id]")
        return

    round_doc, error = await round_service.start_new_round(target_chat_id, price, prizes, total_numbers)
    if error:
        await message.answer(error)
        return

    board_msg = await message.answer(
        build_board_text(round_doc),
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

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /closeregistration [chat_id]")
        return
    round_doc = await repo.get_active_round(target_chat_id)
    if not round_doc or round_doc["status"] != "registration_open":
        await message.answer("No open round to close.")
        return

    await round_service.close_registration(round_doc)
    await message.answer(f"Registration closed for chat {target_chat_id}. Run /startdraw when ready.")


@router.message(Command("startdraw", "sd"))
async def cmd_startdraw(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /startdraw [chat_id]")
        return
    round_doc = await repo.get_active_round(target_chat_id)
    if not round_doc or round_doc["status"] != "registration_closed":
        await message.answer("Close registration first with /closeregistration.")
        return

    results, error = await draw_service.commit_and_draw(round_doc, bot, target_chat_id)
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
        try:
            await bot.send_message(
                r["telegram_id"],
                f"🎉 You won {r['prize']} ETB (place #{r['place']}, number {r['number']:02d})!\n"
                f"Reply here with your payout account (Telebirr/CBE/bank) to claim it.",
            )
        except Exception:
            pass


@router.message(Command("pending", "pd"))
async def cmd_pending(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /pending [chat_id]")
        return
    round_doc = await repo.get_active_round(target_chat_id)
    if not round_doc:
        await message.answer("No active round.")
        return

    pending = await repo.get_pending_payments(round_doc["_id"])
    if not pending:
        await message.answer("No payments awaiting review.")
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
            f"Number {p['number']:02d} — {who} — {p['amount']} ETB",
            reply_markup=build_review_kb(str(p["_id"])),
        )


@router.message(Command("cancelround", "cancel"))
async def cmd_cancel(message: Message):
    if not await is_admin(message.from_user.id):
        return

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /cancelround [chat_id]")
        return
    round_doc = await repo.get_active_round(target_chat_id)
    if not round_doc:
        await message.answer("No active round.")
        return

    await repo.set_round_status(round_doc["_id"], "cancelled")
    await message.answer(f"Round #{round_doc['round_number']} cancelled.")


@router.message(Command("listrounds", "rounds"))
async def cmd_listrounds(message: Message):
    if not await is_admin(message.from_user.id):
        return

    target_chat_id, _ = _resolve_round_chat_id(message.text.split(), message.chat.id, min_tokens_without_chat=1)
    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /listrounds [chat_id]")
        return
    rounds = await repo.list_rounds(target_chat_id)
    if not rounds:
        await message.answer("No rounds yet.")
        return
    lines = []
    for r in rounds:
        lines.append(f"#{r['round_number']} — status: {r['status']} — created: {r['created_at']}")
    await message.answer("\n".join(lines))


@router.message(Command("showround", "round"))
async def cmd_showround(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return

    parts = message.text.split()
    try:
        rn = int(parts[1])
        target_chat_id, _ = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=2)
    except (IndexError, ValueError):
        await message.answer("Usage: /showround round_number [chat_id]")
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /showround round_number [chat_id]")
        return

    round_doc = await repo.get_round_by_number(target_chat_id, rn)
    if not round_doc:
        await message.answer("Round not found.")
        return

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
        nums.append(f"{n['number']:02d}: {n['status']} — {owner}")
    await message.answer(
        f"Round #{round_doc['round_number']}\nStatus: {round_doc['status']}\n" + "\n".join(nums)
    )


@router.message(Command("deleteround", "delround"))
async def cmd_deleteround(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return

    parts = message.text.split()
    try:
        rn = int(parts[1])
        target_chat_id, _ = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=2)
    except (IndexError, ValueError):
        await message.answer("Usage: /deleteround round_number [chat_id]")
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /deleteround round_number [chat_id]")
        return

    round_doc = await repo.get_round_by_number(target_chat_id, rn)
    if not round_doc:
        await message.answer("Round not found.")
        return

    # delete stored board message if present
    board_id = round_doc.get('message_refs', {}).get('board_message_id')
    if board_id:
        try:
            await bot.delete_message(chat_id=target_chat_id, message_id=board_id)
        except Exception:
            pass

    await repo.delete_round(round_doc['_id'])
    await message.answer(f"Deleted round #{rn}.")


@router.message(Command("resendboard", "board"))
async def cmd_resendboard(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return

    parts = message.text.split()
    try:
        rn = int(parts[1])
        target_chat_id, _ = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=2)
    except (IndexError, ValueError):
        await message.answer("Usage: /resendboard round_number [chat_id]")
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /resendboard round_number [chat_id]")
        return

    round_doc = await repo.get_round_by_number(target_chat_id, rn)
    if not round_doc:
        await message.answer("Round not found.")
        return

    prev_id = round_doc.get('message_refs', {}).get('board_message_id')
    board_msg = await bot.send_message(target_chat_id, build_board_text(round_doc), reply_markup=build_number_grid(round_doc))
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

    parts = message.text.split()
    # Usage: /assignnumber round_number number telegram_id|@username [display_name]
    try:
        rn = int(parts[1])
        number = int(parts[2])
        who = parts[3]
        target_chat_id, payload_parts = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=4)
        display_name = " ".join(payload_parts[4:]) if len(payload_parts) > 4 else None
    except (IndexError, ValueError):
        await message.answer("Usage: /assignnumber round_number number telegram_id|@username [display_name] [chat_id]")
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /assignnumber round_number number telegram_id|@username [display_name] [chat_id]")
        return

    round_doc = await repo.get_round_by_number(target_chat_id, rn)
    if not round_doc:
        await message.answer("Round not found.")
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
    board_id = fresh['message_refs'].get('board_message_id')
    if board_id:
        try:
            await bot.edit_message_text(build_board_text(fresh), chat_id=target_chat_id, message_id=board_id)
            await bot.edit_message_reply_markup(chat_id=target_chat_id, message_id=board_id, reply_markup=build_number_grid(fresh))
        except Exception:
            pass

    # Send DM to user if we have a telegram id
    if resolved.get("telegram_id"):
        try:
            user_str = format_user_identity(resolved.get("display_name"), resolved.get("username"), resolved.get("telegram_id"))
            await bot.send_message(
                resolved.get("telegram_id"),
                f"You were assigned number {number:02d} in round #{rn} by an admin.\n\nAssigned to: {user_str}"
            )
        except Exception:
            pass
    assigned_to = format_user_identity(resolved.get("display_name"), resolved.get("username"), resolved.get("telegram_id"))
    await message.answer(f"Assigned number {number:02d} in round #{rn} to {assigned_to} in chat {target_chat_id}.")


@router.message(Command("payout", "paid"))
async def cmd_payout(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return

    parts = message.text.split()
    try:
        round_number = int(parts[1])
        telegram_id = int(parts[2])
        target_chat_id, _ = _resolve_round_chat_id(parts, message.chat.id, min_tokens_without_chat=3)
    except (IndexError, ValueError):
        await message.answer("Usage: /payout round_number telegram_id [chat_id]")
        return

    if _private_chat_id_required(message, target_chat_id):
        await message.answer("Usage: /payout round_number telegram_id [chat_id]")
        return

    round_doc = await repo.get_round_by_number(target_chat_id, round_number)
    if not round_doc:
        await message.answer("Round not found.")
        return

    await repo.mark_payout_paid(round_doc["_id"], telegram_id)
    await message.answer("Marked as paid ✅")
    try:
        winner = next((r for r in round_doc.get("draw", {}).get("results", []) if r.get("telegram_id") == telegram_id), None)
        prize_text = ""
        if winner:
            prize_text = (
                f"\nPrize: {winner.get('prize', 0)} ETB\n"
                f"Place: #{winner.get('place')}\n"
                f"Winning number: {winner.get('number'):02d}"
            )
        await bot.send_message(
            telegram_id,
            "✅ Your prize has been paid out. Thank you for playing Fetan Eta!" + prize_text,
        )
    except Exception:
        pass


@router.message(Command("addadmin", "aadmin"))
async def cmd_addadmin(message: Message):
    if not await is_admin(message.from_user.id):
        return

    parts = message.text.split()
    try:
        aid = int(parts[1])
    except (IndexError, ValueError):
        await message.answer("Usage: /addadmin telegram_id")
        return

    await repo.add_admin(aid)
    await message.answer(f"Added {aid} as admin.")


@router.message(Command("deladmin", "dadmin"))
async def cmd_deladmin(message: Message):
    if not await is_admin(message.from_user.id):
        return

    parts = message.text.split()
    try:
        aid = int(parts[1])
    except (IndexError, ValueError):
        await message.answer("Usage: /deladmin telegram_id")
        return

    await repo.remove_admin(aid)
    await message.answer(f"Removed {aid} from admins.")


@router.message(Command("listadmins", "admins"))
async def cmd_listadmins(message: Message):
    if not await is_admin(message.from_user.id):
        return

    admins = await repo.get_admins()
    lines = [str(a) for a in admins]
    await message.answer("Admins:\n" + "\n".join(lines))


@router.message(Command("chat", "msg"))
async def cmd_chat(message: Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=2)
    try:
        target = int(parts[1])
    except (IndexError, ValueError):
        await message.answer("Usage: /chat telegram_id <message> (or reply to a message with /chat telegram_id)")
        return

    # If text provided inline, send it; otherwise forward/copy the replied-to message
    if len(parts) > 2 and parts[2].strip():
        txt = parts[2].strip()
        try:
            await bot.send_message(target, txt)
            await message.answer("Sent message to user.")
        except Exception:
            await message.answer("Failed to send message to user.")
        return

    # No inline text: expect this message is a reply to something to forward/copy
    if not message.reply_to_message:
        await message.answer("Reply to a message or provide a text to send.")
        return

    rm = message.reply_to_message
    try:
        # Use copy_message to preserve media and caption but attribute to bot
        await bot.copy_message(chat_id=target, from_chat_id=rm.chat.id, message_id=rm.message_id)
        await message.answer("Forwarded replied message to user.")
    except Exception:
        try:
            await bot.forward_message(chat_id=target, from_chat_id=rm.chat.id, message_id=rm.message_id)
            await message.answer("Forwarded replied message to user.")
        except Exception:
            await message.answer("Failed to forward the replied message to user.")


@router.callback_query(F.data.startswith("rev:"))
async def on_review(callback: CallbackQuery, bot: Bot):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Admins only.", show_alert=True)
        return

    # support multiple payment ids joined by commas in the third segment
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer("Invalid action.", show_alert=True)
        return
    _, action, ids_raw = parts
    ids = [pid for pid in ids_raw.split(",") if pid]

    status_labels = {
        "awaiting_review": "Awaiting review",
        "approved": "Approved",
        "rejected": "Rejected",
        "cancelled": "Cancelled",
    }

    async def _edit_review_message(status_text: str):
        try:
            if callback.message.photo:
                current_caption = callback.message.caption or ""
                new_caption = f"{current_caption}\n\nStatus: {status_text}" if current_caption else f"Status: {status_text}"
                await callback.message.edit_caption(caption=new_caption, reply_markup=None)
            else:
                current_text = callback.message.text or ""
                new_text = f"{current_text}\n\nStatus: {status_text}" if current_text else f"Status: {status_text}"
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
                return f"Already {status_labels.get(st, st.title())} by another admin."
        return "Already handled by another admin."

    handled = 0
    affected_rounds = set()
    for pid in ids:
        payment = await repo.get_payment(pid)
        if not payment:
            continue
        if payment.get("status") != "awaiting_review":
            continue

        if action == "approve":
            await round_service.approve_payment(payment, callback.from_user.id)
            try:
                await bot.send_message(
                    payment["telegram_id"],
                    f"✅ Your payment for number {payment['number']:02d} was approved. You're in!",
                )
            except Exception:
                pass
        else:
            await round_service.reject_payment(payment, callback.from_user.id)
            try:
                await bot.send_message(
                    payment["telegram_id"],
                    f"❌ Your payment for number {payment['number']:02d} was rejected. The number is available again.",
                )
            except Exception:
                pass

        handled += 1
        # track rounds that need their board refreshed
        if payment.get("round_id"):
            affected_rounds.add(str(payment.get("round_id")))

    if handled:
        await callback.answer("Handled ✅")
    else:
        await callback.answer(await _current_status_alert(), show_alert=True)

    # Refresh boards for any affected rounds
    for rid in affected_rounds:
        try:
            fresh = await repo.get_round(rid)
            board_id = fresh["message_refs"].get("board_message_id") if fresh else None
            if fresh and board_id:
                await bot.edit_message_text(build_board_text(fresh), chat_id=fresh["chat_id"], message_id=board_id)
                await bot.edit_message_reply_markup(
                    chat_id=fresh["chat_id"], message_id=board_id, reply_markup=build_number_grid(fresh)
                )
        except Exception:
            pass

    if handled:
        await _edit_review_message("Approved" if action == "approve" else "Rejected")
