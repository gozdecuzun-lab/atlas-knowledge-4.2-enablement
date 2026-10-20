"""
Tests for the release-enablement pipeline.

Run:  python -m pytest -q      (or: python tests/test_pipeline.py)

What these prove:
  1. The real 4.2 changelog generates clean output and passes every quality gate.
  2. Internal-visibility changes NEVER leak into customer-facing output.
  3. Adding new entries to the changelog regenerates every output with no hand-editing:
     a new external breaking change shows up in the notes + assessment automatically,
     and a new internal change stays out.
"""
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
GEN = REPO / "pipeline" / "generate.py"
REAL_CHANGELOG = REPO / "changelog.yaml"
TEST_CHANGELOG = REPO / "tests" / "changelog_with_new_entry.yaml"

sys.path.insert(0, str(REPO / "pipeline"))
from generate import check_source, check_cross_field  # noqa: E402


def run(changelog, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(GEN), "--changelog", str(changelog), "--outdir", str(outdir)],
        capture_output=True, text=True)
    return proc


def read(outdir, name):
    return (outdir / name).read_text()


def test_real_changelog_passes_and_excludes_internal(tmp_path):
    proc = run(REAL_CHANGELOG, tmp_path)
    assert proc.returncode == 0, proc.stderr          # quality gates passed
    notes = read(tmp_path, "02-release-notes.md")
    assessment = read(tmp_path, "04-assessment.md")
    scaffold = read(tmp_path, "competency-map-scaffold.md")

    # internal change C5 must not appear anywhere customer-facing
    assert "C5" not in notes
    assert "C5" not in assessment
    assert "Indexing service refactor" not in notes

    # both breaking changes appear with an action
    assert "Search API v1 deprecated" in notes
    assert "Webhook payload v2" in notes
    assert notes.count("Action required:") == 2

    # assessment covers all 5 external changes and has >=2 scenario items
    for cid in ("C1", "C2", "C3", "C4", "C6"):
        assert cid in assessment
    assert assessment.count("[Scenario]") >= 2

    # scaffold merged the two breaking integration changes into one competency
    assert "C1, C6" in scaffold
    assert "C5" in scaffold and "Excluded" in scaffold


def test_adding_entries_regenerates_without_hand_editing(tmp_path):
    """The core promise: edit the YAML, re-run, outputs update themselves."""
    proc = run(TEST_CHANGELOG, tmp_path)
    assert proc.returncode == 0, proc.stderr
    notes = read(tmp_path, "02-release-notes.md")
    assessment = read(tmp_path, "04-assessment.md")

    # the NEW external breaking change (C7) is picked up automatically...
    assert "Bulk Export API v1 removed" in notes
    assert "C7" in notes
    assert "C7" in assessment

    # ...and placed in the breaking section with an action
    breaking_section = notes.split("## Other changes")[0]
    assert "C7" in breaking_section

    # the NEW internal change (C8) must stay out of customer-facing output
    assert "C8" not in notes
    assert "C8" not in assessment
    assert "relevance model" not in notes.lower()


def test_internal_only_changelog_still_safe(tmp_path):
    """Edge case: if an internal item is added, it is simply excluded, not leaked."""
    proc = run(TEST_CHANGELOG, tmp_path)
    scaffold = read(tmp_path, "competency-map-scaffold.md")
    # C8 shows only in the 'excluded' line of the scaffold, never as a competency row
    assert "C8" in scaffold.split("Excluded")[1]


def test_source_consistency_flags_known_issues():
    """The two real contradictions in the source material must be detected."""
    data = yaml.safe_load(open(REAL_CHANGELOG))
    warnings = check_source(data, REPO)
    text = " ".join(warnings)
    assert any("C1" in w and "removal_release" in w for w in warnings)   # 4.3 vs 4.4
    assert any("C6" in w and "article_uuid" in w for w in warnings)      # field-name mismatch
    assert len(warnings) >= 2


def test_cross_field_checks():
    """Cross-field warnings fire on bad combinations, and the real changelog is clean."""
    # the real changelog should NOT add cross-field noise
    real = yaml.safe_load(open(REAL_CHANGELOG))
    assert check_cross_field(real) == []

    # a crafted bad changelog should trip several cross-field warnings
    bad = {"changes": [
        {"id": "X1", "type": "internal", "visibility": "internal", "audience": ["admin"]},
        {"id": "X2", "type": "api_deprecation", "visibility": "external",
         "audience": ["developer"]},                              # no removal_release
        {"id": "X3", "type": "feature", "visibility": "external", "audience": ["admin"],
         "default": "off"},                                       # off but no feature_flag
        {"id": "X4", "type": "ui_change", "visibility": "external", "audience": ["author"],
         "breaking": True},                                       # cosmetic but breaking
    ]}
    warns = " ".join(check_cross_field(bad))
    assert "X1" in warns and "customer" in warns
    assert "X2" in warns and "removal_release" in warns
    assert "X3" in warns and "feature_flag" in warns
    assert "X4" in warns and "breaking" in warns


def test_check_mode_passes_on_committed_outputs():
    """--check must pass when the committed outputs match the changelog (no drift)."""
    proc = subprocess.run(
        [sys.executable, str(GEN), "--check", "--outdir", str(REPO)],
        capture_output=True, text=True)
    assert proc.returncode == 0, "committed outputs are stale; run generate.py\n" + proc.stdout


def test_check_mode_detects_drift(tmp_path):
    """--check must fail when outputs are missing/stale (drift)."""
    proc = subprocess.run(
        [sys.executable, str(GEN), "--check", "--outdir", str(tmp_path)],
        capture_output=True, text=True)
    assert proc.returncode != 0
    assert "DRIFT" in proc.stdout or "DRIFT" in proc.stderr


if __name__ == "__main__":
    # allow running without pytest installed
    import tempfile
    import inspect
    failures = 0
    for fn in (test_real_changelog_passes_and_excludes_internal,
               test_adding_entries_regenerates_without_hand_editing,
               test_internal_only_changelog_still_safe,
               test_source_consistency_flags_known_issues,
               test_cross_field_checks,
               test_check_mode_passes_on_committed_outputs,
               test_check_mode_detects_drift):
        try:
            if inspect.signature(fn).parameters:
                fn(pathlib.Path(tempfile.mkdtemp()))
            else:
                fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {fn.__name__}: {e}")
    sys.exit(1 if failures else 0)
