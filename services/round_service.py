from db import repository as repo

DEFAULT_TOTAL_NUMBERS = 20


async def start_new_round(chat_id, ticket_price, prizes, total_numbers=DEFAULT_TOTAL_NUMBERS):
    existing = await repo.get_active_round(chat_id)
    if existing:
        return None, (
            f"Round #{existing['round_number']} is still active "
            f"(status: {existing['status']}). Finish or /cancelround it first."
        )
    round_number = await repo.get_next_round_number(chat_id)
    round_doc = await repo.create_round(chat_id, round_number, ticket_price, total_numbers, prizes)
    return round_doc, None


async def select_number(round_doc, number, telegram_id, username):
    if round_doc["status"] != "registration_open":
        return None, "Registration is closed for this round."

    valid_numbers = {n["number"] for n in round_doc["numbers"]}
    if number not in valid_numbers:
        return None, "Invalid number."

    won_race = await repo.reserve_number_pending(round_doc["_id"], number, telegram_id, username)
    if not won_race:
        return None, "That number was just taken. Pick another one."

    payment = await repo.create_payment(
        round_doc["_id"], number, telegram_id, username, round_doc["config"]["ticket_price"]
    )
    await repo.link_payment_to_number(round_doc["_id"], number, payment["_id"])
    return payment, None


async def cancel_selection(round_doc, number):
    """Releases a number back to available (e.g. user unreachable via DM)."""
    await repo.release_number(round_doc["_id"], number)


async def approve_payment(payment, admin_id):
    await repo.review_payment(payment["_id"], "approved", admin_id)
    await repo.confirm_number(payment["round_id"], payment["number"], payment["_id"])


async def reject_payment(payment, admin_id):
    await repo.review_payment(payment["_id"], "rejected", admin_id)
    await repo.release_number(payment["round_id"], payment["number"])


async def close_registration(round_doc):
    await repo.set_round_status(round_doc["_id"], "registration_closed", closed_at=repo.utcnow())
