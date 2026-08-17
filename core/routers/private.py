from aiogram import Bot, F, Router
from aiogram.types import Message

from core.i18n import t
from core.keyboards import build_review_kb, build_review_kb_multi
from core.texts import format_user_identity
from db import repository as repo

router = Router(name="private")


@router.message(F.chat.type == "private")
async def on_private_message(message: Message, bot: Bot):
    user = message.from_user
    lang = await repo.get_chat_language(message.chat.id)

    # 1) Is this user a winner who still needs to submit payout details?
    claim_round = await repo.find_round_awaiting_claim_for_user(user.id)
    if claim_round and message.text:
        await repo.set_payout_account(claim_round["_id"], user.id, message.text.strip())
        await message.answer(t(lang, "claim_received"))
        display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or None
        user_str = format_user_identity(display_name, user.username, user.id)
        winner = next((r for r in claim_round.get("draw", {}).get("results", []) if r.get("telegram_id") == user.id), None)
        prize_text = ""
        if winner:
            prize_text = t(
                lang,
                "prize_details_lines",
                prize=winner.get("prize", 0),
                place=winner.get("place"),
                number=f"{winner.get('number'):02d}",
                currency=t(lang, "currency"),
            )
        for admin_id in await repo.get_admins():
            try:
                admin_lang = await repo.get_chat_language(admin_id)
                await bot.send_message(
                    admin_id,
                    t(
                        admin_lang,
                        "admin_payout_info_notify",
                        round_number=claim_round["round_number"],
                        user=user_str,
                        account=message.text.strip(),
                        prize_text=prize_text if winner else "",
                        telegram_id=user.id,
                    ),
                )
            except Exception:
                pass
        return

    # 2) Is this user mid-payment (needs to submit proof)?
    payments = await repo.get_awaiting_proof_payments_for_user(user.id)
    if payments:
        if message.photo:
            proof = {"type": "photo", "value": message.photo[-1].file_id}
        elif message.text:
            proof = {"type": "text", "value": message.text.strip()}
        else:
            await message.answer(t(lang, "ask_for_payment_proof"))
            return

        # Keep the proof stored even if notifications fail, but do not
        # tell the user it was sent until notification attempts succeed.
        for p in payments:
            await repo.submit_proof(p["_id"], proof)

        numbers = ", ".join(f"{p['number']:02d}" for p in payments)
        display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or None
        user_str = format_user_identity(display_name, user.username, user.id)

        payment_ids = [str(p["_id"]) for p in payments]
        kb = build_review_kb_multi(payment_ids)

        notified = False
        try:
            admin_ids = await repo.get_admins()
        except Exception:
            admin_ids = []

        for admin_id in admin_ids:
            try:
                admin_lang = await repo.get_chat_language(admin_id)
                caption = t(
                    admin_lang,
                    "admin_payment_review_caption",
                    numbers=numbers,
                    user=user_str,
                    amount=payments[0]["amount"],
                    currency=t(admin_lang, "currency"),
                )
                if proof["type"] == "photo":
                    await bot.send_photo(admin_id, proof["value"], caption=caption, reply_markup=kb)
                else:
                    await bot.send_message(
                        admin_id,
                        caption + t(admin_lang, "admin_payment_txn_suffix", value=proof["value"]),
                        reply_markup=kb,
                    )
                notified = True
            except Exception:
                try:
                    print(f"[ADMIN NOTIFY ERROR] failed to notify admin {admin_id} about payments {payment_ids}")
                except Exception:
                    pass

        if not notified:
            fallback_round = await repo.get_round(payments[0]["round_id"])
            if fallback_round:
                try:
                    group_chat_id = fallback_round["chat_id"]
                    group_lang = await repo.get_chat_language(group_chat_id)
                    caption = t(
                        group_lang,
                        "admin_payment_review_caption",
                        numbers=numbers,
                        user=user_str,
                        amount=payments[0]["amount"],
                        currency=t(group_lang, "currency"),
                    )
                    if proof["type"] == "photo":
                        await bot.send_photo(group_chat_id, proof["value"], caption=caption, reply_markup=kb)
                    else:
                        await bot.send_message(
                            group_chat_id,
                            caption + t(group_lang, "admin_payment_txn_suffix", value=proof["value"]),
                            reply_markup=kb,
                        )
                    notified = True
                except Exception:
                    try:
                        print(
                            f"[ADMIN NOTIFY ERROR] failed fallback group notification for payments {payment_ids} "
                            f"round_id={payments[0]['round_id']}"
                        )
                    except Exception:
                        pass

        if notified:
            await message.answer(t(lang, "proof_submitted_confirmation", numbers=numbers))
        else:
            await message.answer(t(lang, "proof_saved_notify_failed"))
        return

    # 3) Nothing pending for this user right now.
    await message.answer(t(lang, "no_pending_action"))
