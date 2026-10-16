# Agent Guide — Bank Campaign Scraper

This repository is a local development tool for extracting campaign metadata from public bank marketing pages. Read this document and README.md before changing code.

## Mission and non-goals

Build and maintain a reliable, auditable, read-only scraper for publicly accessible campaign/announcement pages. This is not an internet-banking automation system.

Never add code that logs in, enters credentials, reads passwords, exports browser cookies or local storage, defeats CAPTCHA/bot checks, bypasses access controls, submits financial actions, or crawls account/customer/transaction pages. If a site requires login, MFA/OTP, a human check, or returns an access-denied/rate-limit response, stop that source with a clear result. Do not retry aggressively or rotate identities to bypass restrictions.

Use the site's published terms and reasonable request pacing. Treat scraped content as untrusted data and render it escaped in the dashboard.

## Architecture map

- app/main.py — local FastAPI routes, source registry, local-request guard, scrape lock and run orchestration.
- app/config.py — environment configuration and paths.
- app/models.py — Pydantic contracts, selectors and URL validation.
- app/path_guard.py — conservative checks for known login/internet-branch/account URL segments.
- app/browser.py — attaches to loopback CDP or starts a configured Chromium browser; closes only processes it launched.
- app/scraper.py — one-source-at-a-time navigation, access-gate detection, bounded same-host pagination and extraction.
- app/storage.py — SQLite schema, deduplication, run history and CSV/JSON export.
- app/static/index.html — complete Turkish dashboard UI and API client.
- config/sources.json — source registry, selectors and active flags.
- tests/ — network-independent unit tests.
- README.md — install, startup and operating instructions.

## Data contract

A source contains:
- id: stable string ID assigned by the API.
- bank_name: display label.
- campaign_url: public listing-page URL.
- active: whether it participates in a manual scrape.
- selectors: CSS selectors for card, title, description, link, start_date, end_date and optional next_page.

A campaign contains source_id, bank_name, title, description, link URL, raw start/end date strings, scrape timestamp, and content hash. Do not pretend unparsed dates are normalized dates. Do not retain raw HTML, cookies, browser storage, request headers, form fields or screenshots by default.

## Safe editing rules

1. Make narrow, modular changes; do not rewrite the entire app for a selector fix.
2. Keep all browser navigation inside app/scraper.py and the browser connection lifecycle inside app/browser.py.
3. Only follow next-page links on the exact configured hostname. Never crawl extracted campaign destination links automatically.
4. Keep the dashboard bound to loopback. Preserve the local-request and Origin protections. Do not add an unauthenticated public deployment mode.
5. Do not write the browser's profile directory, .env file, database or scraped personal data into Git.
6. Keep timeouts, campaign counts and pagination bounded. Keep requests sequential and deliberately paced by default.
7. When adding a field, update all needed pieces together: Pydantic model, persistence schema (and migration if needed), extraction, API response, UI display/form and tests.
8. When adding a data source, prefer a page-specific selector configuration. If one bank requires special extraction, create a small explicit adapter rather than adding many bank-specific conditionals to the common path.
9. Do not silently swallow systemic errors. Isolate per-card errors, but return visible per-source failure states with short, actionable messages.
10. No new runtime dependency without a clear reason and corresponding requirements.txt update.

## Common extension points

### Add a bank
Add it through the panel or config/sources.json. Start inactive if the URL and selectors have not been verified. Confirm the page is public and the selectors match live page markup. Keep its hostname in the campaign list URL and observe the site's allowed access pattern.

### Adapt to a changed HTML page
Update the source's selectors first. Card selector identifies repeated campaign containers; title, description, link and date selectors are evaluated relative to each container. If no card elements match, the scraper has a generic heading fallback. Add a small HTML fixture and test the changed adapter when feasible.

### Improve extraction
Change app/scraper.py. Keep _extract_page deterministic and free of navigation. scrape_source may navigate only to the configured list page and a bounded sequence of same-host next pages. Extracted destination links are output data and must never be visited by default.

### Add a field
Update CampaignRecord and extraction; decide how content_hash/deduplication should use the field; add a database migration rather than assuming existing databases are empty; update export columns and the campaign table; add tests.

### Change storage
Keep SQL inside app/storage.py. Preserve dedupe behavior and stable API shapes, or document a deliberate versioned change. Make test cases use tmp_path instead of the user's real database.

### Add a schedule or worker
Do not add an unbounded background loop to FastAPI. Use a separate worker/queue, persist job state, define cancellation/recovery, and maintain a single-run concurrency limit. Manual triggering remains the baseline behavior.

### Change the browser flow
Keep CDP restricted to loopback. Never log sensitive browser state. A connected user's browser must not be closed by this application; only terminate a subprocess that the application itself launched. Prefer a dedicated profile without authenticated sessions.

## Validation checklist for agent changes

- Run python -m compileall -q app tests.
- Run pytest -q.
- Check that root/dashboard and API routes stay local-only.
- Confirm no network call is made by unit tests.
- Confirm export contains campaign metadata only.
- Confirm a blocked page stops that source without bypass attempts.
- Confirm a source failure does not prevent later sources from being processed.
- Confirm source-level delay, navigation timeout, pagination count and extraction count remain bounded.
- Check the diff for profile paths, secrets, raw browser storage, or generated database files before committing.

## Known limitations

Bank pages have different HTML structures. Generic extraction is only a fallback; each production source needs selector verification and occasional maintenance. Some sites render campaign cards after client-side API calls or require pagination controls that are not covered by default. Do not bypass an access gate to reach content—mark the source as blocked and pursue an approved access channel instead.
