---
name: psx-investing
description: Research Pakistan Stock Exchange shares across KSE-100, KMI-30 and liquid penny stocks. Produce evidence-backed buy, sell, hold and profit-taking calls for long-term value, short-term swing and intraday opportunities, with dated Shariah tags and moderate-risk filters. Use for PSX stock selection, portfolio reviews and signal updates; does not execute orders or monitor continuously by itself.
---

# PSX Investing & Trading

Find attractive risk-adjusted opportunities in Pakistan equities. Optimise upside subject to moderate risk, execution quality and evidence quality. Never promise maximum profit, reliable income or guaranteed exits. Small positions do not make inherently high-risk shares moderate risk.

## Efficient execution first

Read [efficient-runtime.md](references/efficient-runtime.md) and use `scripts/psx.py` before browsing. Default follow-ups to a quick cached watchlist update; run a full-market screen only when requested. Refresh source indexes cheaply, read only changed disclosures, merge new price sessions and run calculations in one local batch. Preserve source dates and fail closed on stale or incomplete data.

Start with `status` and `last-calls`. Quick refresh defaults to 45 seconds/8 requests; full refresh to 120 seconds/16 requests. Cap browser-history fallbacks to 3 symbols on quick updates. Do not repeatedly rediscover failed endpoints, dump raw pages into context or silently expand a quick update into a broad scan. Cache or import data returned by other tools rather than retrieving it twice.

For routine updates, normally report only changed calls, level crossings, material new evidence and data gaps in 150–250 words. Say briefly when nothing changed. Save reviewed calls and evidence for the next run. A first history load or missing working provider can still be expensive: disclose cold-cache coverage; never claim the installed engine provides a connected/live market feed.

## Defaults and routing

- Use PKR, Asia/Karachi timestamps and Pakistan sessions. Verify current PSX hours, Friday sessions, Ramadan changes, holidays and halts; never inherit US calendars.
- Long term: 12–36 months. Short term/swing: 3–20 trading sessions. Quick profit: intraday to 2 sessions. These are planning horizons, not guaranteed holding periods.
- For a full selection, aim for 2 long-term names and 3 short-term/quick names combined. Include a separate penny-stock result, which may overlap tactical names. Never force counts, duplicate a name to pad results or manufacture a penny pick. Explain unfilled slots.
- Core universe: current KSE-100 and KMI-30 constituents. Screen other PSX listings for liquid low-priced opportunities. Verify membership and label outside-index names accurately.
- Tag every candidate's Shariah status. Mixed research may include clearly labelled non-compliant names. If the user requires Shariah-only, exclude non-compliant and unverified names from positive calls. Mentioning KMI-30 alone does not imply Shariah-only.
- Research can proceed without personal financial details. Ask for holdings/cost only when needed for a position review; do not invent capital, share quantities or allocation amounts.

Read [sources-and-shariah.md](references/sources-and-shariah.md) before gathering evidence, and [screening-and-calls.md](references/screening-and-calls.md) for relevant horizon rules and risk gates.

## Research workflow

1. Establish analysis timestamp and actual latest completed session. Check current sources for every fresh call, reusing valid cache and conditional refreshes instead of downloading unchanged bodies. Retrieve official index levels, breadth, sectors and comparable share histories. Distinguish total-return and price-return indices.
2. Declare scope: symbols attempted, valid histories, exclusions and failures. A checked shortlist is not a whole-market scan. Never substitute remembered picks for a current screen.
3. Gather latest filings, company announcements, corporate actions, listing/risk status and official Shariah evidence. For finalists, check news since the last session and material announcements since the last results. Look ahead across the intended holding period for known events.
4. Assess relevant current affairs: SBP rates, inflation, PKR, reserves/IMF developments, budget/tax, sector regulations, oil/energy prices, circular debt, political/security disruptions and material global developments. Explain the specific transmission to the company. Separate facts, reported claims and interpretation.
5. Apply financial, liquidity, volatility and event gates before ranking. Rank value names by quality, valuation and catalysts; tactical names by structure, relative strength, execution and reward/risk. Value never excuses ignoring a failed trading stop.
6. Compute indicators and levels from consistent cached history in one batch with the bundled engine. Record window, adjustment basis and formula choice. Cite inputs; distinguish calculations from published figures. Technical REVIEW is not a BUY and does not establish fundamentals, Shariah status, events or achievable reward/risk. Never estimate RSI, ATR or moving averages from headlines or visual impressions.
7. Give an explicit call per horizon, with trigger and invalidation. A bullish index alone never triggers a share call. Refresh prices/evidence before calling an entry active; stale setups remain conditional or unavailable.

## Output

Lead with market stance and timestamp. Show separate long-term and tactical tables. Include these fields per candidate, moving detail below the table when necessary:

| Field | Required content |
|---|---|
| Identity | Symbol, company, verified index membership/outside-index label, penny label if applicable |
| Horizon/call | Planned window; BUY / CONDITIONAL BUY / HOLD / TAKE PROFIT / SELL / AVOID / WATCH |
| Shariah | COMPLIANT / NON-COMPLIANT / UNVERIFIED, official source and effective date; transition note |
| Price/entry | Reference quote and timestamp, delay/session status, entry band and exact confirmation |
| Exit | Stop or thesis invalidation; T1/T2 or valuation range, profit-taking rule, time/review exit |
| Economics | Cost-adjusted reward/risk; disclose uncosted estimates and gap/liquidity exposure |
| Evidence | Financial quality/value or setup, catalyst, upcoming events, downside and direct sources |
| Assessment | Moderate-risk gate result; evidence quality high/medium/insufficient, never a win probability |

Long-term plans need thesis invalidation; tactical plans need a price stop and time exit. Explain unfilled slots, rejected high-risk penny candidates, data gaps and what changes the calls. With insufficient evidence, deliver dated WATCH/NO TRADE rather than invented figures. Include one brief sentence that these are research calls and gaps can exceed planned losses.

## Updates and authorization

- Refresh prices, disclosures, Shariah changes and headlines on follow-ups. Compare with the last explicit call: pending/triggered/expired, stop breached, target reached or thesis changed. Price touching a level does not prove execution or realised gains.
- Revalidate tactical calls each session. Pending entries expire after 2 sessions unless explicitly stated otherwise. Review long-term theses after results/material events and financials at least quarterly.
- This skill checks sources on each run. Never claim background watching, real-time feeds, alerts or scheduled updates without a configured service. If asked for recurring monitoring, use available automation tools; notify only on material changes unless routine reports are requested.
- Research does not authorize orders, paid data subscriptions, brokerage connections or account changes. This skill does not execute trades.
- Default cash equities only: no leverage, short selling, derivatives or averaging down to rescue a failed quick trade. Equity Shariah status does not certify the broker's transaction method.
