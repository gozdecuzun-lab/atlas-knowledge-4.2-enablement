# AI Log

**Tools used:** Claude (Anthropic) as a drafting and pair-programming assistant. No AI runs inside
the pipeline itself — generation is deterministic by design (see README).

## How I used AI

| Where | Prompt (paraphrased) | What I kept | What I changed and why |
|-------|----------------------|-------------|------------------------|
| Framing | "Summarize the assignment and the role of each audience (admin, author, developer, partner)." | The audience model and the admin-as-coordinator framing. | Nothing material; used it to anchor the competency map. |
| Competency map | "Draft 3–5 admin competencies for 4.2, mapped to changes and levels (know/apply/troubleshoot)." | The four-competency structure and the level logic. | Merged the two breaking API changes (C1, C6) into one competency; I decided the levels by admin *responsibility/risk*, not by technical depth. |
| Pipeline design | "Should the generator be deterministic or LLM-based? Trade-offs?" | The decision to go deterministic (accuracy, reproducibility, no API key). | I added explicit quality gates and a test harness, because "trust the template" is not enough on its own. |
| Release notes / assessment templates | "Draft Jinja templates and per-type action + question text." | The template structure and the per-change-type question styles. | Rewrote several answer keys to flag the source inconsistencies (see README) rather than paper over them. |
| Debugging | "Why is the C4 action wrong?" | The diagnosis: YAML parses `off` as boolean `False`. | Fixed the generator to treat both `False` and `"off"` as "off". |
| Guarded AI layer | "Add an optional LLM polish that cannot introduce errors." | The fact-preservation guardrail + fallback design. | Made the model injectable and wrote fake-model tests so the guardrail is proven without an API key; stored the prompt as a versioned file. |
| CI / drift | "How do I stop generated files from going stale?" | The `--check` drift mode + a CI workflow. | Added source-consistency checks and wired both into CI so staleness and contradictions fail the build. |

## Judgment calls the AI did **not** make for me

- Excluding C5 (internal) from all customer-facing output.
- Treating the breaking changes as the highest-priority competency.
- Choosing a deterministic pipeline with quality gates over an LLM pipeline.
- Flagging the three source inconsistencies instead of silently "fixing" them.

## Verification

Every AI-drafted output was checked against `changelog.yaml` by hand and by the automated quality
gates in `pipeline/generate.py` and `tests/test_pipeline.py`. Nothing was accepted on trust.
