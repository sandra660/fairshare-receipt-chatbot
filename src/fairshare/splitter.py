"""The bill-splitting engine. Pure Python, no AI: deterministic, exact and fully tested.

1. Each item is split between the people who had it, by their weights (even split by default).
2. Each charge (VAT, service, tip, discount) is split in proportion to what each person ordered,
   or equally if the charge is marked "equal".
3. Everything is done in whole piasters with largest-remainder rounding, so the parts always add
   up exactly to the receipt total.
"""
from dataclasses import dataclass, field

from .models import Assignment, Receipt
from .money import allocate, to_cents


@dataclass
class PersonBill:
    name: str
    items: list[tuple[str, int]] = field(default_factory=list)   # (item description, cents)
    charges: list[tuple[str, int]] = field(default_factory=list)  # (charge name, cents)

    @property
    def items_cents(self) -> int:
        return sum(c for _, c in self.items)

    @property
    def charges_cents(self) -> int:
        return sum(c for _, c in self.charges)

    @property
    def total_cents(self) -> int:
        return self.items_cents + self.charges_cents


@dataclass
class SplitResult:
    people: dict[str, PersonBill]
    unassigned: list[int]            # item numbers nobody claimed yet
    bill_total_cents: int            # items + charges as read from the receipt
    printed_total_cents: int | None  # the total printed on the receipt, for a cross-check
    warnings: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.unassigned and bool(self.people)


def display_name(name: str) -> str:
    """'sara' -> 'Sara', 'SARA' -> 'Sara'; names in other scripts (e.g. Arabic) stay as written."""
    name = " ".join(name.split())
    return name.title() if name.isascii() and (name.islower() or name.isupper()) else name


def canonical_names(names) -> dict[str, str]:
    """Map 'sara', 'SARA ' and 'Sara' to one tidy spelling."""
    canon: dict[str, str] = {}
    for n in names:
        key = n.strip().casefold()
        if key and key not in canon:
            canon[key] = display_name(n)
    return canon


def check_receipt(receipt: Receipt) -> list[str]:
    """Cross-check the numbers read from the photo, so reading mistakes are caught early."""
    warnings = []
    items = sum(to_cents(i.total_price) for i in receipt.items)
    charges = sum(to_cents(c.amount) for c in receipt.charges)
    if receipt.subtotal is not None and abs(items - to_cents(receipt.subtotal)) > 1:
        warnings.append(f"Items add up to {items / 100:.2f}, but the receipt's subtotal is "
                        f"{receipt.subtotal:.2f}. Please check the item prices.")
    if receipt.total is not None and abs(items + charges - to_cents(receipt.total)) > 1:
        warnings.append(f"Items + charges = {(items + charges) / 100:.2f}, but the receipt's total is "
                        f"{receipt.total:.2f}. Please check the charges.")
    return warnings


def compute_split(receipt: Receipt, assignments: list[Assignment]) -> SplitResult:
    canon = canonical_names(s.person for a in assignments for s in a.shares)
    people: dict[str, PersonBill] = {name: PersonBill(name) for name in canon.values()}
    warnings: list[str] = []

    # 1) items
    assigned = set()
    for a in assignments:
        if not 1 <= a.item <= len(receipt.items):
            warnings.append(f"Ignored item number {a.item}: the receipt has {len(receipt.items)} items.")
            continue
        weights: dict[str, float] = {}
        for s in a.shares:
            if s.weight > 0:
                name = canon[s.person.strip().casefold()]
                weights[name] = weights.get(name, 0) + s.weight
        if not weights:
            continue
        item = receipt.items[a.item - 1]
        assigned.add(a.item)
        parts = allocate(to_cents(item.total_price), weights)
        for name, cents in parts.items():
            label = item.name if len(parts) == 1 else f"{item.name} (shared {len(parts)} ways)"
            people[name].items.append((label, cents))
    unassigned = [i for i in range(1, len(receipt.items) + 1) if i not in assigned]

    # 2) charges
    food = {name: p.items_cents for name, p in people.items() if p.items_cents > 0}
    for charge in receipt.charges:
        if not food:
            break
        weights = {name: 1 for name in food} if charge.split == "equal" else food
        for name, cents in allocate(to_cents(charge.amount), weights).items():
            people[name].charges.append((charge.name, cents))

    bill_total = sum(to_cents(i.total_price) for i in receipt.items) + sum(to_cents(c.amount) for c in receipt.charges)
    printed = to_cents(receipt.total) if receipt.total is not None else None
    if unassigned:
        names = ", ".join(receipt.items[i - 1].name for i in unassigned)
        warnings.append(f"Not assigned yet: {names}. Charges are only shared over assigned items.")
    return SplitResult(people, unassigned, bill_total, printed, warnings + check_receipt(receipt))


def who_owes(result: SplitResult, payer: str | None) -> dict[str, int]:
    """If one person paid the whole bill, everyone else owes them their own total."""
    if not payer:
        return {}
    payer_key = payer.strip().casefold()
    return {name: p.total_cents for name, p in result.people.items() if name.casefold() != payer_key}
