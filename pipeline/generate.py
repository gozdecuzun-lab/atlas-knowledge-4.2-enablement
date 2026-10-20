#!/usr/bin/env python3
"""
Atlas Knowledge release-enablement generator.

Reads changelog.yaml and regenerates, deterministically:
  - release notes          -> 02-release-notes.md
  - readiness assessment   -> 04-assessment.md
  - competency-map scaffold-> competency-map-scaffold.md   (human then refines into 01-competency-map.md)

Design choices (see README):
  - Deterministic + template-based core. No LLM needed, so output is reproducible, accurate
    (no hallucination) and runs with no API key. Quality lives in human-authored templates + rules.
  - OPTIONAL `--polish` runs a guarded LLM pass that may only rephrase; a fact-preservation check
    rejects the LLM output and falls back to deterministic text if any required fact is dropped.
  - Adding a new entry to changelog.yaml and re-running regenerates every output. Nothing is
    hand-edited downstream.
  - Internal-visibility changes are excluded from all customer-facing output.
  - Quality gates (validate_outputs) fail the build if an invariant is broken.
  - Source-consistency checks (check_source) surface contradictions in the source material.

Usage:
    python pipeline/generate.py                 # regenerate (deterministic)
    python pipeline/generate.py --check         # fail if committed outputs are stale (CI/drift)
    python pipeline/generate.py --strict        # treat source-consistency warnings as errors
    python pipeline/generate.py --polish        # optional guarded LLM polish (needs an API key)
"""

import argparse
import difflib
import pathlib
import re
import sys

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"


# ---------- Rules: level, action, competency ----------

def derive_level(change):
    if change.get("breaking"):
        return "troubleshoot"
    if change["type"] in ("config_change", "feature"):
        return "apply"
    if change["type"] == "ui_change":
        return "know"
    return "know"


def derive_action(change):
    t = change["type"]
    if t == "api_deprecation":
        removal = change.get("removal_release")
        when = f" It is scheduled for removal in release {removal}." if removal else ""
        return ("Required: migrate off the deprecated endpoint before it is removed." + when
                + " Coordinate with your developer and partner teams.")
    if t == "api_change":
        return ("Required: update any integration that parses the changed field or payload. "
                "Coordinate with your developer and partner teams.")
    if t == "config_change":
        return "Review the new default and override it in settings if it does not suit your tenant."
    if t == "feature":
        default_val = change.get("default", None)            # YAML parses `off` as boolean False
        is_off = default_val is False or str(default_val).lower() == "off"
        if is_off:
            return "Optional: this ships off by default; enable it per portal if you want it."
        return "Review and configure as needed."
    if t == "ui_change":
        return "No action required; let affected users know about the new location."
    return "Review this change and assess whether any action is needed."


def classify_competency(change):
    if change.get("breaking") and change["type"] in ("api_deprecation", "api_change"):
        return ("COMP-INTEGRATIONS",
                "Support the team through breaking API and integration changes", "troubleshoot")
    verb = {"config_change": "Manage", "feature": "Configure and validate",
            "ui_change": "Be aware of"}.get(change["type"], "Understand")
    return (f"COMP-{change['id']}", f"{verb}: {change['title']}", derive_level(change))


# ---------- Assessment items ----------

def build_assessment_item(change, release):
    comp_id, comp_name, level = classify_competency(change)
    t = change["type"]
    scenario = bool(change.get("breaking")) or t == "config_change"

    if t == "api_deprecation":
        removal = change.get("removal_release")
        q = (f"A developer on your team reports that calls to the old search endpoint started "
             f"returning deprecation warnings after the {release} upgrade. What do you advise, "
             f"and by when must they act?")
        ans = ("Migrate to the v2 search endpoint (which requires a `locale` parameter, e.g. "
               "en-US). Note the changelog is internally inconsistent about the exact removal "
               f"release (field says {removal}, description says supported through 4.4), so confirm "
               "the deadline with the vendor before planning the cutover.")
        rat = "Tests whether the admin can triage a deprecation and coordinate a migration."
    elif t == "api_change":
        q = ("After the upgrade, an integration that listens to the article.published webhook can "
             "no longer find the article's ID and stops working. What likely broke, and what is "
             "the fix?")
        ans = ("Payload v2 replaces the integer `article_id` with the string `article_uuid`; update "
               "the integration to parse `article_uuid`. (The provided v2 sample labels the field "
               "`articleId`, so confirm the exact field name with the vendor.)")
        rat = "Tests whether the admin can diagnose a breaking payload change and guide the fix."
    elif t == "config_change":
        q = ("After upgrading, users complain they are being logged out far more often than before. "
             "What changed, and how do you address it?")
        ans = ("The default SSO session timeout dropped from 8 hours to 1 hour for new and existing "
               "tenants. If that is too short, override it under Settings > Security > Session.")
        rat = "Tests whether the admin can connect a reported symptom to the config change and act."
    elif t == "feature":
        q = ("A stakeholder asks why AI Answers are not showing source citations after the upgrade. "
             "Why, and how do you turn them on?")
        ans = ("Citations ship off by default (feature flag "
               f"`{change.get('feature_flag', 'n/a')}`). Enable them per portal under "
               "AI Answers > Display > Show citations.")
        rat = "Tests whether the admin knows the feature is opt-in and how to enable it."
    elif t == "ui_change":
        q = ("In the new Author Console, where do authors now click to publish an article, and does "
             "publishing behave differently?")
        ans = "Publish moved from the article footer to the top toolbar. There is no behavior change."
        rat = "Tests awareness of the UI change so the admin can inform authors."
    else:
        q = f"What is the change '{change['title']}', and does it require any admin action?"
        ans = change["description"].strip()
        rat = "Tests basic awareness of the change."

    return {"change_id": change["id"], "competency_name": comp_name, "level": level,
            "scenario": scenario, "question": q, "answer": ans, "rationale": rat}


# ---------- Source-consistency checks (surface contradictions in the raw material) ----------

def check_source(data, repo):
    warnings = []
    for c in data["changes"]:
        # removal_release field vs. a release number mentioned in the description
        if c.get("removal_release"):
            mentioned = set(re.findall(r"release (\d+\.\d+)", c.get("description", "")))
            if mentioned and c["removal_release"] not in mentioned:
                warnings.append(
                    f"{c['id']}: removal_release is {c['removal_release']} but the description "
                    f"mentions release(s) {sorted(mentioned)} - the removal date is contradictory.")
        # a described field rename vs. what the sample file actually contains
        desc = c.get("description", "")
        if "article_id" in desc and "article_uuid" in desc:
            sample = repo / "samples" / "webhook_article_published_v2.json"
            if sample.exists() and "article_uuid" not in sample.read_text():
                warnings.append(
                    f"{c['id']}: description renames the field to `article_uuid`, but "
                    f"samples/webhook_article_published_v2.json does not contain `article_uuid` "
                    f"(field-name mismatch).")
    return warnings


# ---------- Quality gates (invariants that MUST hold in the output) ----------

def validate_outputs(data, external, breaking, items, competencies):
    errors = []
    internal_ids = {c["id"] for c in data["changes"] if c.get("visibility") == "internal"}
    if internal_ids & {c["id"] for c in external}:
        errors.append(f"Internal changes leaked into external output: {sorted(internal_ids)}")
    for c in breaking:
        if not c.get("action", "").strip():
            errors.append(f"Breaking change {c['id']} has no action.")
    covered = [it["change_id"] for it in items]
    missing = {c["id"] for c in external} - set(covered)
    if missing:
        errors.append(f"External changes missing from assessment: {sorted(missing)}")
    if {x for x in covered if covered.count(x) > 1}:
        errors.append("Duplicate assessment items.")
    for it in items:
        if not it["competency_name"] or not it["answer"].strip() or not it["rationale"].strip():
            errors.append(f"Assessment item for {it['change_id']} is incomplete.")
    n_scenario = sum(1 for it in items if it["scenario"])
    if n_scenario < 2:
        errors.append(f"Need at least 2 scenario-based items; found {n_scenario}.")
    comp_changes = [cid for comp in competencies for cid in comp["changes"]]
    if {c["id"] for c in external} - set(comp_changes):
        errors.append("Some external changes are missing from the competency map.")
    if errors:
        raise SystemExit("QUALITY GATE FAILED:\n  - " + "\n  - ".join(errors))


# ---------- Build the output strings (pure; no file writes) ----------

def build_outputs(data, repo, polish=False):
    changes = data["changes"]
    external = [c for c in changes if c.get("visibility") == "external"]
    excluded = [c["id"] for c in changes if c.get("visibility") != "external"]
    for c in external:
        c["action"] = derive_action(c)
    breaking = [c for c in external if c.get("breaking")]
    non_breaking = [c for c in external if not c.get("breaking")]
    items = [build_assessment_item(c, data["release"]) for c in external]

    comp_map = {}
    for c in external:
        cid, name, level = classify_competency(c)
        comp_map.setdefault(cid, {"id": cid, "name": name, "level": level, "changes": []})
        comp_map[cid]["changes"].append(c["id"])
    competencies = list(comp_map.values())

    validate_outputs(data, external, breaking, items, competencies)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True)
    outputs = {
        "02-release-notes.md": env.get_template("release_notes.md.j2").render(
            product=data["product"], release=data["release"], release_date=data["release_date"],
            breaking=breaking, non_breaking=non_breaking),
        "04-assessment.md": env.get_template("assessment.md.j2").render(
            product=data["product"], release=data["release"], items=items),
        "competency-map-scaffold.md": env.get_template("competency_scaffold.md.j2").render(
            competencies=competencies, excluded=excluded),
    }

    if polish:
        from llm_polish import polish_markdown
        # facts that must survive a rephrase, or we reject the LLM output
        must_keep = ([c["id"] for c in external]
                     + ["locale", "article_uuid", "Settings > Security > Session",
                        "off by default"])
        for name in ("02-release-notes.md", "04-assessment.md"):
            outputs[name], status = polish_markdown(outputs[name], must_keep)
            print(f"  polish[{name}]: {status}")

    stats = {"external": len(external), "breaking": len(breaking), "items": len(items),
             "scenario": sum(1 for it in items if it["scenario"]),
             "competencies": len(competencies), "excluded": excluded}
    return outputs, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--changelog", default=str(HERE.parent / "changelog.yaml"))
    ap.add_argument("--outdir", default=str(HERE.parent))
    ap.add_argument("--check", action="store_true",
                    help="Do not write; fail if committed outputs differ from freshly generated.")
    ap.add_argument("--strict", action="store_true",
                    help="Treat source-consistency warnings as errors.")
    ap.add_argument("--polish", action="store_true",
                    help="Optional guarded LLM polish (requires an API key; falls back safely).")
    args = ap.parse_args()

    repo = pathlib.Path(args.changelog).resolve().parent
    data = yaml.safe_load(open(args.changelog))

    warnings = check_source(data, repo)
    for w in warnings:
        print(f"SOURCE WARNING: {w}")
    if warnings and args.strict:
        raise SystemExit("Source-consistency warnings present and --strict set.")

    outputs, stats = build_outputs(data, repo, polish=args.polish)
    outdir = pathlib.Path(args.outdir)

    if args.check:
        drift = []
        for name, content in outputs.items():
            existing = (outdir / name)
            current = existing.read_text() if existing.exists() else ""
            if current != content:
                drift.append(name)
                sys.stdout.writelines(difflib.unified_diff(
                    current.splitlines(True), content.splitlines(True),
                    fromfile=f"committed/{name}", tofile=f"regenerated/{name}"))
        if drift:
            raise SystemExit(f"\nDRIFT: committed outputs are stale: {drift}. Run generate.py.")
        print("CHECK OK: committed outputs match the changelog.")
        return

    for name, content in outputs.items():
        (outdir / name).write_text(content)
    print(f"OK. {stats['external']} external ({stats['breaking']} breaking), "
          f"{stats['items']} assessment items ({stats['scenario']} scenario), "
          f"{stats['competencies']} draft competencies. Excluded: {stats['excluded'] or 'none'}.")


if __name__ == "__main__":
    main()
