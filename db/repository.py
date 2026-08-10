from datetime import datetime, timezone, timedelta
from typing import List

from core import config as core_config

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
            "display_name": None,
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


async def list_rounds(chat_id):
    db = get_db()
    cursor = db.rounds.find({"chat_id": chat_id}).sort([("created_at", -1)])
    return [r async for r in cursor]


async def delete_round(round_id):
    db = get_db()
    await db.rounds.delete_one({"_id": _oid(round_id)})


async def assign_number(round_id, number, telegram_id=None, username=None, display_name=None):
    """Force-assign a number to a user (admin action). Marks the number as reserved.
    If telegram_id is provided, set it; otherwise set username/display_name only."""
    db = get_db()
    update = {
        "$set": {
            "numbers.$.status": "reserved",
            "numbers.$.payment_id": None,
            "numbers.$.reserved_at": utcnow(),
        }
    }
    if telegram_id is not None:
        update["$set"]["numbers.$.telegram_id"] = int(telegram_id)
    else:
        update["$set"]["numbers.$.telegram_id"] = None
    if username is not None:
        update["$set"]["numbers.$.username"] = username
    if display_name is not None:
        update["$set"]["numbers.$.display_name"] = display_name

    # Use arrayFilters to ensure correct element is updated
    # rewrite update to use numbers.$[elem]
    set_fields = {}
    for k, v in update.get("$set", {}).items():
        # replace prefix 'numbers.$.' with 'numbers.$[elem].'
        set_fields[k.replace('numbers.$.', 'numbers.$[elem].')] = v
    await db.rounds.update_one({"_id": _oid(round_id)}, {"$set": set_fields}, array_filters=[{"elem.number": number}])


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

async def reserve_number_pending(round_id, number, telegram_id, username, display_name=None):
    """Atomically flips an available number to pending.
    Returns True only if this call is the one that won the race."""
    db = get_db()
    # Use arrayFilters to ensure we update the array element with the matching number
    result = await db.rounds.update_one(
        {"_id": _oid(round_id)},
        {
            "$set": {
                "numbers.$[elem].status": "pending",
                "numbers.$[elem].telegram_id": telegram_id,
                "numbers.$[elem].username": username,
                "numbers.$[elem].display_name": display_name,
                "numbers.$[elem].reserved_at": utcnow(),
            }
        },
        array_filters=[{"elem.number": number, "elem.status": "available"}],
    )
    try:
        print(f"[DB DEBUG] reserve_number_pending round_id={round_id} number={number} telegram_id={telegram_id} modified={result.modified_count}")
        # Fetch the affected round's first 12 numbers for quick inspection
        doc = await db.rounds.find_one({"_id": _oid(round_id)}, {"numbers": {"$slice": 12}})
        nums = [(n.get("number"), n.get("status"), n.get("telegram_id")) for n in doc["numbers"]]
        print(f"[DB DEBUG] post-reserve numbers_sample={nums}")
    except Exception:
        pass
    return result.modified_count == 1


async def release_number(round_id, number):
    db = get_db()
    await db.rounds.update_one(
        {"_id": _oid(round_id)},
        {
            "$set": {
                "numbers.$[elem].status": "available",
                "numbers.$[elem].telegram_id": None,
                "numbers.$[elem].username": None,
                "numbers.$[elem].display_name": None,
                "numbers.$[elem].payment_id": None,
                "numbers.$[elem].reserved_at": None,
            }
        },
        array_filters=[{"elem.number": number}],
    )
    try:
        print(f"[DB DEBUG] release_number round_id={round_id} number={number}")
        doc = await db.rounds.find_one({"_id": _oid(round_id)}, {"numbers": {"$slice": 12}})
        nums = [(n.get("number"), n.get("status"), n.get("telegram_id")) for n in doc["numbers"]]
        print(f"[DB DEBUG] post-release numbers_sample={nums}")
    except Exception:
        pass


async def link_payment_to_number(round_id, number, payment_id):
    db = get_db()
    await db.rounds.update_one(
        {"_id": _oid(round_id)},
        {"$set": {"numbers.$[elem].payment_id": payment_id}},
        array_filters=[{"elem.number": number}],
    )
    try:
        print(f"[DB DEBUG] link_payment_to_number round_id={round_id} number={number} payment_id={payment_id}")
    except Exception:
        pass


async def confirm_number(round_id, number, payment_id):
    db = get_db()
    await db.rounds.update_one(
        {"_id": _oid(round_id)},
        {"$set": {"numbers.$[elem].status": "reserved", "numbers.$[elem].payment_id": payment_id}},
        array_filters=[{"elem.number": number}],
    )
    try:
        print(f"[DB DEBUG] confirm_number round_id={round_id} number={number} payment_id={payment_id}")
    except Exception:
        pass


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

async def create_payment(round_id, number, telegram_id, username, amount, display_name=None):
    db = get_db()
    # Prevent creating duplicate payments for the same round+number
    existing = await db.payments.find_one(
        {"round_id": round_id, "number": number, "status": {"$in": ["awaiting_proof", "awaiting_review"]}}
    )
    if existing:
        return existing
    doc = {
        "round_id": round_id,
        "number": number,
        "telegram_id": telegram_id,
        "username": username,
        "display_name": display_name,
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


async def get_awaiting_proof_payments_for_user(telegram_id):
    """Return all payments for this user that are awaiting proof (status awaiting_proof)."""
    db = get_db()
    cursor = db.payments.find({"telegram_id": telegram_id, "status": "awaiting_proof"}).sort([("created_at", -1)])
    return [p async for p in cursor]


async def get_awaiting_proof_payments_for_round_user(round_id, telegram_id):
    db = get_db()
    cursor = db.payments.find({"round_id": round_id, "telegram_id": telegram_id, "status": "awaiting_proof"})
    return [p async for p in cursor]


async def expire_pending_reservations(round_id, ttl_minutes):
    """Releases any 'pending' numbers that were reserved more than ttl_minutes ago."""
    db = get_db()
    cutoff = utcnow() - timedelta(minutes=ttl_minutes)
    # Update any numbers array elements matching pending and older than cutoff.
    await db.rounds.update_one(
        {"_id": _oid(round_id)},
        {
            "$set": {
                "numbers.$[elem].status": "available",
                "numbers.$[elem].telegram_id": None,
                "numbers.$[elem].username": None,
                "numbers.$[elem].display_name": None,
                "numbers.$[elem].payment_id": None,
                "numbers.$[elem].reserved_at": None,
            }
        },
        array_filters=[{"elem.status": "pending", "elem.reserved_at": {"$lt": cutoff}}],
    )


# ---------------------------------------------------------------------------
# Admin management
# ---------------------------------------------------------------------------

async def add_admin(telegram_id: int):
    db = get_db()
    doc = {"telegram_id": int(telegram_id), "added_at": utcnow()}
    await db.admins.update_one({"telegram_id": int(telegram_id)}, {"$setOnInsert": doc}, upsert=True)


async def remove_admin(telegram_id: int):
    db = get_db()
    await db.admins.delete_one({"telegram_id": int(telegram_id)})


async def get_admins() -> List[int]:
    db = get_db()
    cursor = db.admins.find({})
    docs = [d async for d in cursor]
    ids = {int(d["telegram_id"]) for d in docs}
    # also include any configured via env
    ids.update(core_config.ADMIN_IDS)
    return sorted(ids)


async def is_user_admin(telegram_id: int) -> bool:
    if int(telegram_id) in core_config.ADMIN_IDS:
        return True
    db = get_db()
    doc = await db.admins.find_one({"telegram_id": int(telegram_id)})
    return doc is not None


async def ensure_admins_from_env():
    """Ensure ADMIN_IDS from env are present in the admins collection."""
    db = get_db()
    for aid in core_config.ADMIN_IDS:
        await db.admins.update_one({"telegram_id": int(aid)}, {"$setOnInsert": {"telegram_id": int(aid), "added_at": utcnow()}}, upsert=True)


async def cancel_payment_for_user(round_id, number, telegram_id):
    """Mark the user's awaiting payment for this round+number as cancelled.
    Returns True if a payment was cancelled, False otherwise."""
    db = get_db()
    res = await db.payments.update_one(
        {"round_id": round_id, "number": number, "telegram_id": telegram_id, "status": {"$in": ["awaiting_proof", "awaiting_review"]}},
        {"$set": {"status": "cancelled", "cancelled_at": utcnow()}},
    )
    if res.modified_count:
        # Also release the number in the round doc
        await release_number(round_id, number)
        return True
    return False


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
