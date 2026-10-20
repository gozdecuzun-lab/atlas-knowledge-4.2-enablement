# 15-Minute Module — Getting Ready for Atlas Knowledge 4.2 (Customer Admins)

**Audience:** Customer admins (who also enable their author, developer, and partner teams)
**Duration:** ~15 minutes
**Format:** Self-paced read + one hands-on exercise

**Learning objectives.** By the end, an admin can:
- CM1 — adjust the SSO session timeout for their tenant.
- CM2 — enable and verify AI Answers citations per portal.
- CM3 — recognize the two breaking integration changes and brief their dev/partner teams.
- CM4 — tell authors where Publish moved.

---

## 1. SSO session timeout is now 1 hour (3 min) — CM1

**What changed.** The default SSO session timeout drops from **8 hours to 1 hour**, for **new and
existing** tenants. On day one, users may be logged out more often than before.

**What to do.** Decide whether 1 hour fits your security posture. To change it:
`Settings > Security > Session` → set your preferred timeout.

**Talking point for your team:** warn help-desk staff so they aren't surprised by "I keep getting
logged out" tickets.

## 2. Turn on citations in AI Answers (3 min) — CM2

**What changed.** AI Answers can now show the **source articles** behind each answer. It ships
**off by default** (feature flag `ai_answers_citations`).

**What to do.** Enable it **per portal**: `AI Answers > Display > Show citations`. Then ask a test
question and confirm the source articles appear under the answer.

## 3. Two breaking changes your dev/partner teams must act on (4 min) — CM3

You won't write the code, but you own release readiness, so flag these early:

- **Search API v1 is deprecated (C1).** Calls move from `GET /v1/search` to `GET /v2/search`,
  which **requires a `locale` parameter** (e.g., `en-US`). *(Heads-up: the changelog is
  inconsistent about the exact removal release — the field says 4.3, the description says
  supported through 4.4. Confirm the deadline with the vendor.)*
- **Webhook payload v2 for `article.published` (C6).** The integer `article_id` is replaced by the
  string `article_uuid`. Any integration that parses `article_id` will break until updated.

**What to do.** Send both items to your developer and partner contacts this week and ask them to
confirm a migration plan before go-live.

## 4. Publish moved in the Author Console (1 min) — CM4

**Publish** moved from the article footer to the **top toolbar**. No behavior change. Let your
authors know so they aren't hunting for the button.

---

## Hands-on exercise (4 min) — using the API & webhook samples

Open the two files in `samples/` and answer the questions. (Answer key below — try first.)

**File A — `samples/search_v2_request.json`:**
```json
{
  "method": "GET",
  "url": "https://api.atlas.example/v2/search?q=reset%20password&locale=en-US&limit=5",
  "headers": { "Authorization": "Bearer <token>" }
}
```

**File B — `samples/webhook_article_published_v2.json`:**
```json
{
  "event": "article.published",
  "payload_version": 2,
  "articleId": "a7c9e2f4-1b3d-4e8a-9f60-2d5c8b1e7a43",
  "title": "How to reset your password",
  "portal": "customer-help",
  "published_at": "2026-11-30T17:05:00Z"
}
```

**Questions**
1. In File A, which query parameter is new in v2, and what happens to a v1-style call that omits it?
2. In File B, the changelog says integrations should now read `article_uuid` instead of
   `article_id`. What do you notice about the field name actually used in this sample, and what
   would you do about it?
3. Which teammate (developer or partner) would you send each file to, and what is the one action
   you would ask them to take?

<details>
<summary><strong>Answer key</strong></summary>

1. **`locale`** (e.g., `en-US`) is required in v2. A call that omits it will fail, because v2 makes
   locale mandatory — so a straight copy of a v1 call (no locale) breaks.
2. The sample labels the field **`articleId`**, which matches neither the old `article_id` nor the
   new `article_uuid` from the changelog. This is a source inconsistency: confirm the exact field
   name with the vendor before your team codes against it, and have them parse the **string UUID**
   value regardless of the final field name.
3. Both files go to the **developer and partner** teams who own the integrations. Ask them to
   (A) add the `locale` parameter and move to `/v2/search`, and (B) update the webhook consumer to
   read the string article identifier rather than an integer `article_id`.

</details>

*This module maps to competencies CM1–CM4 in `01-competency-map.md`.*
