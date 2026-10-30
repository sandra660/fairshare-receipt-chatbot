import pytest

from fairshare.models import Assignment, Charge, Item, Receipt, Share
from fairshare.money import allocate, to_cents
from fairshare.splitter import check_receipt, compute_split, who_owes


def A(item, *people, weights=None):
    weights = weights or [1] * len(people)
    return Assignment(item=item, shares=[Share(person=p, weight=w) for p, w in zip(people, weights)])


def test_allocate_always_adds_up_exactly():
    assert allocate(1000, {"A": 1, "B": 1, "C": 1}) == {"A": 334, "B": 333, "C": 333}
    for total in [1, 99, 17718, 13560, -5000]:
        parts = allocate(total, {"A": 3, "B": 1.5, "C": 0.7})
        assert sum(parts.values()) == total


def test_to_cents_avoids_float_errors():
    assert to_cents(0.1) + to_cents(0.2) == to_cents(0.3)
    assert to_cents("177.18") == 17718


def full_assignment():
    return [
        A(1, "Me"),                       # burger 245
        A(2, "Sara", "Omar"),             # pizza 210 shared
        A(3, "Omar"),                     # fettuccine 230
        A(4, "Mona"),                     # salad 145
        A(5, "Me", "Sara", "Omar"),       # 3 colas 105
        A(6, "Mona"),                     # mango juice 75
        A(7, "Me", "Sara", "Omar", "Mona"),  # cake 120 shared by everyone
    ]


def test_sample_split_matches_receipt_total_to_the_piaster(receipt):
    result = compute_split(receipt, full_assignment())
    assert result.is_complete
    assert sum(p.total_cents for p in result.people.values()) == to_cents(receipt.total) == 144278
    # food: Me 245+35+30=310, Sara 105+35+30=170, Omar 105+230+35+30=400, Mona 145+75+30=250
    food = {n: p.items_cents for n, p in result.people.items()}
    assert food == {"Me": 31000, "Sara": 17000, "Omar": 40000, "Mona": 25000}
    # charges are proportional: Omar ordered the most, so he pays the most service + VAT
    charges = {n: p.charges_cents for n, p in result.people.items()}
    assert max(charges, key=charges.get) == "Omar"
    assert charges["Omar"] == pytest.approx(31278 * 400 / 1130, abs=1)


def test_custom_weights_and_name_spelling(receipt):
    result = compute_split(receipt, [A(2, "sara", "Me", weights=[70, 30]), A(1, "SARA ")])
    assert set(result.people) == {"Sara", "Me"}           # 'sara', 'SARA ' -> one tidy name
    assert result.people["Sara"].items_cents == 14700 + 24500
    assert result.people["Me"].items_cents == 6300


def test_unassigned_items_are_reported(receipt):
    result = compute_split(receipt, [A(1, "Me")])
    assert not result.is_complete and 2 in result.unassigned
    assert any("Not assigned yet" in w for w in result.warnings)


def test_invalid_item_numbers_are_ignored(receipt):
    result = compute_split(receipt, [A(99, "Me"), A(1, "Me")])
    assert any("item number 99" in w for w in result.warnings)


def test_equal_charge_and_discount():
    r = Receipt(items=[Item(name="A", total_price=300), Item(name="B", total_price=100)],
                charges=[Charge(name="Delivery", kind="delivery", amount=20, split="equal"),
                         Charge(name="Promo", kind="discount", amount=-40)], total=380)
    res = compute_split(r, [A(1, "X"), A(2, "Y")])
    assert res.people["X"].total_cents == 30000 + 1000 - 3000
    assert res.people["Y"].total_cents == 10000 + 1000 - 1000
    assert sum(p.total_cents for p in res.people.values()) == 38000


def test_reading_errors_are_detected(receipt):
    wrong = receipt.model_copy(update={"subtotal": 1000.0})
    assert any("subtotal" in w for w in check_receipt(wrong))
    assert check_receipt(receipt) == []


def test_who_owes_the_payer(receipt):
    result = compute_split(receipt, full_assignment())
    owes = who_owes(result, "sara")
    assert set(owes) == {"Me", "Omar", "Mona"}
    assert owes["Omar"] == result.people["Omar"].total_cents
