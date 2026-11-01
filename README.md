# PSX Investing

A Codex research skill and Python cache engine for the Pakistan Stock Exchange: KSE-100, KMI-30 and liquid low-priced shares.

Research covers long-term value investing, swing setups and quick profit-taking opportunities, with dated Shariah tags, moderate-risk filters and explicit evidence gaps. The engine calculates technical screens; an analyst must review fundamentals, disclosures, news, execution and risk before making a call.

## Requirements

- Python 3.10 or newer, with the Asia/Karachi timezone available.
- No third-party Python packages required by the engine.
- Internet access for public-source refreshes; historical prices require a permitted export or compatible provider.

## Use

Clone this repository into your personal skills directory, or use it as a standalone engine:

```bash
git clone https://github.com/Qamarz74/psx-investing.git
cd psx-investing
python3 scripts/psx.py --help
python3 scripts/psx.py status
python3 scripts/psx.py refresh --mode quick
```

For Codex, install the repository folder as `~/.codex/skills/psx-investing`, then invoke `$psx-investing`. Read [SKILL.md](SKILL.md) for the research workflow and [runtime instructions](references/efficient-runtime.md) for price imports, full screens and saved calls.

The bundled default watchlist contains examples, not portfolio holdings or recommendations. Set your own research list using `watchlist --set SYMBOL ...`.

## Efficient updates

SQLite stores source freshness, price histories, evidence and previous calls. Updates reuse cached documents, merge missing sessions and report meaningful call changes. Quick refreshes default to 45 seconds and eight requests; full refreshes default to 120 seconds and sixteen requests. Cold-cache research can take longer and require manual imports.

The default cache lives outside this repository at `~/.cache/psx-investing/research.sqlite3`. Override it with `PSX_CACHE_DIR` or `--db`. Keep personal watchlists, holdings, research records and credentials private.

## Limits

No automatic PSX historical OHLCV feed, live quote feed, broker connection, order execution or continuous monitoring is bundled. The generic incremental adapter needs a verified compatible provider. A technical `REVIEW` is not a BUY; stale or incomplete evidence must remain conditional or unavailable. Shariah tags require dated official verification and can change.

Research cannot guarantee returns. Gaps and illiquidity can exceed planned losses. These tools support research, not personalized financial advice.

## Contributing and licence

Keep changes focused, describe validation performed and never commit credentials, personal research or downloaded market datasets. Code and original instructions are MIT licensed; third-party data, documents and trademarks retain their owners' rights. Check source terms before collecting or redistributing data.
