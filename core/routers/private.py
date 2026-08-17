from aiogram import Bot, F, Router
from aiogram.types import Message

from core.config import ADMIN_IDS
from core.keyboards import build_review_kb, build_review_kb_multi
from core.texts import CLAIM_RECEIVED, NO_PENDING_ACTION, PROOF_RECEIVED, format_user_identity
from db import repository as repo

router = Router(name="private")


@router.message(F.chat.type == "private")
async def on_private_message(message: Message, bot: Bot):
    user = message.from_user

    # 1) Is this user a winner who still needs to submit payout details?
    claim_round = await repo.find_round_awaiting_claim_for_user(user.id)
    if claim_round and message.text:
        await repo.set_payout_account(claim_round["_id"], user.id, message.text.strip())
        await message.answer(CLAIM_RECEIVED)
        display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or None
        user_str = format_user_identity(display_name, user.username, user.id)
        winner = next((r for r in claim_round.get("draw", {}).get("results", []) if r.get("telegram_id") == user.id), None)
        prize_text = ""
        if winner:
            prize_text = (
                f"\nሽልማት፡ {winner.get('prize', 0)} ብር"
                f"\nደረጃ፡ #{winner.get('place')}"
                f"\nያሸነፈ ቁጥር፡ {winner.get('number'):02d}"
            )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    "💰 የክፍያ መቀበያ መረጃ ተላክ\n"
                    f"ዙር #{claim_round['round_number']}\n"
                    f"ተጠቃሚ፡ {user_str}\n"
                    f"ሂሳብ፡ {message.text.strip()}"
                    f"{prize_text}\n\n"
                    f"ክፍያው እንደተፈጸመ ምልክት ለማድረግ፡\n/payout {claim_round['round_number']} {user.id}",
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
            await message.answer("እባክዎ የክፍያ ማረጋገጫ ስክሪንሹት ይላኩ ወይም የግብይት መለያ ቁጥርዎን ይጻፉ።")
            return

        # Keep the proof stored even if notifications fail, but do not
        # tell the user it was sent until notification attempts succeed.
        for p in payments:
            await repo.submit_proof(p["_id"], proof)

        numbers = ", ".join(f"{p['number']:02d}" for p in payments)
        display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or None
        user_str = format_user_identity(display_name, user.username, user.id)

        payment_ids = [str(p["_id"]) for p in payments]
        caption = (
            "🧾 አዲስ ክፍያ(ዎች) ለግምገማ\n"
            f"ቁጥሮች፡ {numbers}\n"
            f"ተጠቃሚ፡ {user_str}\n"
            f"መጠን፡ {payments[0]['amount']} ብር (ለእያንዳንዱ)"
        )
        kb = build_review_kb_multi(payment_ids)

        notified = False
        try:
            admin_ids = await repo.get_admins()
        except Exception:
            admin_ids = []

        for admin_id in admin_ids:
            try:
                if proof["type"] == "photo":
                    await bot.send_photo(admin_id, proof["value"], caption=caption, reply_markup=kb)
                else:
                    await bot.send_message(admin_id, caption + f"\nግብይት፡ {proof['value']}", reply_markup=kb)
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
                    if proof["type"] == "photo":
                        await bot.send_photo(group_chat_id, proof["value"], caption=caption, reply_markup=kb)
                    else:
                        await bot.send_message(group_chat_id, caption + f"\nግብይት፡ {proof['value']}", reply_markup=kb)
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
            await message.answer(
                "ተረድቻለሁ! ለሚከተሉት ቁጥሮች የክፍያ ማረጋገጫዎ ለግምገማ ተልኳል፡\n" + numbers
            )
        else:
            await message.answer(
                "ማረጋገጫዎን አስቀምጫለሁ፣ ግን የግምገማ ጥያቄውን ለአስተዳዳሪዎች አሁን ማድረስ አልቻልኩም። እባክዎ ቆይተው እንደገና ይሞክሩ።"
            )
        return

    # 3) Nothing pending for this user right now.
    await message.answer(NO_PENDING_ACTION)
    