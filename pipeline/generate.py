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


# ---------- Type registry: the ONE place to teach the pipeline a new change type ----------
# To support a new change type, add one entry to TYPE_REGISTRY (below) with:
#   default_level : level when the change is NOT breaking (breaking is always "troubleshoot")
#   integration   : True if breaking changes of this type join the shared "integrations" competency
#   verb          : used to name this type's own competency (when it is not grouped)
#   action        : function(change) -> the "what to do" line for the release notes
#   assessment    : function(change, release) -> (question, answer_key, rationale)
# A type that is missing from the registry fails fast with a message pointing right back here.

def _removal_contradiction(change):
    """True if removal_release is set but the description names a different release."""
    removal = change.get("removal_release")
    if not removal:
        return False
    mentioned = set(re.findall(r"release (\d+\.\d+)", change.get("description", "")))
    return bool(mentioned) and removal not in mentioned


# --- action builders (one per type) ---

def _action_api_deprecation(change):
    removal = change.get("removal_release")
    if _removal_contradiction(change):
        # source self-contradicts the date: don't publish a specific (maybe wrong) release.
        core = ("Required: migrate off the deprecated endpoint. It will be removed in a future "
                "release; confirm the exact timing in the migration guide before you migrate.")
    elif removal:
        core = ("Required: migrate off the deprecated endpoint before it is removed in "
                f"release {removal}.")
    else:
        core = "Required: migrate off the deprecated endpoint before it is removed."
    return core + " Coordinate with your developer and partner teams."


def _action_api_change(change):
    return ("Required: update any integration that parses the changed field or payload. "
            "Coordinate with your developer and partner teams.")


def _action_config_change(change):
    return "Review the new default and override it in settings if it does not suit your tenant."


def _action_feature(change):
    default_val = change.get("default", None)            # YAML parses `off` as boolean False
    is_off = default_val is False or str(default_val).lower() == "off"
    if is_off:
        return "Optional: this ships off by default; enable it per portal if you want it."
    return "Review and configure as needed."


def _action_ui_change(change):
    return "No action required; let affected users know about the new location."


def _action_connector_change(change):
    if change.get("breaking"):
        return ("Required: update or reconfigure the connector and migrate affected integrations "
                "before the change takes effect; coordinate with your integration team.")
    return "Review the connector change and update its configuration if needed."


# --- assessment builders (one per type): each returns (question, answer_key, rationale) ---

def _assess_api_deprecation(change, release):
    removal = change.get("removal_release")
    q = (f"A developer on your team reports that calls to the old search endpoint started returning "
         f"deprecation warnings after the {release} upgrade. What do you advise, and by when must "
         f"they act?")
    ans = ("Migrate to the v2 search endpoint (which requires a `locale` parameter, e.g. en-US). "
           "Note the changelog is internally inconsistent about the exact removal release (field "
           f"says {removal}, description says supported through 4.4), so confirm the deadline with "
           "the vendor before planning the cutover.")
    return q, ans, "Tests whether the admin can triage a deprecation and coordinate a migration."


def _assess_api_change(change, release):
    q = ("After the upgrade, an integration that listens to the article.published webhook can no "
         "longer find the article's ID and stops working. What likely broke, and what is the fix?")
    ans = ("Payload v2 replaces the integer `article_id` with the string `article_uuid`; update the "
           "integration to parse `article_uuid`. (The provided v2 sample labels the field "
           "`articleId`, so confirm the exact field name with the vendor.)")
    return q, ans, "Tests whether the admin can diagnose a breaking payload change and guide the fix."


def _assess_config_change(change, release):
    q = ("After upgrading, users complain they are being logged out far more often than before. "
         "What changed, and how do you address it?")
    ans = ("The default SSO session timeout dropped from 8 hours to 1 hour for new and existing "
           "tenants. If that is too short, override it under Settings > Security > Session.")
    return q, ans, "Tests whether the admin can connect a reported symptom to the config change and act."


def _assess_feature(change, release):
    q = ("A stakeholder asks why AI Answers are not showing source citations after the upgrade. "
         "Why, and how do you turn them on?")
    ans = (f"Citations ship off by default (feature flag `{change.get('feature_flag', 'n/a')}`). "
           "Enable them per portal under AI Answers > Display > Show citations.")
    return q, ans, "Tests whether the admin knows the feature is opt-in and how to enable it."


def _assess_ui_change(change, release):
    q = ("In the new Author Console, where do authors now click to publish an article, and does "
         "publishing behave differently?")
    ans = "Publish moved from the article footer to the top toolbar. There is no behavior change."
    return q, ans, "Tests awareness of the UI change so the admin can inform authors."


def _assess_connector_change(change, release):
    q = ("This release includes a connector change your team may rely on. What should you check, "
         "and who should you coordinate with?")
    ans = (change["description"].strip() + " Review the connector's configuration, and if it is a "
           "breaking change, plan the migration with your integration/developer team.")
    return q, ans, "Tests whether the admin can handle a connector change and coordinate the integration team."


TYPE_REGISTRY = {
    "api_deprecation":  {"default_level": "troubleshoot", "integration": True,  "verb": "Understand",
                         "label": "API deprecation", "action": _action_api_deprecation, "assessment": _assess_api_deprecation},
    "api_change":       {"default_level": "troubleshoot", "integration": True,  "verb": "Understand",
                         "label": "API change", "action": _action_api_change,      "assessment": _assess_api_change},
    "connector_change": {"default_level": "apply",        "integration": True,  "verb": "Configure",
                         "label": "Connector change", "action": _action_connector_change, "assessment": _assess_connector_change},
    "config_change":    {"default_level": "apply",        "integration": False, "verb": "Manage",
                         "label": "Config change", "action": _action_config_change,   "assessment": _assess_config_change},
    "feature":          {"default_level": "apply",        "integration": False, "verb": "Configure and validate",
                         "label": "New feature", "action": _action_feature,         "assessment": _assess_feature},
    "ui_change":        {"default_level": "know",         "integration": False, "verb": "Be aware of",
                         "label": "UI change", "action": _action_ui_change,       "assessment": _assess_ui_change},
}

# Types whose questions read naturally as a scenario even when not breaking.
SCENARIO_TYPES = {"config_change"}


def _spec(change):
    """Look up a change type's handling. Fails fast (with a helpful message) if it's unknown."""
    spec = TYPE_REGISTRY.get(change.get("type"))
    if spec is None:
        raise SystemExit(
            f"TYPE ERROR: change type '{change.get('type')}' is not supported. "
            f"Add it to TYPE_REGISTRY in pipeline/generate.py with its level, action, "
            f"assessment, and competency settings.")
    return spec


# ---------- Rules (now just look-ups into the registry) ----------

def derive_level(change):
    if change.get("breaking"):
        return "troubleshoot"
    return _spec(change)["default_level"]


def derive_action(change):
    return _spec(change)["action"](change)


def derive_label(change):
    """Human-readable change-type label for customer-facing output (e.g. 'API deprecation')."""
    return _spec(change)["label"]


def classify_competency(change):
    spec = _spec(change)
    if change.get("breaking") and spec["integration"]:
        return ("COMP-INTEGRATIONS",
                "Support the team through breaking API and integration changes", "troubleshoot")
    return (f"COMP-{change['id']}", f"{spec['verb']}: {change['title']}", derive_level(change))


def build_assessment_item(change, release):
    comp_id, comp_name, level = classify_competency(change)
    question, answer, rationale = _spec(change)["assessment"](change, release)
    scenario = bool(change.get("breaking")) or change["type"] in SCENARIO_TYPES
    return {"change_id": change["id"], "competency_name": comp_name, "level": level,
            "scenario": scenario, "question": question, "answer": answer, "rationale": rationale}


# ---------- Source-consistency checks (surface contradictions in the raw material) ----------

def check_source(data, repo):
    warnings = []
    for c in data["changes"]:
        # removal_release field vs. a release number mentioned in the description
        if _removal_contradiction(c):
            mentioned = sorted(set(re.findall(r"release (\d+\.\d+)", c.get("description", ""))))
            warnings.append(
                f"{c['id']}: removal_release is {c['removal_release']} but the description "
                f"mentions release(s) {mentioned} - the removal date is contradictory.")
        # a described field rename vs. what the sample file actually contains
        desc = c.get("description", "")
        if "article_id" in desc and "article_uuid" in desc:
            sample = repo / "samples" / "webhook_article_published_v2.json"
            if sample.exists() and "article_uuid" not in sample.read_text():
                warnings.append(
                    f"{c['id']}: description renames the field to `article_uuid`, but "
                    f"samples/webhook_article_published_v2.json does not contain `article_uuid` "
                    f"(field-name mismatch).")
    warnings += check_cross_field(data)
    warnings += check_logic(data)
    return warnings


def _version_tuple(s):
    return tuple(int(x) for x in str(s).split("."))


def check_logic(data):
    """
    Logical / common-sense checks that aren't about structure but about whether the content
    makes sense. Warnings, not errors.
    """
    w = []
    changes = data.get("changes", [])
    release = data.get("release")

    if not any(c.get("visibility") == "external" for c in changes):
        w.append("no external changes - the customer release notes and assessment would be empty.")

    titles = {}
    for c in changes:
        if c.get("title"):
            titles.setdefault(c["title"], []).append(c.get("id"))
    for title, ids in titles.items():
        if len(ids) > 1:
            w.append(f"duplicate title '{title}' used by {ids} - likely a copy-paste mistake.")

    for c in changes:
        cid = c.get("id", "?")
        rr = c.get("removal_release")
        if rr and release:
            try:
                if _version_tuple(rr) <= _version_tuple(release):
                    w.append(f"{cid}: removal_release {rr} is not after the current release "
                             f"{release} - it should already be gone.")
            except ValueError:
                pass
        if c.get("breaking") and c.get("visibility") == "external":
            if not (set(c.get("audience", [])) & {"developer", "partner", "admin"}):
                w.append(f"{cid}: breaking change, but no one in the audience "
                         f"(developer/partner/admin) would act on it.")
        if len((c.get("description") or "").strip()) < 15:
            w.append(f"{cid}: description is missing or too short to be useful.")
    return w


REQUIRED_FIELDS = {"id", "title", "type", "breaking", "audience", "visibility", "description"}
# Valid types = everything the registry can handle, plus "internal" (excluded from customer output).
ALLOWED_TYPES = set(TYPE_REGISTRY) | {"internal"}
ALLOWED_VISIBILITY = {"external", "internal"}


def check_schema(data):
    """
    Structural validation of the changelog. Returns a list of ERRORS (fatal): missing required
    fields, unknown enum values, wrong types, or duplicate ids. Run before anything else so a
    malformed changelog fails fast and loudly instead of producing silently-wrong output.
    """
    errors = []
    if not data.get("changes"):
        return ["changelog has no 'changes'."]
    seen = set()
    for i, c in enumerate(data["changes"]):
        cid = c.get("id", f"<index {i}>")
        missing = REQUIRED_FIELDS - set(c)
        if missing:
            errors.append(f"{cid}: missing required field(s) {sorted(missing)}.")
        if "id" in c:
            if c["id"] in seen:
                errors.append(f"duplicate id: {c['id']}.")
            seen.add(c["id"])
        if c.get("type") not in ALLOWED_TYPES:
            errors.append(f"{cid}: unknown type {c.get('type')!r}. To support it, add an entry to "
                          f"TYPE_REGISTRY in pipeline/generate.py. Currently allowed: "
                          f"{sorted(ALLOWED_TYPES)}.")
        if c.get("visibility") not in ALLOWED_VISIBILITY:
            errors.append(f"{cid}: unknown visibility {c.get('visibility')!r} "
                          f"(allowed: {sorted(ALLOWED_VISIBILITY)}).")
        if "breaking" in c and not isinstance(c["breaking"], bool):
            errors.append(f"{cid}: 'breaking' must be true/false, got {c['breaking']!r}.")
    return errors


CUSTOMER_ROLES = {"admin", "author", "developer", "partner", "prospect"}


def check_cross_field(data):
    """
    Cross-field sanity checks. These are WARNINGS, not errors: they flag unusual combinations
    that are *probably* mistakes, but a legitimate edge case could trip them, so they must never
    block a valid changelog. The reviewer confirms; a false positive is just an ignorable line.
    """
    w = []
    for c in data["changes"]:
        cid = c.get("id", "?")
        vis = c.get("visibility")
        audience = set(c.get("audience", []))
        # internal item aimed at customers, or external item aimed only at Atlas engineering
        if vis == "internal" and (audience & CUSTOMER_ROLES):
            w.append(f"{cid}: visibility is internal but audience includes customer roles "
                     f"{sorted(audience & CUSTOMER_ROLES)} - confirm it should not be customer-facing.")
        if vis == "external" and not audience:
            w.append(f"{cid}: visibility is external but audience is empty - specify who the "
                     f"change is for.")
        if vis == "external" and audience and not (audience & CUSTOMER_ROLES):
            w.append(f"{cid}: visibility is external but audience is only {sorted(audience)} "
                     f"- confirm it is really customer-facing.")
        # a deprecation with no stated removal
        if c.get("type") == "api_deprecation" and not c.get("removal_release"):
            w.append(f"{cid}: api_deprecation without a removal_release - customers won't know the deadline.")
        # a feature that is off but has no flag to turn it on
        default_off = c.get("default") is False or str(c.get("default")).lower() == "off"
        if c.get("type") == "feature" and default_off and not c.get("feature_flag"):
            w.append(f"{cid}: feature defaults off but has no feature_flag - how is it enabled?")
        # a 'cosmetic' or internal change marked breaking
        if c.get("breaking") and c.get("type") in ("ui_change", "internal"):
            w.append(f"{cid}: type is {c['type']} but marked breaking - unusual; confirm.")
    return w


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
        c["label"] = derive_label(c)
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
        # Facts that must survive a rephrase, or we reject the LLM output.
        # Release notes no longer print change ids, so they are anchored on titles;
        # the assessment still prints ids, so those stay in its must-keep list.
        terms = ["locale", "article_uuid", "Settings > Security > Session", "off by default"]
        must_keep_by_file = {
            "02-release-notes.md": [c["title"] for c in external] + terms,
            "04-assessment.md": [c["id"] for c in external] + terms,
        }
        for name in ("02-release-notes.md", "04-assessment.md"):
            outputs[name], status = polish_markdown(outputs[name], must_keep_by_file[name])
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
    ap.add_argument("--review-text", action="store_true",
                    help="Optional AI review of free-text for typos/clarity (needs an API key; "
                         "only flags issues, never changes text).")
    ap.add_argument("--validate", action="store_true",
                    help="Only validate the changelog (schema + registry + consistency) and exit; "
                         "write nothing. Fails on a schema error or (with --strict) on warnings.")
    args = ap.parse_args()

    repo = pathlib.Path(args.changelog).resolve().parent
    data = yaml.safe_load(open(args.changelog))

    schema_errors = check_schema(data)          # fail fast on structural problems
    if schema_errors:
        raise SystemExit("SCHEMA ERROR:\n  - " + "\n  - ".join(schema_errors))

    warnings = check_source(data, repo)
    for w in warnings:
        print(f"SOURCE WARNING: {w}")

    if args.review_text:
        from llm_polish import review_text
        items = [(c.get("id"), f"{c.get('title','')} - {c.get('description','')}")
                 for c in data["changes"] if c.get("visibility") == "external"]
        suggestions = review_text(items)
        for s in suggestions:
            print(f"AI REVIEW: {s}")
        if not suggestions:
            print("AI REVIEW: skipped or no issues (needs an API key to run).")
    if warnings and args.strict:
        raise SystemExit("Source-consistency warnings present and --strict set.")

    if args.validate:
        # schema already passed (or we'd have exited); warnings printed above.
        print(f"VALIDATION OK: changelog is structurally valid ({len(data['changes'])} changes, "
              f"{len(warnings)} warning(s)).")
        return

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
