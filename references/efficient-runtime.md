# Cached runtime

Use the bundled standard-library engine before browsing. `S` below is this skill's absolute folder. Run it with `python3 "$S/scripts/psx.py" ...`. Default database: `~/.cache/psx-investing/research.sqlite3`; `--db /absolute/path.sqlite3` or `PSX_CACHE_DIR` overrides it. Keep research data outside an unrelated application repository. The cache and source files can be financial research records; do not upload them or commit them to a repository automatically.

## Modes and token budgets

- **Quick update (default for follow-ups):** cached research watchlist only, 45-second/8-request refresh budget, normally at most 3 browser-history fallbacks, concise changed-call report. Do not silently expand into a market-wide scan.
- **Full screen (explicit request):** refresh universe once, batch first-pass filters and cached histories, then inspect new disclosures for at most 8 finalists. Default refresh budget 120 seconds/16 requests. Report uncovered candidates, not imaginary full coverage.
- **Offline snapshot:** no fetching; always label historical/unverified freshness. Never issue a fresh BUY solely from a snapshot.
- Ordinary quick replies aim for 150–250 words: as-of session, changes, triggered/invalidated plans and missing evidence. If no material changes, say so in a few lines. Full reports normally stay under 600 words unless more detail is requested.
- Print JSON summaries only. Never dump raw HTML, all cached bars, giant accessibility trees or unchanged filings into context. Read only source links and changed documents needed for finalists. Calculations run locally, not in an LLM token stream.

Start with:

```bash
python3 "$S/scripts/psx.py" status
python3 "$S/scripts/psx.py" last-calls
python3 "$S/scripts/psx.py" refresh --mode quick
python3 "$S/scripts/psx.py" screen --mode quick --session YYYY-MM-DD --limit 5
```

Verify the latest completed session from an actual current source before supplying `--session`; the engine does not guess holidays or special trading hours. `screen` does not fetch and never turns a technical pass into a BUY. `REVIEW` means further research, not a recommendation. Missing/stale history produces `DATA_REQUIRED`, not a falsely fresh signal.

For a full run, use `refresh --mode full` and `screen --mode full`. The first filter uses official screener P/E and current price times 30-day mean volume as a cheap liquidity **proxy**. It is not a substitute for median 20-session traded value. Every price-at-or-below-PKR-50 candidate receives the stricter penny gates even if also in KSE-100/KMI-30.

Set the research watchlist, not presumed holdings:

```bash
python3 "$S/scripts/psx.py" watchlist --set FFC OGDC EFERT PSO THCCL
```

## History ingestion and incremental updates

Accepted CSV or JSON records use these fields:

`symbol,date,open,high,low,close,adj_close,volume,value,source_url`

- Dates: ISO `YYYY-MM-DD`; source URL: actual public HTTPS provenance.
- `value` is optional actual traded PKR value. Missing values are estimated as close times volume and labelled accordingly; verify execution/liquidity before approving trades.
- Stock OHLC and volume must be genuine, not inferred from a closing-only endpoint. Benchmarks may have only close/adj_close with empty OHLC/volume; they are used for matching-date returns, not fabricated ATR.
- Supply the provider, stable adjustment-basis version and `price` versus `total_return` return basis. Do not mix providers/bases. Confirm corporate-action treatment before using `--adjustments-verified`. This switch records an analyst verification, not an automatic verification by the script.
- Imports merge by symbol/session/provider/basis, update corrected rows and skip exact duplicates. A changed historical adjustment factor requires a complete-series re-import with `--replace-series`; a partial import cannot silently rebase old bars. Use a new basis identifier for a genuinely different series and select it explicitly with `screen --basis`.

```bash
python3 "$S/scripts/psx.py" import-prices --file /absolute/path/bars.csv \
  --provider PROVIDER --basis VERIFIED-BASIS-VERSION --return-basis total_return \
  --adjustments-verified
```

For a verified provider that returns this normalized schema and supports a bulk date window:

```bash
python3 "$S/scripts/psx.py" sync-prices \
  --url-template 'https://YOUR-VERIFIED-PROVIDER/history?from={since}&to={until}&symbols={symbols}' \
  --symbols FFC OGDC KSE100 KMI30 --session YYYY-MM-DD --start YYYY-MM-DD \
  --provider PROVIDER --basis VERIFIED-BASIS-VERSION --return-basis total_return \
  --adjustments-verified
```

The URL above illustrates the contract; it is not an existing endpoint. Configure an actual verified feed before running it. First load needs `--start`; subsequent runs omit it and request only the missing window plus seven calendar days for corrections. An already-current cache skips the request. `--recheck` permits a bounded correction check but cannot bypass endpoint cooldowns. Periodic complete reconciliation is still needed for corporate-action rebases and older corrections.

No working automatic PSX OHLCV feed is bundled or assumed. The observed PSX history routes returned 404 and some secondary downloads returned 403 during setup. Use a permitted broker/export/provider adapter or browser-extracted visible data imported once. Do not repeat a 72-page browser traversal on every run. If history is missing, disclose cold-cache coverage and cap the browser fallback to the mode's budget; never claim a warm cache or completed screen prematurely.

## Documents, news and Shariah refresh

`refresh` checks the universe, indices, company/PSX announcements, SBP and watchlist company pages. It uses positive TTLs, ETag/Last-Modified conditional requests and semantic hashes. Company quote changes do not alone imply new financial results. Reports are downloaded/re-read only when a new/revised document appears or its scheduled verification is due. Old financial observations never acquire a newer reporting period merely because their source was checked again.

Track specific verified documents/news pages with:

```bash
python3 "$S/scripts/psx.py" track --url 'https://ACTUAL-SOURCE' --kind financial-document
```

Kinds include `financial-document`, `shariah-document`, `shariah-index`, `news`, `announcements`, `macro`, `company`, `market`, `universe` and `prices`. A document URL is immutable only as a working assumption: conditional rechecks and corrections still matter. Feed/index changes can require a new document review. `discovery_empty` means the static page did not reveal documents; use one focused browser/search check, not an inference that nothing happened. News is not limited to PSX/SBP: use a focused fresh news search for relevant politics, security, oil, regulation and company catalysts, with a last-successful-review watermark and a small overlap. Save the review watermark even when no relevant new event was found.

To reuse a source already retrieved by another tool, `cache-file --url URL --kind KIND --file PATH --checked-at ACTUAL-ISO-TIMESTAMP` saves it without downloading again. Preserve actual retrieval time; observation time remains separately visible. Only a successfully parsed screener replaces the cached universe.

Use `record-evidence --file facts.json` for reviewed financial, news/event and Shariah facts. Each record requires `symbol`, `kind`, `payload`, `source_url`, timezone-aware `checked_at`, ISO `effective_from` and `valid_until`. The payload should contain the financial reporting period or Shariah screening period, exception/purification notes and review conditions. Effective dates prevent future decisions overwriting present status. Source-hash changes mark linked evidence for review. Validity is a review deadline, not a guarantee of unchanged real-world status; always check relevant announcement indexes before using cached evidence for a new call.

Suggested maximum review intervals: news/events through next session, financial thesis through next results or at most a quarter, Shariah through the next effective review/announcement. Never make a tag perpetual or treat KMI membership as a complete independent screening decision.

## Endpoint failures and run limits

No automatic retry loop. HTTP 403: six-hour cooldown; 404: 24 hours; 429: 30 minutes; other failures: 15 minutes. Failed company/history route families are shared across symbols so one dead endpoint is not retried 72 times. Positive `--force` does not bypass cooldowns. Do not defeat controls, rotate identities or guess alternate nodes. Stale cached bodies remain available and labelled; failed checks do not advance successful-review watermarks. Network execution may require the environment's normal permission; do not interpret a blocked refresh as fresh data.

## Changed-call reports

Save the reviewed final calls with `record-calls --file calls.json`; read them using `last-calls` next time. Records require `symbol`, `horizon` (`long`, `swing`, `quick`), `call` and `as_of_session`; include entry, stop/thesis invalidation, targets, expiry, Shariah status and evidence quality as relevant. A BUY also requires explicit true `checks` for `price_fresh`, `fundamentals`, `shariah`, `events`, `liquidity`, `risk_reward`, and `adjustments`. These are analyst attestations, not automated proof.

The comparison ignores routine quote/check-time/source-commentary changes but reports changed calls, levels, thesis, status and expiry. Do not invent a SELL when a symbol disappears from a partial scan. Retain historical records; revalidate pending setups and tactical expiry using verified sessions. New stop/target crossings and new material events belong in the report even if the text label remains WATCH/HOLD. Save relevant state fields (`trigger_state`, `stop_state`, `target_state`, `event_state`) so they participate in comparisons.

There is no background service, trading execution or portal in this runtime. Keep the engine separate from a future UI so charts/watchlists/history can reuse it without replacing the research rules.
