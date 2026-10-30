"""Understand a chat message (English, Arabic or Franco-Arabic) and turn it into a ChatAction.

Gemini only *understands* the message. It never calculates money: the split engine does that.
"""
from langchain_core.messages import HumanMessage, SystemMessage

from .models import Assignment, ChatAction, Receipt
from .money import fmt
from .splitter import SplitResult

SYSTEM = """You are FairShare, a friendly assistant that helps friends split a restaurant bill fairly.
Users write in English, Arabic, or Franco-Arabic (Arabic in Latin letters with numbers, e.g.
"ana akalt el burger", "sara w omar 2asamo el pizza", "kolena sharbna cola", "mona dafa3et").
Understand all three and reply in the same language and style the user used.

The user's own name is "{me}". "I", "me", "ana", "أنا", "ana w" refer to {me}.
"everyone", "kolena", "kollena", "كلنا", "all of us" = every person mentioned so far (plus {me}).

Your job for each message:
- intent=assign when the user says who had what, corrects something, adds people, or says who paid.
  Return in `assignments` the COMPLETE updated list for every item that has been assigned so far
  (start from the current assignment below and apply the change). Use item numbers from the list.
  Shared items: one share per person, equal weights unless the user gives proportions ("70/30" -> 70 and 30;
  "Omar ate twice as much" -> Omar 2, other 1). If several units of an item were ordered and each person had
  one, still use one assignment with equal weights.
  Set `payer` if someone paid the whole bill ("Sara paid", "sara dafa3et", "سارة دفعت").
- intent=question for questions about the current bill ("how much does Omar pay?"). Answer using ONLY the
  computed amounts given below; never calculate new amounts yourself.
- intent=settle when someone paid their share back ("Omar paid me back", "omar ba3atly el flos").
- intent=history for questions about past outings: total spending ("how much did I spend this month?") ->
  spending_by_person; who owes whom / unpaid money -> balances; favourite places -> top_restaurants.
  Set history_days if a period is given (week=7, month=30, year=365).
- intent=other for anything else; reply briefly and explain what you can do.
Keep `reply` to one or two short sentences. Never invent items or people."""


def describe_state(receipt: Receipt, assignments: list[Assignment], payer: str | None,
                   result: SplitResult | None) -> str:
    lines = ["Items on the receipt:"]
    lines += [f"{i}. {it.name} x{it.quantity:g} - {it.total_price:.2f}" for i, it in enumerate(receipt.items, 1)]
    lines.append("\nCurrent assignment:")
    if assignments:
        for a in assignments:
            who = ", ".join(f"{s.person} ({s.weight:g})" for s in a.shares)
            lines.append(f"- item {a.item}: {who}")
    else:
        lines.append("- nothing assigned yet")
    lines.append(f"\nPaid by: {payer or 'not said yet'}")
    if result and result.people:
        lines.append("\nComputed amounts (from the calculator):")
        lines += [f"- {p.name}: {fmt(p.total_cents, receipt.currency)}" for p in result.people.values()]
    return "\n".join(lines)


def interpret(llm, message: str, receipt: Receipt, assignments: list[Assignment], payer: str | None,
              result: SplitResult | None, me: str = "Me", recent_chat: list[dict] | None = None) -> ChatAction:
    chat = "\n".join(f"{m['role']}: {m['content']}" for m in (recent_chat or [])[-6:]) or "(start of chat)"
    prompt = [
        SystemMessage(content=SYSTEM.format(me=me)),
        HumanMessage(content=f"{describe_state(receipt, assignments, payer, result)}\n\n"
                             f"Recent chat:\n{chat}\n\nNew message from {me}: {message}"),
    ]
    action = llm.with_structured_output(ChatAction).invoke(prompt)
    return ChatAction.model_validate(action)
