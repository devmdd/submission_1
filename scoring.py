"""Business rules: Facts -> score, tier, routing, reasoning. Pure code, no I/O.

Every number here is defended in DESIGN.md ("Scoring").
"""
import re
from typing import Literal

from pydantic import BaseModel, Field

Signal = Literal["years_trading", "existing_brands", "retail_accounts", "company_named", "specific_answers"]
Flag = Literal["origin_request", "re_export", "too_good_to_be_true"]


class Facts(BaseModel):
    """What the extractor read from the lead's own turns. Also used as Gemini's response schema."""
    license_status: Literal["stated", "in_process", "none", "not_mentioned"]
    volume_fcl_per_month: float | None = None
    volume_recurring: bool | None = None
    brands: list[str] = Field(default_factory=list)
    market: str | None = None
    consumer_order: bool = False
    business_signals: list[Signal] = Field(default_factory=list)
    risk_flags: list[Flag] = Field(default_factory=list)
    summary: str = ""


# ponytail: brief says "Coca-Cola, Monster, Red Bull, etc." — extend when the real catalog is known.
CATALOG = {
    "coca-cola": "Coca-Cola", "coca cola": "Coca-Cola", "coke": "Coca-Cola", "sprite": "Coca-Cola", "fanta": "Coca-Cola",
    "monster": "Monster",
    "red bull": "Red Bull", "redbull": "Red Bull",
}

LICENSE_POINTS = {"stated": 30, "not_mentioned": 15, "in_process": 15, "none": 0}
BLOCKED = {"in_process", "none"}
HOT, WARM, KAM_BAND = 85, 40, 70
FLAG_TEXT = {
    "origin_request": "requests specific-origin stock, confirm sourcing",
    "re_export": "goods may be re-exported, check distribution rights",
    "too_good_to_be_true": "claims look implausible, verify the business",
}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def carries(brand: str) -> bool:
    # whole-word alias match: "Monster Energy" and "Coca-Cola Zero" count, "Cokeville" doesn't
    b = brand.lower()
    return any(re.search(rf"\b{re.escape(alias)}\b", b) for alias in CATALOG)


def _volume_points(vol: float | None, recurring: bool | None) -> int:
    if vol is None:
        return 5
    if vol < 1:
        return 0
    if recurring is False:
        return 10
    return 30 if vol >= 3 else 22 if vol >= 2 else 15


def score_facts(f: Facts) -> int:
    fit = (15 if any(carries(b) for b in f.brands) else 5) + (5 if f.market else 0)
    signals = 5 * min(len(set(f.business_signals)), 4)
    score = LICENSE_POINTS[f.license_status] + _volume_points(f.volume_fcl_per_month, f.volume_recurring) + fit + signals
    if f.license_status in BLOCKED:
        score = min(score, HOT - 1)
    if f.consumer_order:
        score = min(score, 15)
    return max(0, min(100, score))


def tier_for(score: int) -> str:
    return "Hot" if score >= HOT else "Warm" if score >= WARM else "Cold"


def decide(f: Facts, fallback: bool = False) -> dict:
    score = score_facts(f)
    tier = tier_for(score)
    blocked = f.license_status in BLOCKED

    if tier == "Hot":
        routing, why = "kam_handoff", "strong volume, fit and business signals: ready for a KAM call"
    elif tier == "Warm" and score >= KAM_BAND and not blocked:
        routing, why = "kam_handoff", "Warm but no blocker, so worth a KAM follow-up"
    elif tier == "Warm":
        routing = "nurture_pool"
        why = ("capped at Warm: license " + ("in process, re-score once licensed" if f.license_status == "in_process" else "missing")
               if blocked else "promising but not yet qualified, nurture")
    else:
        routing = "auto_archive"
        why = ("consumer purchase, not a trade buyer" if f.consumer_order
               else "no usable license yet and too little else to qualify" if blocked
               else "no import, volume or fit signals")

    parts = [why] + [FLAG_TEXT[x] for x in dict.fromkeys(f.risk_flags)]
    tail = " (scored by fallback rules)" if fallback else ""
    # ponytail: LLM summary is untrusted text — bound it so injected content can't dominate reasoning
    summary = f.summary.strip().rstrip(".").replace(". ", "; ")[:150].strip(" .;") or "Lead"
    return {"score": score, "tier": tier, "routing": routing,
            "reasoning": f"{summary}. {_cap('; '.join(parts))}{tail}."}


def skipped_decision() -> dict:
    return {"score": 0, "tier": "Cold", "routing": "auto_archive",
            "reasoning": "No messages from the lead to assess. Archived without scoring."}
