"""MongoDB storage.

One document per receipt (an "outing"). Everything about that bill lives inside it, which is the
document model's strength: no joins are needed to load or save a bill.

{
  "_id": ObjectId, "restaurant": "Nile Bites Cafe", "date": "2026-10-29", "currency": "EGP",
  "created_at": ISODate,
  "receipt":      {items: [...], charges: [...], subtotal, total},     # what Gemini read (edited by the user)
  "assignments":  [{item: 1, shares: [{person: "Sara", weight: 1}]}],  # who had what
  "payer": "Sara",
  "participants": [{name: "Omar", items_cents: 19000, charges_cents: 4920, total_cents: 23920, paid: false}],
  "messages":     [{role: "user", content: "...", at: ISODate}]
}

The history questions are answered with aggregation pipelines ($match -> $unwind -> $group -> $sort).
"""
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import DESCENDING

from .models import Assignment, Receipt
from .splitter import SplitResult, display_name


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class OutingStore:
    def __init__(self, database):
        """`database` is a pymongo Database (or a mongomock one in the tests)."""
        self.outings = database["outings"]
        self.outings.create_index([("created_at", DESCENDING)])
        self.outings.create_index("participants.name")

    @classmethod
    def connect(cls, uri: str, db_name: str):
        from pymongo import MongoClient

        client = MongoClient(uri, serverSelectionTimeoutMS=5000, appname="fairshare")
        client.admin.command("ping")  # fail fast with a clear error if the URI/password is wrong
        return cls(client[db_name])

    # ---------------------------------------------------------------- writes
    def create(self, receipt: Receipt) -> str:
        doc = {
            "restaurant": receipt.restaurant,
            "date": receipt.date,
            "currency": receipt.currency,
            "created_at": utcnow(),
            "receipt": receipt.model_dump(),
            "assignments": [],
            "payer": None,
            "participants": [],
            "messages": [],
        }
        return str(self.outings.insert_one(doc).inserted_id)

    def update_receipt(self, outing_id: str, receipt: Receipt) -> None:
        self.outings.update_one({"_id": ObjectId(outing_id)}, {"$set": {
            "receipt": receipt.model_dump(), "restaurant": receipt.restaurant,
            "date": receipt.date, "currency": receipt.currency}})

    def save_split(self, outing_id: str, assignments: list[Assignment], payer: str | None,
                   result: SplitResult) -> None:
        existing = self.get(outing_id) or {}
        already_paid = {p["name"] for p in existing.get("participants", []) if p.get("paid")}
        payer_key = (payer or "").casefold()
        participants = [{
            "name": p.name,
            "items_cents": p.items_cents,
            "charges_cents": p.charges_cents,
            "total_cents": p.total_cents,
            # the payer has nothing to pay back; keep earlier "paid" marks
            "paid": p.name.casefold() == payer_key or p.name in already_paid,
        } for p in result.people.values()]
        self.outings.update_one({"_id": ObjectId(outing_id)}, {"$set": {
            "assignments": [a.model_dump() for a in assignments],
            "payer": payer,
            "participants": participants,
        }})

    def add_message(self, outing_id: str, role: str, content: str) -> None:
        self.outings.update_one({"_id": ObjectId(outing_id)},
                                {"$push": {"messages": {"role": role, "content": content, "at": utcnow()}}})

    def mark_paid(self, outing_id: str, name: str, paid: bool = True) -> bool:
        """Positional operator `$`: update only the matching element inside the participants array."""
        res = self.outings.update_one(
            {"_id": ObjectId(outing_id), "participants.name": {"$regex": f"^{_escape(name)}$", "$options": "i"}},
            {"$set": {"participants.$.paid": paid}})
        return res.modified_count > 0

    def delete(self, outing_id: str) -> None:
        self.outings.delete_one({"_id": ObjectId(outing_id)})

    # ---------------------------------------------------------------- reads
    def get(self, outing_id: str) -> dict | None:
        return self.outings.find_one({"_id": ObjectId(outing_id)})

    def recent(self, limit: int = 20) -> list[dict]:
        return list(self.outings.find({}, {"restaurant": 1, "date": 1, "created_at": 1, "currency": 1,
                                           "receipt.total": 1}).sort("created_at", DESCENDING).limit(limit))

    # ---------------------------------------------------------------- analytics (aggregation pipelines)
    def _since(self, days: int | None) -> list[dict]:
        return [{"$match": {"created_at": {"$gte": utcnow() - timedelta(days=days)}}}] if days else []

    def spending_by_person(self, days: int | None = None) -> list[dict]:
        """Total each person spent (their own share, whoever paid) and on how many outings."""
        pipeline = self._since(days) + [
            {"$unwind": "$participants"},
            # group names ignoring capitals, so "sara" and "Sara" count as one person
            {"$group": {"_id": {"name": {"$toLower": "$participants.name"}, "currency": "$currency"},
                        "spent_cents": {"$sum": "$participants.total_cents"},
                        "outings": {"$sum": 1}}},
            {"$sort": {"spent_cents": -1}},
        ]
        return [{"name": display_name(r["_id"]["name"]), "currency": r["_id"]["currency"],
                 "spent_cents": r["spent_cents"], "outings": r["outings"]}
                for r in self.outings.aggregate(pipeline)]

    def balances(self, days: int | None = None) -> list[dict]:
        """Unpaid shares: who still owes money to whom, summed over all outings."""
        pipeline = self._since(days) + [
            {"$match": {"payer": {"$ne": None}}},
            {"$unwind": "$participants"},
            {"$match": {"participants.paid": False}},
            {"$group": {"_id": {"debtor": {"$toLower": "$participants.name"}, "creditor": {"$toLower": "$payer"},
                                "currency": "$currency"},
                        "owed_cents": {"$sum": "$participants.total_cents"},
                        "outings": {"$sum": 1}}},
            {"$sort": {"owed_cents": -1}},
        ]
        return [{"debtor": display_name(r["_id"]["debtor"]), "creditor": display_name(r["_id"]["creditor"]),
                 "currency": r["_id"]["currency"],
                 "owed_cents": r["owed_cents"], "outings": r["outings"]}
                for r in self.outings.aggregate(pipeline)]

    def top_restaurants(self, days: int | None = None, limit: int = 5) -> list[dict]:
        pipeline = self._since(days) + [
            {"$group": {"_id": "$restaurant", "visits": {"$sum": 1},
                        "spent": {"$sum": {"$ifNull": ["$receipt.total", 0]}}}},
            {"$sort": {"visits": -1, "spent": -1}},
            {"$limit": limit},
        ]
        return [{"restaurant": r["_id"], "visits": r["visits"], "spent": round(r["spent"], 2)}
                for r in self.outings.aggregate(pipeline)]


def _escape(text: str) -> str:
    import re
    return re.escape(text.strip())
