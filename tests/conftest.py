"""Test helpers: an in-memory MongoDB (mongomock) and a scripted fake Gemini, so tests run offline."""
from pathlib import Path
import json
import re
import sys

import mongomock
import pytest
from langchain_core.runnables import RunnableLambda

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fairshare.db import OutingStore  # noqa: E402
from fairshare.models import Receipt  # noqa: E402

SAMPLE_JSON = ROOT / "samples" / "sample_receipt.json"


class FakeGemini:
    """Mimics `llm.with_structured_output(Model).invoke(messages)`.

    `rules` = list of (regex on the last message, object to return). Every prompt is kept in `.calls`.
    """

    def __init__(self, rules):
        self.rules, self.calls = rules, []

    def with_structured_output(self, schema):
        def respond(messages):
            last = messages[-1].content
            text = last if isinstance(last, str) else json.dumps(last)
            self.calls.append(text)
            text = text.split("New message from")[-1]  # match on the new message, not the chat history
            for pattern, obj in self.rules:
                if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                    return obj
            raise AssertionError(f"No fake reply for: {text[-200:]}")
        return RunnableLambda(respond)


@pytest.fixture
def receipt() -> Receipt:
    return Receipt.model_validate(json.loads(SAMPLE_JSON.read_text()))


@pytest.fixture
def store() -> OutingStore:
    return OutingStore(mongomock.MongoClient()["fairshare_test"])
