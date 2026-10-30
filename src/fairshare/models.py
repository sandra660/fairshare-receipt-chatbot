"""Data models (Pydantic).

Gemini returns its answers in exactly these shapes (structured output), and Pydantic validates them
before the app trusts them. Lists of small objects are used instead of dictionaries because they
translate cleanly into the JSON schema Gemini is given.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------- the receipt (read from the photo)
class Item(BaseModel):
    name: str = Field(description="Item name as printed, e.g. 'Chicken burger'")
    quantity: float = Field(1, description="How many were ordered on this line")
    total_price: float = Field(description="Price of the whole line = quantity x unit price")

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        return " ".join(v.split()) or "Item"


class Charge(BaseModel):
    """Anything added to or taken off the items: VAT, service, tip, delivery, discount."""
    name: str = Field(description="Name as printed, e.g. 'VAT 14%' or 'Service 12%'")
    kind: Literal["tax", "service", "tip", "delivery", "discount", "other"] = "other"
    amount: float = Field(description="Amount in money (not a percentage). Negative for discounts.")
    split: Literal["proportional", "equal"] = Field(
        "proportional", description="proportional = by what each person ordered; equal = same for everyone")


class Receipt(BaseModel):
    restaurant: str = "Unknown restaurant"
    date: str | None = Field(None, description="Date on the receipt as YYYY-MM-DD, if printed")
    currency: str = "EGP"
    items: list[Item] = Field(default_factory=list)
    charges: list[Charge] = Field(default_factory=list)
    subtotal: float | None = Field(None, description="Subtotal printed on the receipt (items only)")
    total: float | None = Field(None, description="Final total printed on the receipt")


# ---------------------------------------------------------------- who had what (read from the chat)
class Share(BaseModel):
    person: str
    weight: float = Field(1, description="Relative portion. Equal weights split evenly; 70 and 30 = 70/30")


class Assignment(BaseModel):
    item: int = Field(description="Item number from the numbered list (starting at 1)")
    shares: list[Share]


class ChatAction(BaseModel):
    """What Gemini understood from one chat message. Python does every calculation afterwards."""
    intent: Literal["assign", "question", "history", "settle", "other"] = Field(
        description="assign = who had what / who paid / corrections; question = about the current bill; "
                    "history = about past outings (spending, who owes whom); settle = someone paid their share back; "
                    "other = anything else")
    assignments: list[Assignment] | None = Field(
        None, description="For intent=assign: the COMPLETE updated list for ALL items mentioned so far, "
                          "not only the change")
    payer: str | None = Field(None, description="Person who paid the whole bill, if mentioned")
    settled: list[str] = Field(default_factory=list, description="For intent=settle: people who paid back")
    history_query: Literal["spending_by_person", "balances", "top_restaurants"] | None = None
    history_days: int | None = Field(None, description="Time window for history questions, e.g. 30 for 'this month'")
    reply: str = Field(description="Short friendly reply in the SAME language and style the user wrote in. "
                                   "Never calculate amounts yourself.")
