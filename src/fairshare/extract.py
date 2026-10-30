"""Receipt photo -> structured Receipt, using Gemini's vision and structured output."""
import base64

from langchain_core.messages import HumanMessage, SystemMessage

from .models import Receipt

EXTRACT_INSTRUCTIONS = """You read restaurant receipts (English or Arabic) and return their contents as structured data.
Rules:
- items: one entry per printed line. total_price is the price of the whole line (quantity x unit price).
  Copy names as printed; if a name is in Arabic, keep it in Arabic.
- charges: everything that is not food or drink - VAT/tax (ضريبة), service (خدمة), tip, delivery, discounts (خصم).
  Use the money amount, never the percentage. Discounts are negative.
  Set split="equal" only for delivery fees and minimum-charge fees; everything else is "proportional".
- subtotal and total: copy them exactly as printed; leave null if not printed.
- currency: ISO code (EGP for Egyptian pounds / ج.م / LE).
- Do not invent lines that are not on the receipt. Do not do any maths beyond reading the numbers."""


def image_to_data_url(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


def extract_receipt(llm, image_bytes: bytes, mime_type: str = "image/jpeg") -> Receipt:
    structured = llm.with_structured_output(Receipt)
    message = HumanMessage(content=[
        {"type": "text", "text": "Extract this receipt."},
        {"type": "image_url", "image_url": image_to_data_url(image_bytes, mime_type)},
    ])
    receipt = structured.invoke([SystemMessage(content=EXTRACT_INSTRUCTIONS), message])
    return Receipt.model_validate(receipt)
