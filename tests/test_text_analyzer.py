import time

import pytest


def cats(result):
    return {k for k, v in result["categories"].items() if v}


def test_payment_before_viewing(text_analyzer):
    r = text_analyzer.analyze("Send token amount before viewing.")
    assert {"advance_payment", "payment_before_viewing"} <= cats(r)
    assert r["advance_payment_detected"] is True
    assert any("before viewing" in p for p in r["risk_phrases"])


def test_owner_abroad_and_no_viewing(text_analyzer):
    r = text_analyzer.analyze("I am currently in Dubai, so no physical viewing. Keys will be sent after payment.")
    assert {"owner_away", "no_viewing", "payment_before_viewing"} <= cats(r)
    assert r["owner_abroad_detected"] and r["no_viewing_detected"]


def test_urgency_pressure(text_analyzer):
    r = text_analyzer.analyze("Pay immediately or the property will be given to someone else.")
    assert "urgency" in cats(r)
    assert r["urgency_score"] >= 0.8


def test_unusual_payment_and_otp(text_analyzer):
    r = text_analyzer.analyze("Payment by gift card only. Share the OTP to confirm your booking.")
    assert {"unusual_payment", "sensitive_info"} <= cats(r)


@pytest.mark.parametrize("text", [
    "No advance required. Pay after the site visit.",
    "It is immediately available for all for rs. 85000 monthly.",
    "10 to 15 mint walkable distance, within 15 minutes of the station.",
    "Brokers please do not call. Urgent requirement of tenant, family preferred.",
    "Token amount to be paid after site visit and finalisation.",
    "The owner is an NRI, the agent will show the flat.",
    "2 bhk flat available for rent near the station with covered parking.",
])
def test_routine_listing_language_is_not_flagged(text_analyzer, text):
    r = text_analyzer.analyze(text)
    assert cats(r) - {"urgency"} == set(), r["matches"]
    assert r["urgency_score"] <= 0.3


def test_case_insensitive(text_analyzer):
    assert "payment_before_viewing" in cats(text_analyzer.analyze("SEND TOKEN AMOUNT BEFORE VIEWING"))


def test_misspelled_paraphrase_caught_by_tfidf_layer(text_analyzer):
    r = text_analyzer.analyze("snd advnce paymnt befor visting the flat")
    assert cats(r) == set()                       # rules miss it...
    assert r["semantic_match"] is not None        # ...TF-IDF similarity catches it
    assert r["semantic_risk_similarity"] >= 0.5


def test_semantic_layer_ignores_lookalike_words(text_analyzer):
    r = text_analyzer.analyze("Fastest connectivity to both western and central mumbai via highway.")
    assert r["semantic_match"] is None


@pytest.mark.parametrize("desc", [None, "", "   "])
def test_missing_description(text_analyzer, desc):
    r = text_analyzer.analyze(desc)
    assert r["available"] is False
    assert r["risk_phrases"] == []
    assert r["urgency_score"] == 0


def test_extremely_long_description_is_bounded(text_analyzer):
    text = "Nice flat with garden. " * 20000 + "Send token amount before viewing."
    start = time.perf_counter()
    r = text_analyzer.analyze(text)
    assert time.perf_counter() - start < 2.0
    assert r["word_count"] <= 1000          # truncated to MAX_TEXT_CHARS


def test_evidence_is_deduplicated(text_analyzer):
    r = text_analyzer.analyze("Send token amount before viewing. Send token amount before viewing.")
    phrases = [m["phrase"].lower() for m in r["matches"]]
    assert len(phrases) == len(set(phrases))
