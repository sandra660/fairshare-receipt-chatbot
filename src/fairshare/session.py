"""One bill being split: ties together Gemini, the split engine and MongoDB.

    photo ─► Gemini (vision) ─► Receipt ─► user checks/edits ─► MongoDB
    chat  ─► Gemini (understand) ─► ChatAction ─► split engine (Python maths) ─► reply + MongoDB
"""
from dataclasses import dataclass

from .db import OutingStore
from .interpreter import interpret
from .models import Assignment, Receipt
from .splitter import SplitResult, compute_split, display_name
from .summary import history_text


@dataclass
class Turn:
    reply: str
    intent: str
    result: SplitResult | None = None
    history: str | None = None


class BillSession:
    def __init__(self, llm, store: OutingStore, outing_id: str, me: str = "Me"):
        self.llm, self.store, self.outing_id, self.me = llm, store, outing_id, me
        doc = store.get(outing_id)
        self.receipt = Receipt.model_validate(doc["receipt"])
        self.assignments = [Assignment.model_validate(a) for a in doc.get("assignments", [])]
        self.payer = display_name(doc["payer"]) if doc.get("payer") else None
        self.messages = [{"role": m["role"], "content": m["content"]} for m in doc.get("messages", [])]
        self.result = compute_split(self.receipt, self.assignments) if self.assignments else None

    @classmethod
    def start(cls, llm, store: OutingStore, receipt: Receipt, me: str = "Me") -> "BillSession":
        return cls(llm, store, store.create(receipt), me)

    def update_receipt(self, receipt: Receipt) -> None:
        """Called when the user edits the item table."""
        self.receipt = receipt
        self.store.update_receipt(self.outing_id, receipt)
        self._recompute()

    def _recompute(self) -> None:
        self.result = compute_split(self.receipt, self.assignments) if self.assignments else None
        if self.result:
            self.store.save_split(self.outing_id, self.assignments, self.payer, self.result)

    def send(self, message: str) -> Turn:
        action = interpret(self.llm, message, self.receipt, self.assignments, self.payer, self.result,
                           me=self.me, recent_chat=self.messages)
        turn = Turn(reply=action.reply, intent=action.intent, result=self.result)

        if action.intent == "assign":
            if action.assignments is not None:
                self.assignments = action.assignments
            if action.payer:
                self.payer = display_name(action.payer)
            self._recompute()
            turn.result = self.result

        elif action.intent == "settle":
            done = [name for name in action.settled if self.store.mark_paid(self.outing_id, name)]
            if done:
                turn.reply = (action.reply + "\n" if action.reply else "") + "✅ Marked as paid: " + ", ".join(display_name(n) for n in done)

        elif action.intent == "history" and action.history_query:
            q, days = action.history_query, action.history_days
            rows = getattr(self.store, q)(days)
            turn.history = history_text(q, rows, days)

        self.messages += [{"role": "user", "content": message}, {"role": "assistant", "content": turn.reply}]
        self.store.add_message(self.outing_id, "user", message)
        self.store.add_message(self.outing_id, "assistant", turn.reply)
        return turn
