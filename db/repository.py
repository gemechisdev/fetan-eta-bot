from datetime import datetime, timezone

from bson import ObjectId

from db.client import get_db

ACTIVE_STATUSES = [
    "registration_open",
    "registration_closed",
    "drawing",
    "awaiting_claims",
]


def utcnow():
    return datetime.now(timezone.utc)


def _oid(value):
    """Accepts either an ObjectId or its string form."""
    return ObjectId(value) if isinstance(value, str) else value


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------

async def create_round(chat_id, round_number, ticket_price, total_numbers, prizes):
    db = get_db()
    numbers = [
        {
            "number": i,
            "status": "available",
            "telegram_id": None,
            "username": None,
            "payment_id": None,
            "reserved_at": None,
        }
        for i in range(1, total_numbers + 1)
    ]
    doc = {
        "round_number": round_number,
        "chat_id": chat_id,
        "status": "registration_open",
        "config": {
            "ticket_price": ticket_price,
            "total_numbers": total_numbers,
            "prizes": prizes,
        },
        "numbers": numbers,
        "draw": {"seed": None, "seed_hash": None, "status": "idle", "results": []},
        "message_refs": {"board_message_id": None},
        "created_at": utcnow(),
        "started_at": utcnow(),
        "closed_at": None,
        "finished_at": None,
    }
    result = await db.rounds.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def get_active_round(chat_id):
    db = get_db()
    return await db.rounds.find_one(
        {"chat_id": chat_id, "status": {"$in": ACTIVE_STATUSES}},
        sort=[("created_at", -1)],
    )


async def get_round(round_id):
    db = get_db()
    return await db.rounds.find_one({"_id": _oid(round_id)})


async def get_round_by_number(chat_id, round_number):
    db = get_db()
    return await db.rounds.find_one({"chat_id": chat_id, "round_number": round_number})


async def get_next_round_number(chat_id):
    db = get_db()
    last = await db.rounds.find_one({"chat_id": chat_id}, sort=[("round_number", -1)])
    return (last["round_number"] + 1) if last else 1


async def set_board_message_id(round_id, message_id):
    db = get_db()
    await db.rounds.update_one(
        {"_id": _oid(round_id)},
        {"$set": {"message_refs.board_message_id": message_id}},
    )


async def set_round_status(round_id, status, **extra_fields):
    db = get_db()
    fields = {"status": status, **extra_fields}
    await db.rounds.update_one({"_id": _oid(round_id)}, {"$set": fields})


async def set_draw_field(round_id, **fields):
    db = get_db()
    update = {f"draw.{k}": v for k, v in fields.items()}
    await db.rounds.update_one({"_id": _oid(round_id)}, {"$set": update})


# ---- number state transitions (all atomic, filtered on current status) ----

async def reserve_number_pending(round_id, number, telegram_id, username):
    """Atomically flips an available number to pending.
    Returns True only if this call is the one that won the race."""
    db = get_db()
    result = await db.rounds.update_one(
        {"_id": _oid(round_id), "numbers.number": number, "numbers.status": "available"},
        {
            "$set": {
                "numbers.$.status": "pending",
                "numbers.$.telegram_id": telegram_id,
                "numbers.$.username": username,
                "numbers.$.reserved_at": utcnow(),
            }
        },
    )
    return result.modified_count == 1


async def release_number(round_id, number):
    db = get_db()
    await db.rounds.update_one(
        {"_id": _oid(round_id), "numbers.number": number},
        {
            "$set": {
                "numbers.$.status": "available",
                "numbers.$.telegram_id": None,
                "numbers.$.username": None,
                "numbers.$.payment_id": None,
                "numbers.$.reserved_at": None,
            }
        },
    )


async def link_payment_to_number(round_id, number, payment_id):
    db = get_db()
    await db.rounds.update_one(
        {"_id": _oid(round_id), "numbers.number": number},
        {"$set": {"numbers.$.payment_id": payment_id}},
    )


async def confirm_number(round_id, number, payment_id):
    db = get_db()
    await db.rounds.update_one(
        {"_id": _oid(round_id), "numbers.number": number},
        {"$set": {"numbers.$.status": "reserved", "numbers.$.payment_id": payment_id}},
    )


async def mark_payout_paid(round_id, telegram_id):
    db = get_db()
    await db.rounds.update_one(
        {"_id": _oid(round_id), "draw.results.telegram_id": telegram_id},
        {"$set": {"draw.results.$.payout_status": "paid"}},
    )
    round_doc = await db.rounds.find_one({"_id": _oid(round_id)})
    if round_doc and all(r["payout_status"] == "paid" for r in round_doc["draw"]["results"]):
        await db.rounds.update_one(
            {"_id": _oid(round_id)},
            {"$set": {"status": "completed", "finished_at": utcnow()}},
        )


async def find_round_awaiting_claim_for_user(telegram_id):
    db = get_db()
    return await db.rounds.find_one(
        {
            "status": "awaiting_claims",
            "draw.results": {
                "$elemMatch": {"telegram_id": telegram_id, "payout_status": "awaiting_details"}
            },
        }
    )


async def set_payout_account(round_id, telegram_id, account_text):
    db = get_db()
    await db.rounds.update_one(
        {"_id": _oid(round_id), "draw.results.telegram_id": telegram_id},
        {
            "$set": {
                "draw.results.$.payout_account": account_text,
                "draw.results.$.payout_status": "pending_payout",
            }
        },
    )


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

async def create_payment(round_id, number, telegram_id, username, amount):
    db = get_db()
    doc = {
        "round_id": round_id,
        "number": number,
        "telegram_id": telegram_id,
        "username": username,
        "amount": amount,
        "proof": None,
        "status": "awaiting_proof",
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": utcnow(),
        "submitted_at": None,
    }
    result = await db.payments.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def get_payment(payment_id):
    db = get_db()
    return await db.payments.find_one({"_id": _oid(payment_id)})


async def get_awaiting_proof_payment_for_user(telegram_id):
    db = get_db()
    return await db.payments.find_one(
        {"telegram_id": telegram_id, "status": "awaiting_proof"},
        sort=[("created_at", -1)],
    )


async def submit_proof(payment_id, proof):
    db = get_db()
    await db.payments.update_one(
        {"_id": _oid(payment_id)},
        {"$set": {"proof": proof, "status": "awaiting_review", "submitted_at": utcnow()}},
    )


async def review_payment(payment_id, status, admin_id):
    db = get_db()
    await db.payments.update_one(
        {"_id": _oid(payment_id)},
        {"$set": {"status": status, "reviewed_by": admin_id, "reviewed_at": utcnow()}},
    )


async def get_pending_payments(round_id):
    db = get_db()
    cursor = db.payments.find({"round_id": round_id, "status": "awaiting_review"})
    return [p async for p in cursor]
