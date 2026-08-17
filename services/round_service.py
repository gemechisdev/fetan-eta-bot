from db import repository as repo

DEFAULT_TOTAL_NUMBERS = 20

PAY_INSTRUCTIONS_FOOTER = (
    "ወደዚህ ይክፈሉ:\n"
    "Telebirr: 09xxxxxxxx\n"
    "CBE: 100xxxxxxxx\n\n"
    "ክፍያውን ከፈጸሙ በኋላ የክፍያውን ስክሪንሾት ይላኩ ወይም የግብይት መለያ ቁጥሩን (Transaction ID) እዚህ ይጻፉ።"
)


async def build_reservation_summary_text(round_id, telegram_id) -> str:
    """Builds the 'You reserved number(s): ...' DM, summarizing every number
    this user currently has awaiting proof *in this specific round* (so a
    user who reserves several numbers in one round gets one clear summary).
    """
    pending_payments = await repo.get_awaiting_proof_payments_for_round_user(round_id, telegram_id)
    seen = set()
    numbers_list = []
    total = 0
    for p in pending_payments:
        num = p["number"]
        if num not in seen:
            seen.add(num)
            numbers_list.append(f"{num:02d}")
        total += p["amount"]
    numbers = ", ".join(numbers_list) if numbers_list else "(ምንም)"
    return (
        f"የተያዙ ቁጥር(ሮች): {numbers}።\n\n"
        f"ጠቅላላ: {total} ETB\n\n"
        f"{PAY_INSTRUCTIONS_FOOTER}"
    )


async def refresh_board(bot, chat_id):
    """Re-renders the group's number grid after a reservation state change.
    Safe to call from any context (group callback or private /start)."""
    from core.keyboards import build_number_grid

    fresh = await repo.get_active_round(chat_id)
    if not fresh:
        return
    try:
        board_id = fresh.get("message_refs", {}).get("board_message_id")
        if board_id:
            await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=board_id, reply_markup=build_number_grid(fresh)
            )
    except Exception:
        pass


async def start_new_round(chat_id, ticket_price, prizes, total_numbers=DEFAULT_TOTAL_NUMBERS):
    existing = await repo.get_active_round(chat_id)
    if existing:
        return None, (
            f"ዙር #{existing['round_number']} አሁንም ንቁ ነው "
            f"(ሁኔታ: {existing['status']})። መጀመሪያ ይጨርሱት ወይም /cancelround ያድርጉት።"
        )
    round_number = await repo.get_next_round_number(chat_id)
    round_doc = await repo.create_round(chat_id, round_number, ticket_price, total_numbers, prizes)
    return round_doc, None


async def select_number(round_doc, number, telegram_id, username, display_name=None):
    if round_doc["status"] != "registration_open":
        return None, "ለዚህ ዙር ምዝገባው ተዘግቷል።"

    valid_numbers = {n["number"] for n in round_doc["numbers"]}
    if number not in valid_numbers:
        return None, "ልክ ያልሆነ ቁጥር።"

    won_race = await repo.reserve_number_pending(round_doc["_id"], number, telegram_id, username, display_name)
    if not won_race:
        # Provide info about who currently holds the number if possible
        fresh = await repo.get_round(round_doc["_id"])
        holder = None
        if fresh:
            for n in fresh["numbers"]:
                if n["number"] == number:
                    holder = n
                    break
        if holder and holder.get("telegram_id"):
            who = holder.get("display_name") or holder.get("username") or f"id:{holder.get('telegram_id')}"
            return None, f"ይህ ቁጥር አስቀድሞ በ{who} ተይዟል። ሌላ ቁጥር ይምረጡ።"
        return None, "ይህ ቁጥር አሁን በሌላ ሰው ተይዟል። ሌላ ቁጥር ይምረጡ።"

    payment = await repo.create_payment(
        round_doc["_id"], number, telegram_id, username, round_doc["config"]["ticket_price"], display_name=display_name
    )
    await repo.link_payment_to_number(round_doc["_id"], number, payment["_id"])
    return payment, None


async def cancel_selection(round_doc, number):
    """Releases a number back to available (e.g. user unreachable via DM)."""
    # First try to cancel any awaiting payment for the current reserver
    # If none found, just release the number
    # We don't know which user to cancel for here; attempt a generic cancel
    # by checking the round document for the current holder.
    fresh = await repo.get_round(round_doc["_id"])
    if fresh:
        holder = next((n for n in fresh["numbers"] if n["number"] == number), None)
        if holder and holder.get("telegram_id"):
            await repo.cancel_payment_for_user(round_doc["_id"], number, holder["telegram_id"])
            return

    await repo.release_number(round_doc["_id"], number)


async def approve_payment(payment, admin_id):
    await repo.review_payment(payment["_id"], "approved", admin_id)
    await repo.confirm_number(payment["round_id"], payment["number"], payment["_id"])


async def reject_payment(payment, admin_id):
    await repo.review_payment(payment["_id"], "rejected", admin_id)
    await repo.release_number(payment["round_id"], payment["number"])


async def close_registration(round_doc):
    await repo.set_round_status(round_doc["_id"], "registration_closed", closed_at=repo.utcnow())
