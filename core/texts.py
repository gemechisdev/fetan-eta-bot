from core.i18n import t


def build_board_text(round_doc, lang: str) -> str:
    cfg = round_doc["config"]
    total = cfg["total_numbers"]
    left = sum(1 for n in round_doc["numbers"] if n["status"] == "available")
    prizes = cfg["prizes"]
    results = round_doc.get("draw", {}).get("results", [])

    def prize_icon(index: int) -> str:
        return {0: "🥇", 1: "🥈", 2: "🥉"}.get(index, "🎖")

    currency = t(lang, "currency")
    prize_lines = "\n".join(
        t(lang, "board_prize_line", icon=prize_icon(i), prize=p, currency=currency) for i, p in enumerate(prizes)
    )

    lines = [
        t(lang, "board_title", round_number=round_doc["round_number"]),
        "",
        t(lang, "board_ticket_price", price=cfg["ticket_price"], currency=currency),
        t(lang, "board_left_numbers", left=left, total=total),
        "",
        t(lang, "board_prize_money", prize_lines=prize_lines),
    ]

    if results:
        lines.extend(["", t(lang, "board_winners_header")])
        for r in results:
            lines.append(
                t(
                    lang,
                    "board_winner_line",
                    icon=prize_icon(r["place"] - 1),
                    place=r["place"],
                    number=r["number"],
                    who=format_user_identity(r.get("display_name"), r.get("username"), r.get("telegram_id")),
                    prize=r["prize"],
                    currency=currency,
                )
            )
        if round_doc.get("draw", {}).get("seed_hash"):
            lines.extend(["", t(lang, "board_seed_hash", hash=round_doc["draw"]["seed_hash"])])

    lines.extend(["", t(lang, "board_choose_number")])

    return "\n".join(lines)


_BOLD_SANS_DIGIT_BASE = 0x1D7EC  # Mathematical Sans-Serif Bold Digit Zero


def _bold_digits(n: int) -> str:
    """Convert an integer to Mathematical Sans-Serif Bold digits (𝟬-𝟵), to
    match the stylized 'ROUND #𝟭' heading used in the results announcement."""
    return "".join(chr(_BOLD_SANS_DIGIT_BASE + int(d)) for d in str(n))


def build_results_text(round_doc, results, lang: str) -> str:
    def result_icon(place: int) -> str:
        return {1: "🥇", 2: "🥈", 3: "🥉"}.get(place, "🎖")

    currency = t(lang, "currency")
    prize_strs = [f"{r['prize']:,}" for r in results]
    width = max((len(p) for p in prize_strs), default=0)

    result_lines = []
    for r, prize_str in zip(results, prize_strs):
        pad = " " * (width - len(prize_str))
        result_lines.append(
            t(lang, "results_line", icon=result_icon(r["place"]), number=r["number"], pad=pad, prize=prize_str, currency=currency)
        )

    draw = round_doc.get("draw", {})
    lines = [
        "╔═══━━━━━∙•∙◦❉◦∙•∙━━━━━═══╗",
        f"┣   {t(lang, 'results_title', round_number=_bold_digits(round_doc['round_number']))}",
        "┣━━━━━━━━━━━━━━━━━━━━━",
        *[f"┣ {line}" for line in result_lines],
        "┣━━━━━━━━━━━━━━━━━━━━━",
        f"┣ {t(lang, 'results_hash')} <code>{draw.get('seed_hash')}</code>",
        f"┣ {t(lang, 'results_seed')} <code>{draw.get('seed')}</code>",
        "╚═══━━━━━∙•∙◦❉◦∙•∙━━━━━═══╝",
    ]
    return "\n".join(lines)


def format_user_identity(display_name: str | None, username: str | None, telegram_id: int | None) -> str:
    """Return a standardized string: Display Name - @username - id
    Use 'None' for missing username and '-' for missing display name."""
    disp = display_name if display_name else "-"
    userpart = f"@{username}" if username else "None"
    idpart = str(telegram_id) if telegram_id else "None"
    return f"{disp} - {userpart} - {idpart}"
