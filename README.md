# 🧾 FairShare: Split the Restaurant Bill by Chatting

Friends eat out, one receipt arrives, and nobody wants to do the maths.
**FairShare** reads a photo of the receipt, lets the group say who had what in **English, Arabic or Franco-Arabic**,
and calculates exactly what each person owes. Tax, service and tip are shared **in proportion to what each person ordered**.

> **You:** *ana akalt el burger, sara w omar 2asamo el pizza, w kolena 2asamna el cake. sara dafa3et*
> **FairShare:** *تمام! Sara paid, so everyone else owes her their share.*
>
> | Person | Food | Tax / service | **Total** |
> |---|---|---|---|
> | Omar | 400.00 | 110.72 | **510.72 EGP** |
> | Sandra | 310.00 | 85.81 | **395.81 EGP** |
> | … | | | |

Built with **Python, LangChain, Google Gemini (vision + structured output), MongoDB and Streamlit**.

| Chat in English, Arabic or Franco-Arabic | Exact split + WhatsApp summary |
|---|---|
| ![FairShare chat](docs/screenshot-chat.png) | ![FairShare split](docs/screenshot-split.png) |

## Features

| | |
|---|---|
| 📸 **Receipt reading** | Gemini reads the photo and returns structured JSON (items, quantities, VAT, service, discounts), validated with Pydantic. The items appear in an **editable table**, and the app cross-checks them against the printed subtotal and total to catch reading mistakes. |
| 💬 **Multilingual chat** | Understands English, Arabic and Franco-Arabic ("ana", "kolena", "dafa3et"). Handles corrections (*"actually Omar didn't have cola"*), shared items and custom ratios (*"split the pasta 70/30"*), and replies in the user's language and style. |
| 🧮 **Exact, fair maths in Python** | The AI never calculates money. Gemini only turns the message into a structured action, and a tested Python engine does every calculation in whole piasters. Largest-remainder rounding makes everyone's shares add up **exactly** to the receipt total. |
| 🍃 **MongoDB** | One document per outing, holding the receipt, assignments, payer, participants and chat. Aggregation pipelines answer *"how much did I spend this month?"*, *"who still owes whom?"* and *"where do we go most?"*. |
| 📲 **Share** | A ready-to-paste WhatsApp summary, plus "paid back" checkboxes that update MongoDB. |
| ✅ **Tests** | 12 pytest tests with a fake Gemini and an in-memory MongoDB (mongomock). GitHub Actions runs them on every push. |

## How it works

```mermaid
flowchart LR
    P([Receipt photo]) --> V[Gemini vision<br/>structured output]
    V --> R[Receipt JSON<br/>validated by Pydantic]
    R --> E[Editable table +<br/>subtotal/total check]
    E --> M[(MongoDB<br/>outings)]
    C([Chat message<br/>EN / عربي / Franco]) --> I[Gemini: understand<br/>→ ChatAction JSON]
    I -- assign / correct --> S[Split engine<br/>Python, piasters]
    S --> M
    I -- settle --> M
    I -- history --> A[Aggregation<br/>pipelines] --> M
    S --> O([Totals + WhatsApp message])
```

**Why the AI does not do the maths.** Language models make arithmetic mistakes, and a bill must be exact to the piaster.
So Gemini only *understands* the photo and the messages, returning validated JSON such as
`{"intent": "assign", "assignments": [{"item": 2, "shares": [{"person": "Sara", "weight": 1}, {"person": "Omar", "weight": 1}]}], "payer": "Sara"}`.
Deterministic Python code then calculates the split ([`splitter.py`](src/fairshare/splitter.py)).

### The fair-split rule
1. Each item is split between the people who had it: evenly, or by the given weights (70/30).
2. Each charge (VAT, service, tip, discount) is split **in proportion to each person's food total**. Delivery-type charges can be split equally instead.
3. Everything is calculated in whole piasters. Leftover piasters from rounding go to the people with the largest remainders, so the parts always add up to the receipt total.

## MongoDB design

One **document per outing**. Everything about a bill lives together, so loading or saving a bill is a single read or write with no joins:

```json
{
  "_id": "ObjectId",
  "restaurant": "Lotus & Lime Cafe", "date": "2026-10-29", "currency": "EGP", "created_at": "ISODate",
  "receipt": { "items": [{"name": "Margherita Pizza", "quantity": 1, "total_price": 210.0}],
               "charges": [{"name": "VAT 14%", "kind": "tax", "amount": 177.18, "split": "proportional"}],
               "subtotal": 1130.0, "total": 1442.78 },
  "assignments": [{"item": 2, "shares": [{"person": "Sara", "weight": 1}, {"person": "Omar", "weight": 1}]}],
  "payer": "Sara",
  "participants": [{"name": "Omar", "items_cents": 40000, "charges_cents": 11072, "total_cents": 51072, "paid": false}],
  "messages": [{"role": "user", "content": "ana akalt el burger…", "at": "ISODate"}]
}
```

- **Indexes:** `created_at` (recent bills, time filters) and `participants.name` (per-person queries).
- **Positional update:** `{"$set": {"participants.$.paid": true}}` marks one person as paid inside the array.
- **Aggregation pipeline:** who still owes whom ([`db.py`](src/fairshare/db.py)):

```python
[{"$match": {"created_at": {"$gte": since}, "payer": {"$ne": None}}},
 {"$unwind": "$participants"},
 {"$match": {"participants.paid": False}},
 {"$group": {"_id": {"debtor": "$participants.name", "creditor": "$payer", "currency": "$currency"},
             "owed_cents": {"$sum": "$participants.total_cents"}}},
 {"$sort": {"owed_cents": -1}}]
```

## Run it locally

**You need:** Python 3.10+, a free [Gemini API key](https://aistudio.google.com/apikey) and a free MongoDB Atlas cluster.

### 1. Create the free MongoDB database (about 5 minutes)
1. Sign up at [mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas/register) and create a **free (M0)** cluster.
2. **Database Access** → add a database user with a username and password.
3. **Network Access** → *Add IP Address* → *Add current IP address*.
4. **Clusters** → **Connect** → **Drivers** → copy the connection string (`mongodb+srv://…`) and put your password in it.

(Or use a local MongoDB: `MONGODB_URI=mongodb://localhost:27017`.)

### 2. Install and start
```bash
git clone https://github.com/sandra660/fairshare-receipt-chatbot.git
cd fairshare-receipt-chatbot
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
# open .env: paste GOOGLE_API_KEY and MONGODB_URI
streamlit run app.py
```
Click **Use the sample receipt** to try it without a real receipt.

### Deploy online (Streamlit Community Cloud, free)
1. Use a MongoDB **Atlas** cluster (the cloud can't reach a database on your laptop) and allow access from anywhere (`0.0.0.0/0`) under *Network Access*.
2. On [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, click **Create app**, choose this repository, branch `main`, file `app.py`, and Python 3.12 under *Advanced settings*.
3. Paste the secrets (they are never stored in the repository):
   ```toml
   GOOGLE_API_KEY = "your-gemini-key"
   MONGODB_URI = "mongodb+srv://user:password@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
   MONGODB_DB = "fairshare"
   APP_PASSWORD = "choose-a-demo-password"
   ```
   `APP_PASSWORD` shows a password screen first, so a public link can't use up your Gemini quota.

### Run the tests
```bash
pytest -q
```

## Project structure
```
├── app.py                     # Streamlit UI: receipt, chat, results, history
├── src/fairshare/
│   ├── models.py              # Pydantic models = the JSON shapes Gemini must return
│   ├── extract.py             # photo → Receipt (Gemini vision + structured output)
│   ├── interpreter.py         # chat message → ChatAction (EN / AR / Franco)
│   ├── splitter.py            # the fair-split engine (pure Python, exact)
│   ├── money.py               # piaster arithmetic + largest-remainder allocation
│   ├── session.py             # ties Gemini, the engine and MongoDB together
│   ├── db.py                  # MongoDB document model + aggregation pipelines
│   ├── summary.py             # WhatsApp message, breakdown and history text
│   └── config.py              # settings from .env
├── samples/                   # sample receipt (fictional café) + its expected JSON
├── scripts/make_sample_receipt.py
└── tests/                     # fake Gemini + mongomock: offline tests
```

## Limitations and ideas
- Very blurry or crumpled receipts can be misread. That's why the table is editable and the totals are cross-checked.
- Ideas: a split-the-difference mode for shared appetizers, settle-up suggestions that minimise the number of transfers, and deployment to Streamlit Community Cloud.

*The sample receipt is for a fictional café and was generated by `scripts/make_sample_receipt.py`.*
