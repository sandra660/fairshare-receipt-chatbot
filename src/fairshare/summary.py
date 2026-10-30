"""Human-readable outputs: the WhatsApp message, per-person breakdowns and history tables."""
from .money import fmt
from .splitter import SplitResult, who_owes


def whatsapp_message(restaurant: str, result: SplitResult, payer: str | None, currency: str) -> str:
    lines = [f"🧾 {restaurant} - bill split with FairShare"]
    for p in sorted(result.people.values(), key=lambda p: -p.total_cents):
        lines.append(f"• {p.name}: {fmt(p.total_cents, currency)}")
    lines.append(f"Total: {fmt(sum(p.total_cents for p in result.people.values()), currency)}")
    owes = who_owes(result, payer)
    if owes:
        lines.append("")
        lines.append(f"💸 {payer} paid, so please send:")
        lines += [f"  {name} → {payer}: {fmt(cents, currency)}" for name, cents in owes.items()]
    lines.append("(Tax & service shared in proportion to what each person ordered.)")
    return "\n".join(lines)


def breakdown_rows(result: SplitResult, currency: str) -> list[dict]:
    return [{
        "Person": p.name,
        "Items": "; ".join(f"{name} {fmt(c, currency)}" for name, c in p.items),
        "Food": fmt(p.items_cents, currency),
        "Tax/service/tip": fmt(p.charges_cents, currency),
        "Total": fmt(p.total_cents, currency),
    } for p in sorted(result.people.values(), key=lambda p: -p.total_cents)]


def history_text(kind: str, rows: list[dict], days: int | None) -> str:
    period = f"in the last {days} days" if days else "across all your outings"
    if not rows:
        return f"No matching outings found {period}."
    if kind == "spending_by_person":
        out = [f"Spending {period}:"]
        out += [f"• {r['name']}: {fmt(r['spent_cents'], r['currency'])} over {r['outings']} outing(s)" for r in rows]
    elif kind == "balances":
        out = [f"Still unpaid {period}:"]
        out += [f"• {r['debtor']} owes {r['creditor']} {fmt(r['owed_cents'], r['currency'])}" for r in rows]
    else:
        out = [f"Most visited places {period}:"]
        out += [f"• {r['restaurant']}: {r['visits']} visit(s), {r['spent']:,.2f} in total" for r in rows]
    return "\n".join(out)
