"""Deep-link payload helpers for the "tap a number -> start bot -> instantly
reserved" flow.

Telegram only allows a bot to open a private chat with a user in response to
a user action (there's no API to push a chat open on someone). The closest
thing to "automatic" we can offer is a single tap: a t.me/<bot>?start=<payload>
button that opens the private chat AND immediately triggers /start with the
number embedded, so the bot can reserve it right away without the user having
to search for the bot and tap the number again.

Payload format (must match Telegram's allowed charset [A-Za-z0-9_-]{1,64}):

    r_<encoded_chat_id>_<round_number>_<number>

Chat ids for groups/supergroups are negative, so we encode the sign as a
letter prefix instead of using '-' (which would collide with our separator).
"""

from __future__ import annotations


def _encode_chat_id(chat_id: int) -> str:
    return f"n{abs(chat_id)}" if chat_id < 0 else f"p{chat_id}"


def _decode_chat_id(token: str) -> int:
    sign = -1 if token[:1] == "n" else 1
    return sign * int(token[1:])


def build_reserve_payload(chat_id: int, round_number: int, number: int) -> str:
    return f"r_{_encode_chat_id(chat_id)}_{round_number}_{number}"


def parse_reserve_payload(payload: str | None) -> dict | None:
    """Returns {"chat_id", "round_number", "number"} or None if it isn't a
    (valid) reservation deep-link payload."""
    if not payload:
        return None
    try:
        prefix, chat_token, round_str, number_str = payload.split("_")
        if prefix != "r":
            return None
        return {
            "chat_id": _decode_chat_id(chat_token),
            "round_number": int(round_str),
            "number": int(number_str),
        }
    except (ValueError, IndexError):
        return None
