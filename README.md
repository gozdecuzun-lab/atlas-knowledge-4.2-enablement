# Atlas Knowledge 4.2 — Release Enablement

Turns the 4.2 changelog into customer release training, and makes the next release a matter of
minutes: edit `changelog.yaml`, re-run one script, and the release notes, assessment, and a
competency-map scaffold regenerate themselves.

## Contents

| File | What it is | How it's produced |
|------|------------|-------------------|
| `changelog.yaml` | Source of truth for the release. | Given (indentation normalized — see below). |
| `samples/` | API + webhook request/payload samples. | Given. |
| `01-competency-map.md` | Final competency map (admin). | Human-authored, refined from the scaffold. |
| `02-release-notes.md` | Customer release notes. | **Generated** from the changelog. |
| `03-module-15min.md` | 15-minute module + hands-on exercise. | Human-authored. |
| `04-assessment.md` | 5-item readiness assessment + answer key. | **Generated** from the changelog. |
| `competency-map-scaffold.md` | Mechanical competency draft. | **Generated** from the changelog. |
| `pipeline/` | Generator + Jinja templates. | — |
| `tests/` | Automated tests + a changelog fixture. | — |
| `AI-LOG.md` | How AI was used. | — |

## How to run

```bash
pip install -r requirements.txt

# regenerate release notes, assessment, and the competency scaffold
python pipeline/generate.py

# run the tests (quality gates + regeneration proof)
python -m pytest -q          # or, with no pytest installed:  python tests/test_pipeline.py
```

To prepare the **next** release, add entries to `changelog.yaml` and re-run `generate.py`. You do
not hand-edit any generated file. (See `tests/changelog_with_new_entry.yaml` for a worked example
that adds a new breaking change and a new internal change.)

## Design: why a deterministic pipeline

Release notes and assessments are accuracy-critical, so the generator is **deterministic and
template-based**: no LLM at runtime. That means output is reproducible, carries no hallucination
risk, and runs with no API key. Quality is enforced in three layers:

1. **Rules** — level, action, and competency are derived from structured fields
   (`type`, `breaking`, `visibility`).
2. **Human-authored templates** — the wording lives in `pipeline/templates/` and in the per-type
   question text, reviewed once and reused.
3. **Quality gates** — `generate.py` refuses to write output if an invariant is broken (e.g., an
   internal change leaks out, a breaking change has no action, an assessment item is missing a
   competency, or there are fewer than two scenario items). The tests exercise these.

An optional LLM "polish" layer could enrich the prose later, but the reliable core stays
deterministic.

## Assumptions

- The customer admin is the primary audience and also enables their author/developer/partner teams.
- The assessment produces **one item per externally visible change**, so coverage scales with the
  release (4.2 → 5 items).
- Internal-visibility changes are excluded from every customer-facing artifact.
- "Levels" reflect the admin's responsibility and risk, not a change's technical depth.

## What I found unclear in the source material

1. **`changelog.yaml` indentation.** As received (from the PDF), entries C4–C6 were mis-indented
   and the file did not parse. I normalized the indentation; content is unchanged.
2. **Search API removal date (C1).** The field `removal_release: "4.3"` contradicts the description
   ("v1 remains supported through release 4.4"). I surfaced this in the release notes and
   assessment rather than guessing; it should be confirmed with the product team.
3. **Webhook field name (C6 vs. sample).** The changelog says `article_id` becomes `article_uuid`,
   but `samples/webhook_article_published_v2.json` labels the field `articleId`. I kept the sample
   as given and flagged the mismatch in the module and assessment.

## What I'd do with more time

- Add an optional LLM polish pass (with the deterministic output as the guardrail) for more varied,
  on-brand prose.
- Auto-generate the 15-minute module outline from the changelog, the way the scaffold is generated.
- Support audience-specific release notes (separate admin / developer / author views from the same
  `audience` fields).
- Add multiple-choice distractors and difficulty tags to assessment items.
- Validate the samples against the changelog automatically (e.g., assert the webhook field name
  matches), turning the inconsistencies above into failing checks.
