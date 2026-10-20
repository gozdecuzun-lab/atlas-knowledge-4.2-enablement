#!/usr/bin/env python3
"""
Atlas Knowledge release-enablement generator.

Reads changelog.yaml and regenerates, deterministically:
  - release notes          -> 02-release-notes.md
  - readiness assessment   -> 04-assessment.md
  - competency-map scaffold-> competency-map-scaffold.md   (human then refines into 01-competency-map.md)

Design choices (see README):
  - Deterministic + template-based. No LLM at runtime, so output is reproducible,
    accurate (no hallucination), and runnable with no API key. Quality lives in the
    human-authored templates + the rules below.
  - Adding a new entry to changelog.yaml and re-running regenerates every output.
    Nothing is hand-edited downstream.
  - Internal-visibility changes are excluded from all customer-facing output.
  - Quality gates (validate()) fail the build if an invariant is broken.

Usage:
    python pipeline/generate.py                 # uses ./changelog.yaml, writes to repo root
    python pipeline/generate.py --changelog X --outdir Y
"""

import argparse
import pathlib
import sys

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"

# ---- Rules: how a change maps to a level, an action, and a competency ----

def derive_level(change):
    """Expected proficiency level for the admin, driven by risk, not technical depth."""
    if change.get("breaking"):
        return "troubleshoot"          # breaking changes demand diagnosis + team support
    if change["type"] in ("config_change", "feature"):
        return "apply"                 # admin must perform a configuration action
    if change["type"] == "ui_change":
        return "know"                  # awareness is enough (no behavior change)
    return "know"


def derive_action(change):
    """One-line action text, by change type. Specifics come from the description."""
    t = change["type"]
    if t == "api_deprecation":
        removal = change.get("removal_release")
        when = f" It is scheduled for removal in release {removal}." if removal else ""
        return ("Required: migrate off the deprecated endpoint before it is removed."
                + when + " Coordinate with your developer and partner teams.")
    if t == "api_change":
        return ("Required: update any integration that parses the changed field or payload. "
                "Coordinate with your developer and partner teams.")
    if t == "config_change":
        return ("Review the new default and override it in settings if it does not suit "
                "your tenant.")
    if t == "feature":
        # NOTE: YAML parses the unquoted word `off` as the boolean False, so accept both.
        default_val = change.get("default", None)
        is_off = default_val is False or str(default_val).lower() == "off"
        if is_off:
            return "Optional: this ships off by default; enable it per portal if you want it."
        return "Review and configure as needed."
    if t == "ui_change":
        return "No action required; let affected users know about the new location."
    return "Review this change and assess whether any action is needed."


def classify_competency(change):
    """
    Map a change to a (draft) competency. Breaking API/integration changes are grouped
    into ONE competency (so C1 + C6 merge, matching the refined map). Everything else
    gets its own competency. Mechanical names; a human renames them in the final map.
    """
    if change.get("breaking") and change["type"] in ("api_deprecation", "api_change"):
        return ("COMP-INTEGRATIONS",
                "Support the team through breaking API and integration changes",
                "troubleshoot")
    verb = {
        "config_change": "Manage",
        "feature": "Configure and validate",
        "ui_change": "Be aware of",
    }.get(change["type"], "Understand")
    return (f"COMP-{change['id']}", f"{verb}: {change['title']}", derive_level(change))


# ---- Assessment: one item per external change, scenario-framed where it matters ----

def build_assessment_item(change):
    """Return a dict with a question, answer key, one-line rationale, competency, level."""
    comp_id, comp_name, level = classify_competency(change)
    t = change["type"]
    scenario = bool(change.get("breaking")) or t == "config_change"  # these read naturally as scenarios

    if t == "api_deprecation":
        removal = change.get("removal_release")
        q = (f"A developer on your team reports that calls to the old search endpoint started "
             f"returning deprecation warnings after the {change_release} upgrade. What do you "
             f"advise, and by when must they act?")
        ans = ("Migrate to the v2 search endpoint (which requires a `locale` parameter, e.g. "
               "en-US). Note the changelog is internally inconsistent about the exact removal "
               f"release (field says {removal}, description says supported through 4.4), so "
               "confirm the deadline with the vendor before planning the cutover.")
        rat = "Tests whether the admin can triage a deprecation and coordinate a migration."
    elif t == "api_change":
        q = ("After the upgrade, an integration that listens to the article.published webhook "
             "can no longer find the article's ID and stops working. What likely broke, and "
             "what is the fix?")
        ans = ("Payload v2 replaces the integer `article_id` with the string `article_uuid`; "
               "update the integration to parse `article_uuid`. (The provided v2 sample labels "
               "the field `articleId`, so confirm the exact field name with the vendor.)")
        rat = "Tests whether the admin can diagnose a breaking payload change and guide the fix."
    elif t == "config_change":
        q = ("After upgrading, users complain they are being logged out far more often than "
             "before. What changed, and how do you address it?")
        ans = ("The default SSO session timeout dropped from 8 hours to 1 hour for new and "
               "existing tenants. If that is too short, override it under "
               "Settings > Security > Session.")
        rat = "Tests whether the admin can connect a reported symptom to the config change and act."
    elif t == "feature":
        where = ""
        # pull the enable path out of the description if present
        q = ("A stakeholder asks why AI Answers are not showing source citations after the "
             "upgrade. Why, and how do you turn them on?")
        ans = ("Citations ship off by default (feature flag "
               f"`{change.get('feature_flag', 'n/a')}`). Enable them per portal under "
               "AI Answers > Display > Show citations.")
        rat = "Tests whether the admin knows the feature is opt-in and how to enable it."
    elif t == "ui_change":
        q = ("In the new Author Console, where do authors now click to publish an article, and "
             "does publishing behave differently?")
        ans = ("Publish moved from the article footer to the top toolbar. There is no behavior "
               "change.")
        rat = "Tests awareness of the UI change so the admin can inform authors."
    else:
        q = f"What is the change '{change['title']}', and does it require any admin action?"
        ans = change["description"].strip()
        rat = "Tests basic awareness of the change."

    return {
        "change_id": change["id"],
        "competency_name": comp_name,
        "level": level,
        "scenario": scenario,
        "question": q,
        "answer": ans,
        "rationale": rat,
    }


# ---- Quality gates: fail loudly if an invariant is broken ----

def validate(data, external, breaking, non_breaking, items, competencies, excluded):
    errors = []

    # 1. No internal-visibility change may leak into customer-facing output.
    internal_ids = {c["id"] for c in data["changes"] if c.get("visibility") == "internal"}
    leaked = internal_ids & ({c["id"] for c in external})
    if leaked:
        errors.append(f"Internal changes leaked into external output: {sorted(leaked)}")

    # 2. Every breaking change must carry a non-empty action.
    for c in breaking:
        if not c.get("action", "").strip():
            errors.append(f"Breaking change {c['id']} has no action.")

    # 3. Every external change must be represented exactly once in the assessment.
    covered = [it["change_id"] for it in items]
    missing = {c["id"] for c in external} - set(covered)
    if missing:
        errors.append(f"External changes missing from assessment: {sorted(missing)}")
    dupes = {x for x in covered if covered.count(x) > 1}
    if dupes:
        errors.append(f"Duplicate assessment items for: {sorted(dupes)}")

    # 4. Every assessment item must map to a competency and have an answer + rationale.
    for it in items:
        if not it["competency_name"] or not it["answer"].strip() or not it["rationale"].strip():
            errors.append(f"Assessment item for {it['change_id']} is incomplete.")

    # 5. At least two scenario-based items (per the brief).
    n_scenario = sum(1 for it in items if it["scenario"])
    if n_scenario < 2:
        errors.append(f"Need at least 2 scenario-based items; found {n_scenario}.")

    # 6. Every external change must appear in exactly one competency.
    comp_changes = [cid for comp in competencies for cid in comp["changes"]]
    missing_c = {c["id"] for c in external} - set(comp_changes)
    if missing_c:
        errors.append(f"External changes missing from competency map: {sorted(missing_c)}")

    if errors:
        raise SystemExit("QUALITY GATE FAILED:\n  - " + "\n  - ".join(errors))


change_release = None  # set at runtime so assessment questions can reference the release


def main():
    global change_release
    ap = argparse.ArgumentParser()
    ap.add_argument("--changelog", default=str(HERE.parent / "changelog.yaml"))
    ap.add_argument("--outdir", default=str(HERE.parent))
    args = ap.parse_args()

    data = yaml.safe_load(open(args.changelog))
    change_release = data["release"]
    outdir = pathlib.Path(args.outdir)

    changes = data["changes"]
    external = [c for c in changes if c.get("visibility") == "external"]
    excluded = [c["id"] for c in changes if c.get("visibility") != "external"]

    # attach derived action to each external change
    for c in external:
        c["action"] = derive_action(c)

    breaking = [c for c in external if c.get("breaking")]
    non_breaking = [c for c in external if not c.get("breaking")]

    # assessment items
    items = [build_assessment_item(c) for c in external]

    # competency scaffold (grouped)
    comp_map = {}
    for c in external:
        cid, name, level = classify_competency(c)
        comp_map.setdefault(cid, {"id": cid, "name": name, "level": level, "changes": []})
        comp_map[cid]["changes"].append(c["id"])
    competencies = list(comp_map.values())

    # quality gates BEFORE writing anything
    validate(data, external, breaking, non_breaking, items, competencies, excluded)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                      undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)

    (outdir / "02-release-notes.md").write_text(env.get_template("release_notes.md.j2").render(
        product=data["product"], release=data["release"], release_date=data["release_date"],
        breaking=breaking, non_breaking=non_breaking))

    (outdir / "04-assessment.md").write_text(env.get_template("assessment.md.j2").render(
        product=data["product"], release=data["release"], items=items))

    (outdir / "competency-map-scaffold.md").write_text(env.get_template("competency_scaffold.md.j2").render(
        competencies=competencies, excluded=excluded))

    print(f"OK. {len(external)} external changes "
          f"({len(breaking)} breaking), {len(items)} assessment items "
          f"({sum(1 for it in items if it['scenario'])} scenario), "
          f"{len(competencies)} draft competencies. Excluded: {excluded or 'none'}.")


if __name__ == "__main__":
    main()
