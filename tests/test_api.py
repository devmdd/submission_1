import json

import pytest

import extract
from api import score as api
from scoring import Facts

GOOD = {"lead_id": "L1", "channel": "email", "conversation": [{"role": "lead", "text": "hi"}]}
FACTS = Facts(license_status="stated", volume_fcl_per_month=3, volume_recurring=True, brands=["Monster"],
              market="X", business_signals=["years_trading", "retail_accounts", "company_named"], summary="S")


@pytest.fixture(autouse=True)
def fake_extract(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "extract", lambda conv: (calls.append(conv), (FACTS, "llm"))[1])
    return calls


def call(body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return api.handle(raw)


def test_bad_json():
    assert call(b"{nope")[:2] == (400, {"error": "invalid_json"})


@pytest.mark.parametrize("body", [[], "x", 5])
def test_not_an_object(body):
    status, out, _ = call(body)
    assert status == 400 and out["error"] == "invalid_input"


@pytest.mark.parametrize("lead_id", [None, "", 123])
def test_bad_lead_id(lead_id):
    body = {**GOOD, "lead_id": lead_id}
    assert call(body)[:2] == (400, {"error": "invalid_input", "detail": "lead_id"})


@pytest.mark.parametrize("conv", [None, [], "hi", ["hi"], [None], [{"role": "lead"}], [{"role": "lead", "text": 5}]])
def test_bad_conversation(conv):
    assert call({**GOOD, "conversation": conv})[:2] == (400, {"error": "invalid_input", "detail": "conversation"})


def test_too_many_turns():
    status, out, _ = call({**GOOD, "conversation": [{"role": "lead", "text": "x"}] * 101})
    assert (status, out) == (413, {"error": "payload_too_large"})


def test_lenient_on_extras():
    body = {"lead_id": "L1", "extra": 1, "conversation": [{"role": "bot", "text": "x"}, {"role": "lead", "text": "y"}]}
    assert call(body)[0] == 200


def test_only_agent_turns_skips_llm(fake_extract):
    status, out, headers = call({**GOOD, "conversation": [{"role": "agent", "text": "hello?"}]})
    assert status == 200 and out["tier"] == "Cold" and headers["X-Scoring-Mode"] == "skipped"
    assert fake_extract == []


def test_valid_contract():
    status, out, headers = call(GOOD)
    assert status == 200 and set(out) == {"lead_id", "score", "tier", "routing", "reasoning"}
    assert out["lead_id"] == "L1" and out["tier"] == "Hot" and headers["X-Scoring-Mode"] == "llm"


def test_internal_error_hides_trace(monkeypatch):
    monkeypatch.setattr(api, "decide", lambda *a, **k: 1 / 0)
    status, out, _ = call(GOOD)
    assert (status, out) == (500, {"error": "internal_error"})


def test_deeply_nested_json_is_400_not_crash():
    status, out, _ = call(b"[" * 60000)
    assert status == 400
