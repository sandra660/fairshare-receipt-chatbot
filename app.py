"""FairShare - Streamlit app.

Run:  streamlit run app.py
"""
import hmac
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fairshare.config import get_chat_model, settings  # noqa: E402
from fairshare.db import OutingStore  # noqa: E402
from fairshare.extract import extract_receipt  # noqa: E402
from fairshare.models import Charge, Item, Receipt  # noqa: E402
from fairshare.money import fmt  # noqa: E402
from fairshare.session import BillSession  # noqa: E402
from fairshare.splitter import check_receipt, who_owes  # noqa: E402
from fairshare.summary import breakdown_rows, history_text, whatsapp_message  # noqa: E402

SAMPLE = Path(__file__).resolve().parent / "samples" / "sample_receipt.jpg"
st.set_page_config(page_title="FairShare", page_icon="🧾", layout="wide")


def password_ok() -> bool:
    """Optional access password (APP_PASSWORD), so a public link can't use up your Gemini quota."""
    expected = os.getenv("APP_PASSWORD")
    if not expected or st.session_state.get("authenticated"):
        return True
    st.title("🧾 FairShare")
    st.caption("Split a restaurant bill fairly by chatting, in English, عربي or Franco.")
    entered = st.text_input("Password", type="password", placeholder="Enter the demo password")
    if entered:
        if hmac.compare_digest(entered.encode(), expected.encode()):  # constant-time comparison
            st.session_state.authenticated = True
            st.rerun()
        st.error("Wrong password.")
    return False


if not password_ok():
    st.stop()


def safe_md(text: str) -> str:
    return text.replace("$", "\\$")  # stop Streamlit treating $...$ as maths


# ---------------------------------------------------------------- connections (cached)
@st.cache_resource
def load_llm():
    return get_chat_model()


@st.cache_resource
def load_store():
    return OutingStore.connect(settings.mongodb_uri, settings.mongodb_db)


try:
    llm = load_llm()
except RuntimeError as err:
    st.error(str(err))
    st.stop()
try:
    store = load_store()
except Exception as err:  # wrong URI, wrong password, or IP not allowed in Atlas
    st.error(f"Could not connect to MongoDB: {err}\n\nCheck MONGODB_URI in your .env file (see README).")
    st.stop()


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🧾 FairShare")
    st.caption("Split a restaurant bill fairly by chatting, in English, عربي or Franco.")
    me = st.text_input("Your name", value=st.session_state.get("me", "Me"))
    st.session_state.me = me.strip() or "Me"

    if st.button("➕ New bill", width="stretch"):
        st.session_state.pop("outing_id", None)
        st.rerun()

    st.subheader("Recent bills")
    for o in store.recent(10):
        total = (o.get("receipt") or {}).get("total")
        when = o.get("date") or o["created_at"].strftime("%Y-%m-%d")
        label = f"{o['restaurant']} · {when}"
        if total:
            label += f" · {total:,.0f} {o.get('currency', '')}"
        if st.button(label, key=f"o-{o['_id']}", width="stretch"):
            st.session_state.outing_id = str(o["_id"])
            st.rerun()

tab_split, tab_history = st.tabs(["Split a bill", "History & balances"])


# ---------------------------------------------------------------- tab 1: split a bill
def start_from_image(image_bytes: bytes, mime: str):
    with st.spinner("Reading the receipt with Gemini..."):
        receipt = extract_receipt(llm, image_bytes, mime)
    session = BillSession.start(llm, store, receipt, me=st.session_state.me)
    st.session_state.outing_id = session.outing_id
    st.rerun()


with tab_split:
    if "outing_id" not in st.session_state:
        st.markdown("### 1. Add the receipt")
        c1, c2 = st.columns([2, 1])
        with c1:
            photo = st.file_uploader("Upload a photo of the receipt", type=["jpg", "jpeg", "png", "webp"])
            if photo and st.button("Read receipt", type="primary"):
                start_from_image(photo.getvalue(), photo.type or "image/jpeg")
        with c2:
            st.image(str(SAMPLE), caption="No receipt at hand? Try this one.", width=220)
            if st.button("Use the sample receipt"):
                start_from_image(SAMPLE.read_bytes(), "image/jpeg")
        st.stop()

    session = BillSession(llm, store, st.session_state.outing_id, me=st.session_state.me)
    r = session.receipt
    cur = r.currency

    left, right = st.columns([1, 1], gap="large")

    # ---- the receipt, editable (Gemini can misread a number; the user stays in control)
    with left:
        st.markdown(f"### 🧾 {r.restaurant}" + (f" · {r.date}" if r.date else ""))
        items_df = pd.DataFrame([{"#": i, **it.model_dump()} for i, it in enumerate(r.items, 1)])
        edited_items = st.data_editor(items_df, hide_index=True, num_rows="dynamic", key="items",
                                      column_config={"#": st.column_config.NumberColumn(disabled=True),
                                                     "total_price": st.column_config.NumberColumn(
                                                         "line total", format="%.2f")})
        charges_df = pd.DataFrame([c.model_dump() for c in r.charges]) if r.charges else \
            pd.DataFrame(columns=["name", "kind", "amount", "split"])
        edited_charges = st.data_editor(charges_df, hide_index=True, num_rows="dynamic", key="charges",
                                        column_config={"kind": st.column_config.SelectboxColumn(
                                            options=["tax", "service", "tip", "delivery", "discount", "other"]),
                                            "split": st.column_config.SelectboxColumn(
                                                options=["proportional", "equal"])})
        if st.button("Save receipt changes"):
            new = Receipt(
                restaurant=r.restaurant, date=r.date, currency=cur, subtotal=r.subtotal, total=r.total,
                items=[Item(name=str(x["name"]), quantity=float(x["quantity"] or 1), total_price=float(x["total_price"]))
                       for x in edited_items.to_dict("records") if pd.notna(x.get("total_price"))],
                charges=[Charge(name=str(x["name"]), kind=x["kind"] or "other", amount=float(x["amount"]),
                                split=x["split"] or "proportional")
                         for x in edited_charges.to_dict("records") if pd.notna(x.get("amount"))])
            session.update_receipt(new)
            st.rerun()
        for w in check_receipt(r):
            st.warning(w)
        st.caption(f"Receipt total: {fmt(round((r.total or 0) * 100), cur)}" if r.total else "")

    # ---- the chat
    with right:
        st.markdown("### 💬 Who had what?")
        box = st.container(height=380)
        with box:
            if not session.messages:
                st.info("Tell me who had what and who paid, for example:\n\n"
                        "• *I had the burger, Sara and Omar shared the pizza, everyone had a cola. Sara paid.*\n\n"
                        "• *ana akalt el pasta w mona 5adet el salad, w kolena 2asamna el cake*\n\n"
                        "• *أنا أكلت البرجر وسارة شربت عصير المانجو*")
            for m in session.messages:
                with st.chat_message(m["role"]):
                    st.markdown(safe_md(m["content"]))
        msg = st.chat_input("Who had what?")
        if msg:
            with st.spinner("Thinking..."):
                try:
                    turn = session.send(msg)
                except Exception as err:
                    st.error(f"Gemini error: {err}")
                    st.stop()
            if turn.history:
                st.session_state.history_answer = turn.history
            st.rerun()
        if st.session_state.get("history_answer"):
            st.info(st.session_state.pop("history_answer"))

    # ---- the result (always computed by Python, never by the AI)
    res = session.result
    if res and res.people:
        st.divider()
        st.markdown("### 💰 Who pays what")
        for w in res.warnings:
            st.warning(w)
        st.dataframe(pd.DataFrame(breakdown_rows(res, cur)), hide_index=True, width="stretch")
        shared = sum(p.total_cents for p in res.people.values())
        st.caption(f"Sum of everyone's shares: {fmt(shared, cur)} · receipt total: "
                   f"{fmt(res.printed_total_cents, cur) if res.printed_total_cents is not None else 'not printed'}")

        c1, c2 = st.columns([1, 1], gap="large")
        with c1:
            st.markdown("**Send to the group** (copy with the icon in the corner)")
            st.code(whatsapp_message(r.restaurant, res, session.payer, cur), language=None, wrap_lines=True)
        with c2:
            owes = who_owes(res, session.payer)
            if owes:
                st.markdown(f"**Paid back to {session.payer}?**")
                doc = store.get(session.outing_id)
                # compare names ignoring capitals ("sara" in the database = "Sara" on screen)
                paid = {p["name"].casefold(): p["paid"] for p in doc.get("participants", [])}
                for name, cents in owes.items():
                    was_paid = paid.get(name.casefold(), False)
                    ticked = st.checkbox(f"{name}: {fmt(cents, cur)}", value=was_paid,
                                         key=f"paid-{session.outing_id}-{name.casefold()}")
                    if ticked != was_paid:
                        store.mark_paid(session.outing_id, name, ticked)
            else:
                st.caption("Tell me who paid the bill to track who owes whom.")


# ---------------------------------------------------------------- tab 2: history (MongoDB aggregations)
with tab_history:
    days = st.selectbox("Period", [7, 30, 90, 365, None], index=1,
                        format_func=lambda d: f"Last {d} days" if d else "All time")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("#### Spending per person")
        rows = store.spending_by_person(days)
        if rows:
            df = pd.DataFrame(rows)
            df["spent"] = df["spent_cents"] / 100
            st.bar_chart(df, x="name", y="spent", horizontal=True)
        st.text(history_text("spending_by_person", rows, days))
    with c2:
        st.markdown("#### Who still owes whom")
        st.text(history_text("balances", store.balances(days), days))
        st.markdown("#### Favourite places")
        st.text(history_text("top_restaurants", store.top_restaurants(days), days))
