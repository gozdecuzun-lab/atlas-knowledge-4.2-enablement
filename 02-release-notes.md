# Atlas Knowledge 4.2 — Customer Release Notes

**Release date:** 2026-11-30

## ⚠ Breaking changes (action required)

These changes can break existing behavior or integrations. Review each one and complete the required action before 2026-11-30.

### [API deprecation] Search API v1 deprecated

GET /v1/search is deprecated. Use GET /v2/search, which requires a locale query parameter (for example en-US). v1 remains supported through release 4.4.


**Who is affected:** developer, partner
**Action required:** Required: migrate off the deprecated endpoint. It will be removed in a future release; confirm the exact timing in the migration guide before you migrate. Coordinate with your developer and partner teams.

### [API change] Webhook payload v2 for article.published

The article.published webhook now sends payload v2. The integer field article_id is replaced by the string field article_uuid. Integrations that parse article_id must be updated.


**Who is affected:** developer, partner
**Action required:** Required: update any integration that parses the changed field or payload. Coordinate with your developer and partner teams.

## Other changes

### [Config change] Default SSO session timeout reduced

The default SSO session timeout changes from 8 hours to 1 hour for new and existing tenants. Admins can override it under Settings > Security > Session.


**Who is affected:** admin, partner
**Action:** Review the new default and override it in settings if it does not suit your tenant.

### [UI change] Publish button moved to top toolbar

In the Author Console, Publish moves from the article footer to the top toolbar. No behavior change.


**Who is affected:** author
**Action:** No action required; let affected users know about the new location.

### [New feature] Citations in AI Answers

AI Answers can show the source articles behind each answer. Enable it per portal under AI Answers > Display > Show citations.


**Who is affected:** admin, partner, prospect
**Action:** Optional: this ships off by default; enable it per portal if you want it.

---
*Generated automatically from `changelog.yaml` by `pipeline/generate.py`. Internal-only changes are excluded. Do not edit by hand; edit the changelog or the templates and regenerate.*