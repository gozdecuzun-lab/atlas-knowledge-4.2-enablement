# Atlas Knowledge 4.2 — Release Enablement

Turns the 4.2 changelog into customer release training, and makes the next release a matter of
minutes: edit `changelog.yaml`, run one script, and the release notes, assessment, and a
competency-map scaffold regenerate themselves.

## Contents

| File | What it is | How it's produced |
|------|------------|-------------------|
| `changelog.yaml` | Source of truth for the release. | Given (indentation normalized — see below). |
| `samples/` | API + webhook request/payload samples. | Given. |
| `01-competency-map.md` | Final competency map (admin). | Human-authored, refined from the scaffold. |
| `02-release-notes.md` | Customer release notes. | **Generated.** |
| `03-module-15min.md` | 15-minute module, hands-on exercise, evaluation plan. | Human-authored. |
| `04-assessment.md` | 5-item readiness assessment + answer key. | **Generated.** |
| `competency-map-scaffold.md` | Mechanical competency draft for human review. | **Generated.** |
| `pipeline/generate.py` | Generator: rules, templates, quality gates, `--check`, source checks. | — |
| `pipeline/llm_polish.py` | Optional, guarded LLM polish layer. | — |
| `pipeline/templates/`, `pipeline/prompts/` | Content templates and the polish prompt (prompt-as-code). | — |
| `tests/` | Quality-gate, regeneration, drift, and LLM-guardrail tests. | — |
| `.github/workflows/ci.yml` | CI: runs tests + drift check on every push. | — |
| `AI-LOG.md` | How AI was used. | — |

## How to run

```bash
pip install -r requirements.txt

python pipeline/generate.py            # regenerate (deterministic)
python pipeline/generate.py --check    # fail if committed outputs are stale (used in CI)
python pipeline/generate.py --strict   # treat source-consistency warnings as errors
python pipeline/generate.py --polish   # optional guarded LLM polish (needs an API key; safe to omit)

python -m pytest -q                    # or: python tests/test_pipeline.py && python tests/test_llm_polish.py
```

To prepare the **next** release, add entries to `changelog.yaml` and re-run `generate.py`. You do
not hand-edit any generated file. `tests/changelog_with_new_entry.yaml` is a worked example that
adds a new breaking change and a new internal change.

## Design

**Deterministic core.** Release notes and assessments are accuracy-critical, so generation is
deterministic and template-based: reproducible, no hallucination risk, no API key required. Quality
is enforced in layers:

1. **Rules** — level, action, and competency are derived from structured fields
   (`type`, `breaking`, `visibility`).
2. **Human-authored templates** — wording lives in `pipeline/templates/`, reviewed once, reused.
3. **Quality gates** (`generate.py`) — refuse to write output if an invariant breaks (internal
   change leaks, breaking change with no action, assessment item missing a competency, fewer than
   two scenario items, a change missing from the map). Exercised by the tests.
4. **Source-consistency + cross-field checks** — surface contradictions in the raw material (see
   below) and unusual field combinations (e.g., an internal change aimed at customer roles, a
   deprecation with no removal date, a feature that defaults off with no flag) as warnings;
   `--strict` makes them fail the build. These are warnings, not errors, so a legitimate edge case
   is never blocked.
5. **Drift check** (`--check`) — CI fails if committed outputs no longer match the changelog, so the
   generated files can never silently go stale.

**Optional guarded AI layer** (`--polish`, `pipeline/llm_polish.py`). An LLM may only *rephrase*
already-correct Markdown. Every call is verified: the returned text must still contain every
required fact (change IDs, field names, settings paths, flags); if any is missing, or there is no
API key, the LLM output is rejected and the deterministic text is returned unchanged. So enabling
`--polish` can, at worst, do nothing — it can never introduce a wrong or hallucinated release note.
The guardrail is unit-tested with fake models (`tests/test_llm_polish.py`).

## Assumptions

- The customer admin is the primary audience and also enables their author/developer/partner teams.
- The assessment produces **one item per externally visible change**, so coverage scales with the
  release (4.2 → 5 items).
- Internal-visibility changes are excluded from every customer-facing artifact.
- "Levels" reflect the admin's responsibility and risk, not a change's technical depth.

## Source material: issues found

The generator prints these as warnings on every run (and `--strict` fails on them):

1. **`changelog.yaml` indentation.** As received (from the PDF), entries C4–C6 were mis-indented and
   the file did not parse. Indentation normalized; content unchanged.
2. **Search API removal date (C1).** `removal_release: "4.3"` contradicts the description ("v1
   remains supported through release 4.4"). Detected automatically as a warning and flagged in the
   assessment; the customer release note deliberately avoids publishing a specific (possibly wrong)
   removal release and points to the migration guide instead. Confirm with the product team.
3. **Webhook field name (C6 vs. sample).** The changelog renames `article_id` → `article_uuid`, but
   `samples/webhook_article_published_v2.json` labels the field `articleId`. Sample kept as given;
   mismatch flagged in the module/assessment and detected automatically.

## Evaluation

`03-module-15min.md` includes a success-criteria plan (reaction / learning / behavior), with a
per-competency pass bar on the assessment (≥ 4/5 overall and both breaking-change items correct).
Because the assessment is regenerated each release, this per-competency signal is available every
time, not just for 4.2.

## What I'd do with more time

- Audience-specific release notes (separate admin / developer / author views from the `audience`
  fields).
- Multiple-choice distractors and difficulty tags on assessment items.
- Auto-generate the 15-minute module outline the way the competency scaffold is generated.
- A small eval set for the `--polish` layer (golden rephrasings) in addition to the fact-preservation guardrail.
- A consistency check that the hand-authored competency map's coverage and levels match the pipeline's derivation, so the human map and the generated outputs cannot silently drift. (Left out deliberately here: for a 4–6 item map, human review is sufficient and a hard check would add more overhead than value.)
