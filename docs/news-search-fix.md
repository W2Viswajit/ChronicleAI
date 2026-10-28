# News retrieval patch

## Verified update — 28 October 2026

The live local run now succeeds using a Bing News RSS fallback when GDELT
is unavailable. GDELT itself still returned HTTP 429; the fallback does not
bypass that limit. Both providers retain separate persistent pacing/cooldowns.
RSS candidates are filtered by publication time and all publisher text goes
through the existing public-URL, extraction, and topic relevance checks.
This RSS reader is for the project's personal, non-commercial local use.
Set NEWS_RSS_FALLBACK=0 to disable the fallback.

- Claude: 2 extracted articles in 3.10 seconds on the initial live test.
- India cricket: 2 extracted articles in 2.12 seconds after a seven-second gap.
- Cached repeats: 0.09 and 0.06 seconds, with zero provider requests.
- Browser verification with a five-article limit: 4 Claude articles, followed
  by 5 India cricket articles. Some publisher extraction failures remain visible
  under retrieval notices; inaccessible text is never fabricated.
- 40 Python tests pass; `node tests/test_search_ui.cjs` passes cooldown expiry,
  repeat-request suppression, preserved selections and double-click protection.

The UI shows a countdown if no provider can complete the search, then enables
the search button again. Timeouts also open a 30-second cooldown. Successful
candidate searches cache for 15 minutes; repeated fallback searches use that
cache before contacting GDELT. Extracted publisher text caches for six hours.

Run `./start.ps1` from the project directory. It now prefers `.venv-local`,
the repaired Python 3.13 environment, because the previous `.venv` referenced
a removed Python 3.11 installation. Existing `.venv` was preserved.

The sections below describe the earlier GDELT-only attempts and their failures.

The screenshot shows upstream HTTP 429 responses. GDELT rejected the searches before
the app could determine whether relevant news existed. The previous final
"No relevant accessible articles" message was misleading in that case.

## Behaviour

- At least six seconds between GDELT request starts, shared by all topics in the
  supported single-process server. One provider request runs at a time.
- Fifteen-minute persistent cache for successful candidate searches, shared across
  equivalent topic wording and article limits. True empty results cache for one minute.
- Existing six-hour extracted-article cache remains in place.
- Respect Retry-After in seconds or HTTP-date form. At most one automatic retry.
- Without a Retry-After header, repeated provider failures back off for 30, 60,
  120, 240 and then 300 seconds. A successful search resets this sequence.
- Pauses longer than 45 seconds return an explanation immediately instead of
  keeping the request asleep. Another topic does not bypass the provider cooldown.
- Cached topics remain available during a provider cooldown. Cooldowns persist
  in runtime/news-search.sqlite3 after restarting the backend.
- Search failures, real zero results, off-topic matches and publisher extraction
  failures are distinguished. No invented articles or fabricated successful results.
- No frontend design changes or new package dependencies.

This does not change GDELT's own quota or guarantee its availability. Other traffic
from the same public IP may still affect the service. Use one Uvicorn worker, as in
the existing launcher. Do not run several app copies against the provider.

## Install on Windows

1. Stop the backend with Ctrl+C.
2. Extract ChronicleAI-retrieval-rate-limit-fix.zip into a separate folder.
3. In PowerShell in that extracted folder, run:

   powershell -ExecutionPolicy Bypass -File .\apply-fix.ps1 -ProjectPath "C:\path\to\ChronicleAI"

   Replace the example path with your actual project folder. The installer backs
   up existing files before copying the patch. It does not modify .env or model setup.
4. Restart with your existing start.ps1. Search again in the browser.

Alternatively copy backend/news_search.py and backend/retrieval.py into your
project's backend folder, and scripts/verify_news_search.py into scripts.
Keep the two backend files together. The complete retrieval.py replaces your local
2s/4s/8s/16s retry implementation and preserves the repository's relevance filters.
Back up any other local custom retrieval changes before installing.

## Verify two real topics

From your project folder, with the app closed to avoid competing searches:

   .\.venv\Scripts\python.exe -m scripts.verify_news_search --gap 35

This searches "Bengaluru metro", waits at least 35 seconds (or the provider's longer
cooldown), then searches "India cricket". It prints actual titles/URLs and counts.
If the first search succeeds, it repeats that query to check cache reuse.

PASS requires at least two extracted relevant articles per topic, successful
provider status for both topics, and reuse of the first query's cache. The JSON
report is runtime/news-search-verification.json. A failed report is kept, too.
If matching news is outside seven days, explicitly test --days 30; the program does
not silently widen your selected date range.

Regression tests:

   .\.venv\Scripts\python.exe -m pytest tests/test_news_search.py -q

## Verification in the development environment

14 focused automated tests passed. They use mocked provider responses and a
controlled clock for repeatable checks, including sequential topics, concurrency,
Retry-After, invalid responses, extraction errors, relevance and persistent cooldowns.

Actual live attempts: 2026-10-27 19:59:22 UTC for Bengaluru metro and 19:59:57 UTC
for India cricket. Both failed before reaching GDELT due to DNS resolution failure
(socket.gaierror: Temporary failure in name resolution) in this environment.
Live article retrieval was NOT verified successfully. The included live-results.json
records this failure honestly. Run the supplied verifier on the Windows laptop.
