# Competency Map — Atlas Knowledge 4.2 (Customer Admin)

**Audience:** Customer admins, who are also responsible for enabling the authors and
developers on their teams.

**Levels:**
- **Know** — can recognize the change and explain what it means / who it affects.
- **Apply** — can perform the configuration or task correctly in their own tenant/portal.
- **Troubleshoot** — can diagnose problems the change causes and guide their team to a fix.

> Scope note: C5 (Indexing service refactor) is `visibility: internal` and is intentionally
> excluded from all customer-facing materials, per the changelog.

| # | Competency | Changes covered | Level | What the admin must be able to do |
|---|------------|-----------------|-------|-----------------------------------|
| CM1 | **Manage the SSO session security policy** | C2 | **Apply** | Understand that the default SSO session timeout drops from 8h to 1h for new *and existing* tenants, anticipate the day-one impact on users, and override it when needed under `Settings > Security > Session`. |
| CM2 | **Configure and validate AI Answers citations** | C4 | **Apply** | Know the feature ships **off by default** (flag `ai_answers_citations`), enable it **per portal** under `AI Answers > Display > Show citations`, and verify citations appear as expected. |
| CM3 | **Support the team through breaking API & integration changes** | C1, C6 | **Troubleshoot** | Recognize the two breaking changes (Search API v1 deprecation; `article.published` webhook payload v2), communicate required actions to developer/partner teammates, and triage failures (e.g., v1 search errors, integrations still parsing `article_id`). |
| CM4 | **Guide authors through the Author Console change** | C3 | **Know** | Be aware that **Publish** moved from the article footer to the top toolbar (no behavior change) so authors can be informed proactively and support tickets are avoided. |

## Rationale (mapping logic)

- **Every externally visible change is covered**, and each is placed at the level that matches the admin's real responsibility, not the change's technical depth.
- **Breaking changes drive the highest level.** C1 and C6 are `breaking: true`; even though they are developer-facing, the admin owns release readiness for their team, so the expected level is **Troubleshoot**.
- **Action-required config changes are Apply.** C2 and C4 require the admin to *do something* in settings, so they sit at **Apply**.
- **Awareness-only UI changes are Know.** C3 has "no behavior change," so **Know** is sufficient.
- **Internal changes are excluded.** C5 never appears, in line with its `internal` visibility.

*This map is the backbone of the package: the release notes, the 15-minute module, and every
assessment item trace back to one of these four competencies (CM1–CM4).*
