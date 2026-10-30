"""Generate the sample receipt image (fictional café) used for demos and tests.

Usage: python scripts/make_sample_receipt.py
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

RECEIPT = {
    "restaurant": "Lotus & Lime Cafe",
    "date": "2026-10-29",
    "currency": "EGP",
    "items": [
        {"name": "Classic Beef Burger", "quantity": 1, "total_price": 245.00},
        {"name": "Margherita Pizza", "quantity": 1, "total_price": 210.00},
        {"name": "Chicken Fettuccine", "quantity": 1, "total_price": 230.00},
        {"name": "Caesar Salad", "quantity": 1, "total_price": 145.00},
        {"name": "Coca-Cola", "quantity": 3, "total_price": 105.00},
        {"name": "Fresh Mango Juice", "quantity": 1, "total_price": 75.00},
        {"name": "Molten Cake", "quantity": 1, "total_price": 120.00},
    ],
    "charges": [
        {"name": "Service 12%", "kind": "service", "amount": 135.60, "split": "proportional"},
        {"name": "VAT 14%", "kind": "tax", "amount": 177.18, "split": "proportional"},
    ],
    "subtotal": 1130.00,
    "total": 1442.78,
}


def main():
    W = 560
    big, reg, small = (ImageFont.truetype(FONT, s) for s in (30, 21, 17))
    lines = []  # (text, font, align)
    lines += [("LOTUS & LIME CAFE", big, "c"), ("26 July St., Zamalek, Cairo", small, "c"),
              ("Tel: 02 0000 0000  (sample receipt)", small, "c"), ("", reg, "l"),
              ("Date: 29/10/2026      Time: 21:14", small, "l"), ("Table: 7     Guests: 4    Check #4471", small, "l"),
              ("-" * 44, small, "l"), ("QTY  ITEM                       AMOUNT", small, "l"), ("-" * 44, small, "l")]
    for it in RECEIPT["items"]:
        lines.append((f"{it['quantity']:>2}   {it['name']:<24}{it['total_price']:>10.2f}", small, "l"))
        if it["quantity"] > 1:
            lines.append((f"       @ {it['total_price'] / it['quantity']:.2f}", small, "l"))
    lines += [("-" * 44, small, "l"),
              (f"{'Subtotal':<34}{RECEIPT['subtotal']:>10.2f}", small, "l")]
    for ch in RECEIPT["charges"]:
        lines.append((f"{ch['name']:<34}{ch['amount']:>10.2f}", small, "l"))
    lines += [("=" * 44, small, "l"), (f"TOTAL EGP{RECEIPT['total']:>15.2f}", big, "l"), ("=" * 44, small, "l"),
              ("", reg, "l"), ("Paid by: VISA ****4821", small, "l"), ("", reg, "l"),
              ("Thank you! See you soon :)", reg, "c")]

    H = 60 + sum((f.size + 12) for _, f, _ in lines) + 40
    img = Image.new("RGB", (W, H), (250, 248, 242))
    d = ImageDraw.Draw(img)
    y = 50
    for text, font, align in lines:
        w = d.textlength(text, font=font)
        x = (W - w) / 2 if align == "c" else 40
        d.text((x, y), text, fill=(35, 35, 40), font=font)
        y += font.size + 12
    # make it look like a photo: slight rotation on a table-coloured background + blur
    bg = Image.new("RGB", (W + 120, H + 120), (120, 96, 72))
    rotated = img.rotate(2.2, expand=True, fillcolor=(120, 96, 72))
    bg.paste(rotated, ((bg.width - rotated.width) // 2, (bg.height - rotated.height) // 2))
    bg = bg.filter(ImageFilter.GaussianBlur(0.6))
    out = ROOT / "samples"
    out.mkdir(exist_ok=True)
    bg.save(out / "sample_receipt.jpg", quality=88)
    (out / "sample_receipt.json").write_text(json.dumps(RECEIPT, indent=2))
    print("Saved samples/sample_receipt.jpg and samples/sample_receipt.json")


if __name__ == "__main__":
    main()
