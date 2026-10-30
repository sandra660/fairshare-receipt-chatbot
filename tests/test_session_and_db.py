from datetime import timedelta

from fairshare.db import utcnow
from fairshare.extract import extract_receipt
from fairshare.models import Assignment, ChatAction, Share
from fairshare.session import BillSession
from conftest import FakeGemini, SAMPLE_JSON


def shares(*names):
    return [Share(person=n) for n in names]


FIRST = ChatAction(
    intent="assign", payer="Sara", reply="تمام! Got it.",
    assignments=[Assignment(item=1, shares=shares("Me")), Assignment(item=2, shares=shares("Sara", "Omar")),
                 Assignment(item=5, shares=shares("Me", "Sara", "Omar"))])
CORRECTION = ChatAction(
    intent="assign", reply="Fixed: Mona had a cola instead of Omar.",
    assignments=[Assignment(item=1, shares=shares("Me")), Assignment(item=2, shares=shares("Sara", "Omar")),
                 Assignment(item=5, shares=shares("Me", "Sara", "Mona"))])


def test_extract_receipt_sends_the_image(receipt):
    llm = FakeGemini([(r"image_url", receipt)])
    out = extract_receipt(llm, b"fake-jpeg-bytes")
    assert out.total == 1442.78 and len(out.items) == 7
    assert "data:image/jpeg;base64," in llm.calls[0]


def test_chat_flow_with_franco_arabic_and_correction(receipt, store):
    llm = FakeGemini([
        (r"omar mesh sharab cola", CORRECTION),
        (r"ana akalt el burger", FIRST.model_copy(update={"payer": "sara"})),
        (r"omar ba3atly", ChatAction(intent="settle", settled=["omar"], reply="Tamam!")),
        (r"spend", ChatAction(intent="history", history_query="spending_by_person", history_days=30, reply="Here:")),
    ])
    session = BillSession.start(llm, store, receipt, me="Me")

    turn = session.send("ana akalt el burger, sara w omar 2asamo el pizza, w e7na el talata sharbna cola. sara dafa3et")
    assert turn.intent == "assign" and session.payer == "Sara"
    assert set(turn.result.people) == {"Me", "Sara", "Omar"}
    assert "ana akalt el burger" in llm.calls[0] and "1. Classic Beef Burger" in llm.calls[0]  # state sent to Gemini

    turn = session.send("la2 omar mesh sharab cola, mona hya elly sharbet")
    assert set(turn.result.people) == {"Me", "Sara", "Omar", "Mona"}
    assert "Computed amounts" in llm.calls[1]  # Gemini sees the calculator's numbers, never makes its own

    doc = store.get(session.outing_id)
    assert doc["payer"] == "Sara" and len(doc["messages"]) == 4
    paid = {p["name"]: p["paid"] for p in doc["participants"]}
    assert paid == {"Me": False, "Sara": True, "Omar": False, "Mona": False}  # payer counts as paid

    turn = session.send("omar ba3atly el flos")
    assert "Marked as paid: Omar" in turn.reply
    assert {p["name"]: p["paid"] for p in store.get(session.outing_id)["participants"]}["Omar"] is True

    turn = session.send("How much did everyone spend this month?")
    assert turn.history.startswith("Spending in the last 30 days")

    reloaded = BillSession(llm, store, session.outing_id)  # state survives a reload from MongoDB
    assert reloaded.payer == "Sara" and len(reloaded.assignments) == 3


def test_aggregations_over_several_outings(receipt, store):
    from fairshare.splitter import compute_split

    def outing(assignments, payer, days_ago, restaurant):
        r = receipt.model_copy(update={"restaurant": restaurant})
        oid = store.create(r)
        store.save_split(oid, assignments, payer, compute_split(r, assignments))
        store.outings.update_one({"_id": store.get(oid)["_id"]}, {"$set": {"created_at": utcnow() - timedelta(days=days_ago)}})
        return oid

    all_items = [Assignment(item=i, shares=shares("Me", "Sara")) for i in range(1, 8)]
    o1 = outing(all_items, "Sara", 2, "Lotus & Lime Cafe")
    outing([Assignment(item=1, shares=shares("sara"))], "Me", 5, "Lotus & Lime Cafe")  # lowercase spelling
    outing(all_items, "Me", 10, "Lotus & Lime Cafe")
    outing(all_items, "Sara", 100, "Koshary Corner")

    spending = {r["name"]: r for r in store.spending_by_person(30)}
    assert spending["Me"]["outings"] == 2
    assert spending["Me"]["spent_cents"] + spending["Sara"]["spent_cents"] == 2 * 144278 + 55778  # + sara's burger + all charges
    assert spending["Sara"]["outings"] == 3          # "sara" and "Sara" are merged into one person

    balances = {(b["debtor"], b["creditor"]): b["owed_cents"] for b in store.balances()}
    assert set(balances) == {("Me", "Sara"), ("Sara", "Me")}
    store.mark_paid(o1, "me")
    assert {(b["debtor"], b["creditor"]): b["outings"] for b in store.balances()}[("Me", "Sara")] == 1

    top = store.top_restaurants()
    assert top[0]["restaurant"] == "Lotus & Lime Cafe" and top[0]["visits"] == 3
