#!/usr/bin/env python3
"""
Optional, GUARDED LLM polish layer.

The deterministic pipeline is the source of truth. This layer may only *rephrase* already-correct
Markdown for readability. It can never be trusted to add facts, so every call is verified:

    1. Send the text to an LLM with a strict "rephrase only, change no facts" instruction
       (prompt lives in prompts/polish.md - prompt-as-code, versioned with the repo).
    2. Verify the returned text still contains every required fact (change IDs, field names,
       settings paths, flags). If any is missing, REJECT the LLM output and return the original.
    3. If no API key / SDK is available, or the call errors, fall back to the original text.

So the worst case of enabling --polish is "no change", never a wrong or hallucinated release note.

`llm` is injectable so the guardrail can be unit-tested with a fake model (see tests).
"""
import os
import pathlib

PROMPT = (pathlib.Path(__file__).parent / "prompts" / "polish.md").read_text() \
    if (pathlib.Path(__file__).parent / "prompts" / "polish.md").exists() else \
    "Rephrase for clarity. Do not add, remove, or change any fact, number, name, or path.\n\n{text}"


def _default_llm(prompt: str) -> str:
    """Try a real provider via env key. Raises if none is configured (caller falls back)."""
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("no API key set (ANTHROPIC_API_KEY / OPENAI_API_KEY)")
    try:  # Anthropic first
        if os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic
            client = anthropic.Anthropic()
            msg = client.messages.create(
                model="claude-3-5-sonnet-latest", max_tokens=2000,
                messages=[{"role": "user", "content": prompt}])
            return msg.content[0].text
        import openai
        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content
    except Exception as e:  # import error, network error, etc.
        raise RuntimeError(f"LLM call failed: {e}")


REVIEW_PROMPT = (
    "You are reviewing a product changelog entry for spelling mistakes and unclear wording.\n"
    "List only real problems, briefly. If the text is fine, reply exactly: none.\n"
    "Do not rewrite the text; just point out issues.\n\n{text}")


def review_text(items, llm=None):
    """
    Optional AI review for free-text typos/clarity that deterministic checks can't catch
    (e.g., 'Aharepoint' instead of 'SharePoint'). It only *flags* issues, never changes text,
    so it is safe. `items` is a list of (id, text). Returns a list of suggestion strings.
    Falls back to [] if there is no API key or the call fails.
    """
    llm = llm or _default_llm
    findings = []
    for cid, text in items:
        try:
            out = llm(REVIEW_PROMPT.format(text=text))
        except Exception:
            return []                       # no key / offline: skip the whole review quietly
        if out and out.strip().lower() != "none":
            findings.append(f"{cid}: AI text review (suggestion): {out.strip()}")
    return findings


def verify_facts(polished: str, must_keep):
    """Return the list of required facts that are MISSING from the polished text."""
    return [fact for fact in must_keep if fact not in polished]


def polish_markdown(text: str, must_keep, llm=None):
    """
    Return (text, status). Status is one of: applied / rejected:... / skipped:...
    Falls back to the original text on any problem, so it is always safe to enable.
    """
    llm = llm or _default_llm
    try:
        candidate = llm(PROMPT.format(text=text))
    except Exception as e:
        return text, f"skipped ({e})"
    missing = verify_facts(candidate, must_keep)
    if missing:
        return text, f"rejected (LLM dropped required facts: {missing})"
    return candidate, "applied"
