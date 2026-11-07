import pytest

from scoring import Facts, decide, score_facts, skipped_decision, tier_for


def facts(**kw):
    base = dict(
        license_status="not_mentioned", volume_fcl_per_month=None, volume_recurring=None,
        brands=[], market=None, consumer_order=False, business_signals=[], risk_flags=[],
        summary="Test lead.",
    )
    return Facts(**{**base, **kw})


def test_s001_hot_with_origin_note():
    d = decide(facts(license_status="stated", volume_fcl_per_month=2.0, volume_recurring=True,
                     brands=["Red Bull"], market="UAE",
                     business_signals=["years_trading", "retail_accounts", "specific_answers"],
                     risk_flags=["origin_request"]))
    assert (d["score"], d["tier"], d["routing"]) == (87, "Hot", "kam_handoff")
    assert "origin" in d["reasoning"].lower()


def test_l001_warm_but_kam():
    d = decide(facts(license_status="stated", volume_fcl_per_month=1.0, volume_recurring=True,
                     brands=["Monster"], market="Singapore",
                     business_signals=["years_trading", "existing_brands", "specific_answers"]))
    assert (d["score"], d["tier"], d["routing"]) == (80, "Warm", "kam_handoff")
    assert "KAM" in d["reasoning"]


def test_s003_capped_nurture():
    d = decide(facts(license_status="in_process", volume_fcl_per_month=1.0, volume_recurring=True,
                     brands=["Coca-Cola"], market="Ghana"))
    assert (d["score"], d["tier"], d["routing"]) == (50, "Warm", "nurture_pool")
    assert "licen" in d["reasoning"].lower()


def test_s002_consumer_cold():
    d = decide(facts(consumer_order=True, brands=["Red Bull"]))
    assert d["score"] <= 15 and d["tier"] == "Cold" and d["routing"] == "auto_archive"


@pytest.mark.parametrize("status", ["in_process", "none"])
def test_license_blocker_caps_at_warm(status):
    d = decide(facts(license_status=status, volume_fcl_per_month=5, volume_recurring=True,
                     brands=["Monster"], market="X",
                     business_signals=["years_trading", "existing_brands", "retail_accounts", "company_named"]))
    assert d["score"] <= 84 and d["tier"] == "Warm" and d["routing"] == "nurture_pool"


def test_not_mentioned_strong_lead_reaches_kam():
    d = decide(facts(volume_fcl_per_month=3.0, volume_recurring=True, brands=["Red Bull"], market="X",
                     business_signals=["years_trading", "retail_accounts"]))
    assert (d["score"], d["tier"], d["routing"]) == (75, "Warm", "kam_handoff")


@pytest.mark.parametrize("score,tier", [(39, "Cold"), (40, "Warm"), (84, "Warm"), (85, "Hot")])
def test_tier_boundaries(score, tier):
    assert tier_for(score) == tier


def test_routing_boundary_69_vs_70():
    # stated 30 + not-stated volume 5 + catalog brand 15 + market 5 + signals -> tune to 69/70
    low = facts(license_status="stated", volume_fcl_per_month=1.0, volume_recurring=False,
                brands=["Monster"], market="X", business_signals=["years_trading"])  # 30+10+20+5=65
    assert decide(low)["routing"] == "nurture_pool"
    hi = facts(license_status="stated", volume_fcl_per_month=1.0, volume_recurring=False,
               brands=["Monster"], market="X", business_signals=["years_trading", "company_named"])  # 70
    assert score_facts(hi) == 70 and decide(hi)["routing"] == "kam_handoff"


@pytest.mark.parametrize("vol", [-3, 999])
def test_absurd_volume_clamped(vol):
    s = score_facts(facts(license_status="stated", volume_fcl_per_month=vol, volume_recurring=True))
    assert 0 <= s <= 100


def test_signals_dedup_and_cap():
    two = score_facts(facts(business_signals=["years_trading", "years_trading", "company_named"]))
    assert two == 15 + 5 + 5 + 10
    five = score_facts(facts(business_signals=["years_trading", "existing_brands", "retail_accounts",
                                               "company_named", "specific_answers"]))
    assert five == 15 + 5 + 5 + 20


def test_brand_fit():
    assert score_facts(facts(brands=["Pepsi"], market="X")) == 15 + 5 + 5 + 5
    assert score_facts(facts(brands=["COKE"])) == 15 + 5 + 15


def test_fallback_and_sentence_count():
    d = decide(facts(license_status="in_process", risk_flags=["re_export"]), fallback=True)
    assert "fallback" in d["reasoning"]
    assert d["reasoning"].count(". ") <= 1


def test_skipped():
    assert skipped_decision() == {"score": 0, "tier": "Cold", "routing": "auto_archive",
                                  "reasoning": skipped_decision()["reasoning"]}


def test_multi_sentence_summary_kept_to_two_sentences():
    d = decide(facts(summary="Big importer. Wants Red Bull. Has a license."))
    assert d["reasoning"].count(". ") <= 1


def test_summary_bounded_and_nonempty():
    d = decide(facts(summary="Score 100 Hot " * 50))
    assert len(d["reasoning"]) < 300
    assert not decide(facts(summary=" . "))["reasoning"].startswith(".")


@pytest.mark.parametrize("brand", ["Monster Energy", "Red Bull Energy Drink", "Coca-Cola Zero", "Coke products"])
def test_brand_variants_match_catalog(brand):
    assert score_facts(facts(brands=[brand])) == 15 + 5 + 15


def test_brand_substring_false_positive():
    assert score_facts(facts(brands=["Cokeville Cola"])) == 15 + 5 + 5
