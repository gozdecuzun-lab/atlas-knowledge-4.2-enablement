# Atlas Knowledge 4.2 — Admin Readiness Assessment

5 items. Each item maps to a competency and a change. Scenario-based items
are marked **[Scenario]**. An answer key with a one-line rationale follows each item.

## Q1. **[Scenario]** A developer on your team reports that calls to the old search endpoint started returning deprecation warnings after the 4.2 upgrade. What do you advise, and by when must they act?

- **Competency:** Support the team through breaking API and integration changes (troubleshoot)
- **Change:** C1
- **Answer key:** Migrate to the v2 search endpoint (which requires a `locale` parameter, e.g. en-US). Note the changelog is internally inconsistent about the exact removal release (field says 4.3, description says supported through 4.4), so confirm the deadline with the vendor before planning the cutover.
- **Rationale:** Tests whether the admin can triage a deprecation and coordinate a migration.

## Q2. **[Scenario]** After upgrading, users complain they are being logged out far more often than before. What changed, and how do you address it?

- **Competency:** Manage: Default SSO session timeout reduced (apply)
- **Change:** C2
- **Answer key:** The default SSO session timeout dropped from 8 hours to 1 hour for new and existing tenants. If that is too short, override it under Settings > Security > Session.
- **Rationale:** Tests whether the admin can connect a reported symptom to the config change and act.

## Q3. In the new Author Console, where do authors now click to publish an article, and does publishing behave differently?

- **Competency:** Be aware of: Publish button moved to top toolbar (know)
- **Change:** C3
- **Answer key:** Publish moved from the article footer to the top toolbar. There is no behavior change.
- **Rationale:** Tests awareness of the UI change so the admin can inform authors.

## Q4. A stakeholder asks why AI Answers are not showing source citations after the upgrade. Why, and how do you turn them on?

- **Competency:** Configure and validate: Citations in AI Answers (apply)
- **Change:** C4
- **Answer key:** Citations ship off by default (feature flag `ai_answers_citations`). Enable them per portal under AI Answers > Display > Show citations.
- **Rationale:** Tests whether the admin knows the feature is opt-in and how to enable it.

## Q5. **[Scenario]** After the upgrade, an integration that listens to the article.published webhook can no longer find the article's ID and stops working. What likely broke, and what is the fix?

- **Competency:** Support the team through breaking API and integration changes (troubleshoot)
- **Change:** C6
- **Answer key:** Payload v2 replaces the integer `article_id` with the string `article_uuid`; update the integration to parse `article_uuid`. (The provided v2 sample labels the field `articleId`, so confirm the exact field name with the vendor.)
- **Rationale:** Tests whether the admin can diagnose a breaking payload change and guide the fix.

---
*Generated automatically from `changelog.yaml` by `pipeline/generate.py`. One item is produced per
externally visible change, so coverage scales with the release. Do not edit by hand.*