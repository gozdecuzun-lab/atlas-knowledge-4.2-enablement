"""
Tests for the guarded LLM polish layer, using fake models (no API key needed).

They prove the guardrail: a well-behaved model's text is accepted, but a model that drops a
required fact, or errors, is rejected and the original (correct) text is returned unchanged.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "pipeline"))
from llm_polish import polish_markdown, verify_facts, review_text  # noqa: E402

ORIGINAL = ("Enable citations per portal under AI Answers > Display > Show citations. "
            "It ships off by default. See change C4.")
MUST_KEEP = ["C4", "off by default", "AI Answers > Display > Show citations"]


def test_good_model_is_accepted():
    # a faithful rephrase that keeps every required fact
    good = lambda p: ("Turn on citations for each portal via AI Answers > Display > Show citations. "
                      "The feature is off by default. Refers to change C4.")
    out, status = polish_markdown(ORIGINAL, MUST_KEEP, llm=good)
    assert status == "applied"
    assert verify_facts(out, MUST_KEEP) == []


def test_model_that_drops_a_fact_is_rejected():
    # drops "off by default" -> must be rejected, original returned
    bad = lambda p: "Turn on citations under AI Answers > Display > Show citations. See C4."
    out, status = polish_markdown(ORIGINAL, MUST_KEEP, llm=bad)
    assert status.startswith("rejected")
    assert out == ORIGINAL                      # fell back to the correct text


def test_model_that_hallucinates_still_must_keep_facts():
    # adds a wrong fact AND drops one -> rejected
    bad = lambda p: "Citations are on by default for change C4."
    out, status = polish_markdown(ORIGINAL, MUST_KEEP, llm=bad)
    assert status.startswith("rejected")
    assert out == ORIGINAL


def test_model_error_falls_back_safely():
    def boom(p):
        raise RuntimeError("network down")
    out, status = polish_markdown(ORIGINAL, MUST_KEEP, llm=boom)
    assert status.startswith("skipped")
    assert out == ORIGINAL


def test_review_flags_typos_and_skips_clean_text():
    # fake model: flags a typo if it sees 'Aharepoint', else says 'none'
    def fake(prompt):
        return "Typo: 'Aharepoint' should be 'SharePoint'." if "Aharepoint" in prompt else "none"
    items = [("C7", "Aharepoint connector v2"), ("C2", "SSO session timeout reduced")]
    findings = review_text(items, llm=fake)
    assert len(findings) == 1
    assert "C7" in findings[0] and "SharePoint" in findings[0]


def test_review_skips_without_api_key():
    def boom(prompt):
        raise RuntimeError("no API key")
    assert review_text([("C1", "some text")], llm=boom) == []


if __name__ == "__main__":
    fails = 0
    for fn in (test_good_model_is_accepted, test_model_that_drops_a_fact_is_rejected,
               test_model_that_hallucinates_still_must_keep_facts, test_model_error_falls_back_safely,
               test_review_flags_typos_and_skips_clean_text, test_review_skips_without_api_key):
        try:
            fn(); print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            fails += 1; print(f"FAIL  {fn.__name__}: {e}")
    sys.exit(1 if fails else 0)
