#!/usr/bin/env python3
"""Bounded public-source cache and batch research calculations; never places orders."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")
DEFAULT_WATCHLIST = ["FFC", "OGDC", "EFERT", "PSO", "THCCL"]
ROOT = "https://dps.psx.com.pk"
TTLS = {"market": 900, "universe": 21600, "announcements": 1800,
        "shariah-index": 21600, "macro": 21600, "financial-document": 2592000,
        "shariah-document": 2592000, "news": 1800, "company": 3600, "prices": 900}
CALLS = {"BUY", "CONDITIONAL BUY", "HOLD", "TAKE PROFIT", "SELL", "AVOID", "WATCH", "NO TRADE"}
HORIZONS = {"long", "swing", "quick"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat(timespec="seconds")


def age(value: str | None) -> float:
    return (now() - datetime.fromisoformat(value)).total_seconds() if value else math.inf


def digest(value: Any) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def symbol(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", value):
        raise ValueError("Invalid symbol")
    return value


def https_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Sources require a public HTTPS URL without credentials")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Local endpoints are not market sources")
    return value


def num(value: Any) -> float:
    number = float(str(value).replace(",", "").strip())
    if not math.isfinite(number):
        raise ValueError("Non-finite numeric input")
    return number


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS resources(
          url TEXT PRIMARY KEY,kind TEXT NOT NULL,body BLOB,etag TEXT,modified TEXT,
          semantic_hash TEXT,checked_at TEXT,downloaded_at TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS health(
          bucket TEXT PRIMARY KEY,retry_at TEXT NOT NULL,error TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS universe(
          symbol TEXT PRIMARY KEY,payload TEXT NOT NULL,source_url TEXT NOT NULL,observed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS series(
          symbol TEXT,provider TEXT,basis TEXT,return_basis TEXT NOT NULL,
          verified INTEGER NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY(symbol,provider,basis));
        CREATE TABLE IF NOT EXISTS bars(
          symbol TEXT,session TEXT,provider TEXT,basis TEXT,
          open REAL,high REAL,low REAL,close REAL NOT NULL,adj_close REAL NOT NULL,
          volume REAL,value REAL,source_url TEXT NOT NULL,
          PRIMARY KEY(symbol,session,provider,basis),
          FOREIGN KEY(symbol,provider,basis) REFERENCES series(symbol,provider,basis));
        CREATE TABLE IF NOT EXISTS evidence(
          id INTEGER PRIMARY KEY,symbol TEXT,kind TEXT,payload TEXT NOT NULL,
          source_url TEXT NOT NULL,source_hash TEXT,checked_at TEXT NOT NULL,
          effective_from TEXT NOT NULL,valid_until TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS calls(
          id INTEGER PRIMARY KEY,symbol TEXT NOT NULL,horizon TEXT NOT NULL,
          payload TEXT NOT NULL,semantic_hash TEXT NOT NULL,recorded_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS calls_lookup ON calls(symbol,horizon,id);
        CREATE TABLE IF NOT EXISTS calculations(
          signature TEXT PRIMARY KEY,payload TEXT NOT NULL);
    """)
    db.execute("INSERT OR IGNORE INTO settings VALUES('watchlist',?)", (json.dumps(DEFAULT_WATCHLIST),))
    db.commit()
    return db


class Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self.row: list[dict[str, Any]] | None = None
        self.cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"}:
            self.cell = {"attrs": attributes, "text": [], "tags": [], "name": ""}
        if self.cell is not None and tag == "a" and attributes.get("data-title"):
            self.cell["name"] = attributes["data-title"]
        if self.cell is not None and tag == "div" and "tag--" in str(attributes.get("class", "")):
            self.cell["tags"].extend(str(attributes["class"]).split())

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.cell is not None:
            self.cell["text"] = " ".join("".join(self.cell["text"]).split())
            if self.row is not None:
                self.row.append(self.cell)
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_universe(body: bytes) -> list[dict[str, Any]]:
    table = Tables()
    table.feed(body.decode("utf-8", errors="replace"))
    result = []
    for row in table.rows:
        if len(row) != 11 or not row[0]["attrs"].get("data-order"):
            continue
        def cell(index: int) -> str:
            return row[index]["attrs"].get("data-order", row[index]["text"])
        result.append({"symbol": symbol(cell(0)), "name": unescape(row[0]["name"]),
                       "indices": cell(2).split(","), "price": num(cell(4)),
                       "pe": num(cell(7)), "yield": num(cell(8)),
                       "avg30_volume": num(cell(10)), "market_cap": num(cell(3)),
                       "listing_warning": "tag--def" in row[0]["tags"],
                       "ex_dividend": "tag--xd" in row[0]["tags"]})
    if len(result) < 50 or len({r["symbol"] for r in result}) != len(result):
        raise ValueError("Unrecognised/incomplete screener; previous universe retained")
    return result


def resource_summary(kind: str, body: bytes) -> dict[str, Any]:
    if kind == "prices":
        return {"fingerprint": digest(body), "bytes": len(body)}
    if kind == "universe":
        rows = parse_universe(body)
        return {"rows": len(rows), "fingerprint": digest(rows)}
    if body.startswith(b"%PDF"):
        return {"bytes": len(body), "fingerprint": digest(body), "requires_document_review": True}
    html = body.decode("utf-8", errors="replace")
    links = []
    for href, label in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        title = " ".join(unescape(re.sub(r"<[^>]+>", " ", label)).split())
        if re.search(r"download/(?:attachment|document)|\.pdf(?:\?|$)|press-release|monetary.policy", href, re.I):
            links.append({"url": urllib.parse.urljoin(ROOT, href), "title": title})
    sections = {}
    if kind == "company":
        for name in ["financials", "announcements", "ratios"]:
            match = re.search(r'id=["\']' + name + r'["\'](.*?)(?=<div class=["\']section|$)', html, re.S)
            if match:
                sections[name] = digest(" ".join(re.sub(r"<[^>]+>", " ", match[1]).split()))
    as_of = re.findall(r"As of\s+(?:[A-Za-z]{3},?\s+)?[A-Za-z]{3}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s*[AP]M", re.sub(r"<[^>]+>", " ", html), re.I)
    observation = as_of[0] if as_of else None
    semantic = {"documents": sorted(links, key=lambda x: (x["url"], x["title"])), "sections": sections}
    if kind == "market":
        table = Tables()
        table.feed(html)
        semantic["market_rows"] = [[c["text"] for c in row] for row in table.rows]
        semantic["observation"] = observation
    return {"fingerprint": digest(semantic), "observation": observation,
            "documents": semantic["documents"], "sections": sections,
            "discovery_empty": not links and kind in {"announcements", "shariah-index", "news"}}


def store_resource(db: sqlite3.Connection, url: str, kind: str, body: bytes,
                   etag: str | None = None, modified: str | None = None,
                   checked_at: str | None = None) -> dict[str, Any]:
    summary = resource_summary(kind, body)
    old = db.execute("SELECT semantic_hash,body FROM resources WHERE url=?", (url,)).fetchone()
    old_documents = resource_summary(kind, old["body"]).get("documents", []) if old and old["body"] else []
    previous_urls = {d["url"] for d in old_documents}
    checked = checked_at or stamp()
    with db:
        db.execute("""INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,NULL)
          ON CONFLICT(url) DO UPDATE SET kind=excluded.kind,body=excluded.body,
          etag=excluded.etag,modified=excluded.modified,semantic_hash=excluded.semantic_hash,
          checked_at=excluded.checked_at,downloaded_at=excluded.downloaded_at,error=NULL""",
                   (url, kind, body, etag, modified, summary["fingerprint"], checked, checked))
        if kind == "universe":
            rows = parse_universe(body)
            db.execute("DELETE FROM universe")
            db.executemany("INSERT INTO universe VALUES(?,?,?,?)",
                           [(r["symbol"], json.dumps(r), url, checked) for r in rows])
    return {"url": url, "kind": kind, "changed": not old or old["semantic_hash"] != summary["fingerprint"],
            "observation": summary.get("observation"), "rows": summary.get("rows"),
            "discovery_empty": summary.get("discovery_empty", False),
            "new_documents": [d for d in summary.get("documents", []) if d["url"] not in previous_urls][:5]}


def bucket(url: str) -> str:
    p = urllib.parse.urlparse(url)
    path = re.sub(r"/(?:company|eod|int)/[^/]+", lambda m: m[0].rsplit("/", 1)[0] + "/*", p.path)
    return p.netloc + path


def fetch(db: sqlite3.Connection, url: str, kind: str, deadline: float, force: bool) -> dict[str, Any]:
    https_url(url)
    cached = db.execute("SELECT * FROM resources WHERE url=?", (url,)).fetchone()
    if cached and cached["body"] and age(cached["checked_at"]) < TTLS[kind] and not force:
        return {"url": url, "state": "cache", "checked_at": cached["checked_at"]}
    health = db.execute("SELECT * FROM health WHERE bucket=?", (bucket(url),)).fetchone()
    if health and datetime.fromisoformat(health["retry_at"]) > now():
        return {"url": url, "state": "cooldown", "retry_at": health["retry_at"], "error": health["error"]}
    remaining = deadline - time.monotonic()
    if remaining < 1:
        return {"url": url, "state": "budget_exhausted"}
    headers = {"User-Agent": "PSX-Research-Cache/1.0", "Accept": "text/html,application/pdf,application/json"}
    if cached:
        if cached["etag"]:
            headers["If-None-Match"] = cached["etag"]
        if cached["modified"]:
            headers["If-Modified-Since"] = cached["modified"]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=min(10, remaining)) as response:
            chunks = []
            size = 0
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Run deadline reached")
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise ValueError("Resource exceeds 8 MiB limit")
                chunks.append(chunk)
            result = store_resource(db, url, kind, b"".join(chunks), response.headers.get("ETag"), response.headers.get("Last-Modified"))
        with db:
            db.execute("DELETE FROM health WHERE bucket=?", (bucket(url),))
        return {**result, "state": "downloaded", "bytes": size}
    except urllib.error.HTTPError as error:
        if error.code == 304 and cached and cached["body"]:
            with db:
                db.execute("UPDATE resources SET checked_at=?,error=NULL WHERE url=?", (stamp(), url))
            return {"url": url, "state": "not_modified"}
        code = error.code
        message = f"HTTP {code}"
    except (OSError, ValueError, TimeoutError) as error:
        code = 0
        message = f"{type(error).__name__}: {error}"
    delay = {403: 21600, 404: 86400, 429: 1800}.get(code, 900)
    retry = (now() + timedelta(seconds=delay)).isoformat()
    with db:
        db.execute("INSERT INTO health VALUES(?,?,?) ON CONFLICT(bucket) DO UPDATE SET retry_at=excluded.retry_at,error=excluded.error", (bucket(url), retry, message))
        if cached:
            db.execute("UPDATE resources SET error=? WHERE url=?", (message, url))
    return {"url": url, "state": "failed", "error": message, "retry_at": retry, "stale_cache_available": bool(cached and cached["body"])}


def load_input(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with p.open(newline="") as stream:
            return list(csv.DictReader(stream))
    return json.loads(p.read_text())


def sync_prices(db: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    """One configured bulk request for the missing window; no per-symbol crawling."""
    session = date.fromisoformat(args.session)
    if session > datetime.now(PKT).date():
        raise ValueError("Cannot fetch a future session")
    wanted = list(dict.fromkeys(symbol(s) for s in args.symbols))
    last = []
    for s in wanted:
        row = db.execute("SELECT MAX(session) FROM bars WHERE symbol=? AND provider=? AND basis=?", (s, args.provider, args.basis)).fetchone()
        if row[0] is None:
            if not args.start:
                raise ValueError(f"Cold series {s}: provide --start for the one-time history load")
            last.append(date.fromisoformat(args.start))
        else:
            last.append(date.fromisoformat(row[0]))
    if min(last) >= session and not args.recheck:
        return {"state": "already_current", "session": session.isoformat(), "network_requests": 0}
    start = min(last) - timedelta(days=7) if not args.start else min(min(last), date.fromisoformat(args.start))
    if start > session:
        raise ValueError("Start must not be after requested session")
    fields = {"since": start.isoformat(), "until": session.isoformat(), "symbols": urllib.parse.quote(",".join(wanted), safe=",")}
    if "{since}" not in args.url_template or "{until}" not in args.url_template:
        raise ValueError("Feed template must contain {since} and {until}; optionally {symbols}")
    url = https_url(args.url_template.format(**fields))
    outcome = fetch(db, url, "prices", time.monotonic() + 30, args.recheck)
    if outcome["state"] not in {"downloaded", "not_modified", "cache"}:
        return {"fetch": outcome, "imported": False}
    body = db.execute("SELECT body FROM resources WHERE url=?", (url,)).fetchone()[0]
    text = body.decode("utf-8-sig")
    records = json.loads(text) if text.lstrip().startswith("[") else list(csv.DictReader(text.splitlines()))
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("Feed must return a normalized CSV or JSON array of bar objects")
    if any(symbol(r["symbol"]) not in wanted or not start <= date.fromisoformat(r["date"]) <= session for r in records):
        raise ValueError("Feed returned an unexpected symbol/date; cache not imported")
    result = import_prices(db, records, args.provider, args.basis, args.return_basis, args.adjustments_verified, False)
    return {"fetch": outcome["state"], "window": [start.isoformat(), session.isoformat()], **result,
            "note": "Seven calendar days overlap permit corrections. Adjustment rebases require complete-series replacement."}


def import_prices(db: sqlite3.Connection, records: list[dict[str, Any]], provider: str,
                  basis: str, return_basis: str, verified: bool, replace: bool) -> dict[str, Any]:
    if not records or not provider.strip() or not basis.strip():
        raise ValueError("Nonempty records, provider and basis are required")
    prepared = {}
    groups: dict[str, set[str]] = {}
    today = datetime.now(PKT).date()
    for record in records:
        s = symbol(record["symbol"])
        session = date.fromisoformat(record["date"])
        if session > today:
            raise ValueError("Future price observations are not accepted")
        close = num(record["close"])
        adjusted = num(record["adj_close"])
        if close <= 0 or adjusted <= 0:
            raise ValueError("Prices must be positive")
        ohl = [num(record[k]) if record.get(k) not in {None, ""} else None for k in ["open", "high", "low"]]
        if s not in {"KSE100", "KSE100PR", "KMI30"} and any(v is None for v in ohl):
            raise ValueError("Stock bars need actual OHLC, not fabricated highs/lows")
        if all(v is not None for v in ohl) and not (0 < ohl[2] <= min(ohl[0], close) <= max(ohl[0], close) <= ohl[1]):
            raise ValueError(f"Invalid OHLC range: {s} {session}")
        volume = num(record["volume"]) if record.get("volume") not in {None, ""} else None
        value = num(record["value"]) if record.get("value") not in {None, ""} else None
        if (volume is not None and (volume < 0 or not volume.is_integer())) or (value is not None and value < 0):
            raise ValueError("Volume/value must be nonnegative; share volume must be integral")
        key = (s, session.isoformat())
        row = (s, session.isoformat(), provider, basis, *ohl, close, adjusted, volume, value, https_url(record["source_url"]))
        if key in prepared and prepared[key] != row:
            raise ValueError("Conflicting duplicate bars within import")
        prepared[key] = row
        groups.setdefault(s, set()).add(session.isoformat())
    for s, sessions in groups.items():
        prior = db.execute("SELECT * FROM series WHERE symbol=? AND provider=? AND basis=?", (s, provider, basis)).fetchone()
        if prior and (prior["return_basis"] != return_basis or prior["verified"] != int(verified)):
            raise ValueError("Series metadata changed: use a new basis identifier")
        old = db.execute("SELECT * FROM bars WHERE symbol=? AND provider=? AND basis=?", (s, provider, basis)).fetchall()
        changed_factor = any((s, row["session"]) in prepared and not math.isclose(row["adj_close"] / row["close"], prepared[(s, row["session"])][8] / prepared[(s, row["session"])][7], rel_tol=1e-6) for row in old)
        if (changed_factor or replace) and old and not {r["session"] for r in old}.issubset(sessions):
            raise ValueError("Adjustment rebase/replacement must cover every cached session of that series")
        if changed_factor and not replace:
            raise ValueError("Historical adjustment factors changed; re-import complete series with --replace-series")
    changed = 0
    with db:
        for s in groups:
            db.execute("INSERT OR IGNORE INTO series VALUES(?,?,?,?,?,1)", (s, provider, basis, return_basis, int(verified)))
        for row in prepared.values():
            old = db.execute("SELECT * FROM bars WHERE symbol=? AND session=? AND provider=? AND basis=?", row[:4]).fetchone()
            if old and tuple(old) == row:
                continue
            db.execute("""INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(symbol,session,provider,basis) DO UPDATE SET open=excluded.open,
              high=excluded.high,low=excluded.low,close=excluded.close,adj_close=excluded.adj_close,
              volume=excluded.volume,value=excluded.value,source_url=excluded.source_url""", row)
            db.execute("UPDATE series SET revision=revision+1 WHERE symbol=? AND provider=? AND basis=?", (row[0], provider, basis))
            changed += 1
    return {"input_rows": len(records), "changed_rows": changed, "unchanged_rows": len(prepared) - changed, "symbols": len(groups)}


def get_series(db: sqlite3.Connection, s: str, session: str, provider: str | None, basis: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    parameters: list[Any] = [s]
    query = "SELECT * FROM series WHERE symbol=?"
    for field, value in [("provider", provider), ("basis", basis)]:
        if value:
            query += f" AND {field}=?"
            parameters.append(value)
    choices = db.execute(query, parameters).fetchall()
    if len(choices) != 1:
        return None, []
    selected = dict(choices[0])
    rows = db.execute("""SELECT * FROM bars WHERE symbol=? AND provider=? AND basis=?
                         AND session<=? ORDER BY session DESC LIMIT 400""",
                      (s, selected["provider"], selected["basis"], session)).fetchall()
    return selected, [dict(row) for row in reversed(rows)]


def wilder(values: list[float], period: int = 14) -> float:
    value = statistics.mean(values[:period])
    for item in values[period:]:
        value = (value * (period - 1) + item) / period
    return value


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    last_factor = rows[-1]["adj_close"] / rows[-1]["close"]
    closes = [r["adj_close"] / last_factor for r in rows]
    true_ranges, gains, losses = [], [], []
    for i in range(1, len(rows)):
        factor = rows[i]["adj_close"] / rows[i]["close"] / last_factor
        high, low = rows[i]["high"] * factor, rows[i]["low"] * factor
        true_ranges.append(max(high - low, abs(high - closes[i - 1]), abs(low - closes[i - 1])))
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    loss, gain = wilder(losses), wilder(gains)
    rsi = (50 if gain == 0 else 100) if loss == 0 else 100 - 100 / (1 + gain / loss)
    atr = wilder(true_ranges)
    actual_values = all(r["value"] is not None for r in rows[-20:])
    values = [r["value"] if r["value"] is not None else r["close"] * r["volume"] for r in rows[-20:]]
    median_volume = statistics.median([r["volume"] for r in rows[-21:-1]])
    return {"observations": len(rows), "last_session": rows[-1]["session"], "close": rows[-1]["close"],
            "return20": (closes[-1] / closes[-21] - 1) * 100,
            "return60": (closes[-1] / closes[-61] - 1) * 100,
            "atr14": atr, "atr_percent": atr / closes[-1] * 100, "rsi14": rsi,
            "sma20": statistics.mean(closes[-20:]), "sma50": statistics.mean(closes[-50:]),
            "median_value20": statistics.median(values), "value_estimated": not actual_values,
            "volume_ratio": rows[-1]["volume"] / median_volume if median_volume else None}


def candidate(db: sqlite3.Connection, s: str, session: str, provider: str | None, basis: str | None) -> dict[str, Any]:
    chosen, rows = get_series(db, s, session, provider, basis)
    out: dict[str, Any] = {"symbol": s, "status": "DATA_REQUIRED", "reasons": []}
    if not chosen:
        out["reasons"] = ["missing_or_ambiguous_series"]
        return out
    if len(rows) < 61:
        out["reasons"] = ["fewer_than_61_observations"]
        out["observations"] = len(rows)
        return out
    if any(any(r[k] is None for k in ["high", "low", "volume"]) for r in rows):
        out["reasons"] = ["incomplete_ohlcv"]
        return out
    signature = digest([chosen, rows])
    cached = db.execute("SELECT payload FROM calculations WHERE signature=?", (signature,)).fetchone()
    computed = json.loads(cached[0]) if cached else metrics(rows)
    if not cached:
        with db:
            db.execute("INSERT OR IGNORE INTO calculations VALUES(?,?)", (signature, json.dumps(computed)))
    out.update(computed)
    out["source_url"] = rows[-1]["source_url"]
    out["provider"] = chosen["provider"]
    out["return_basis"] = chosen["return_basis"]
    blockers = []
    if rows[-1]["session"] != session:
        blockers.append("stale_for_requested_session")
    if not chosen["verified"]:
        blockers.append("adjustments_not_verified")
    penny = computed["close"] <= 50
    out["penny"] = penny
    if computed["atr_percent"] > (4 if penny else 5):
        out["reasons"].append("volatility_above_limit")
    if computed["median_value20"] < (50e6 if penny else 20e6):
        out["reasons"].append("liquidity_below_limit")
    if any(r["volume"] == 0 for r in rows[-20:]):
        out["reasons"].append("nontrading_session_in_last20")
    if penny and (computed["return20"] <= 0 or computed["return60"] <= 0):
        out["reasons"].append("penny_momentum_failed")
    benchmark = "KMI30" if not penny and db.execute("SELECT 1 FROM universe WHERE symbol=? AND payload LIKE '%\"KMI30\"%'", (s,)).fetchone() else "KSE100"
    bm, benchmark_rows = get_series(db, benchmark, session, None, None)
    by_date = {r["session"]: r for r in benchmark_rows}
    dates = [rows[i]["session"] for i in [-1, -21, -61]]
    if bm and bm["verified"] and bm["return_basis"] == chosen["return_basis"] and all(d in by_date for d in dates):
        returns = [(by_date[dates[0]]["adj_close"] / by_date[dates[i]]["adj_close"] - 1) * 100 for i in [1, 2]]
        out["relative20"], out["relative60"] = computed["return20"] - returns[0], computed["return60"] - returns[1]
        if penny and min(out["relative20"], out["relative60"]) <= 0:
            out["reasons"].append("penny_underperformed_benchmark")
    else:
        blockers.append("benchmark_comparison_unverified")
    out["data_gaps"] = blockers
    out["status"] = "REJECTED" if out["reasons"] else "DATA_REQUIRED" if blockers else "REVIEW"
    out["requires_manual_review"] = ["financials", "effective_shariah_status", "news_events", "structure_targets", "costs_and_reward_risk"]
    return out


def current_evidence(db: sqlite3.Connection, s: str, session: str) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM evidence WHERE symbol=? AND effective_from<=? AND valid_until>=? ORDER BY id DESC", (s, session, session)).fetchall()
    seen = set()
    result = []
    for row in rows:
        if row["kind"] in seen:
            continue
        seen.add(row["kind"])
        resource = db.execute("SELECT semantic_hash,error FROM resources WHERE url=?", (row["source_url"],)).fetchone()
        changed = bool(resource and row["source_hash"] and resource["semantic_hash"] != row["source_hash"])
        result.append({"kind": row["kind"], "payload": json.loads(row["payload"]), "source_url": row["source_url"],
                       "checked_at": row["checked_at"], "valid_until": row["valid_until"], "review_due": changed})
    return result


def screen(db: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    session = date.fromisoformat(args.session).isoformat()
    if date.fromisoformat(session) > datetime.now(PKT).date():
        raise ValueError("Requested session is in the future")
    universe = [json.loads(r[0]) for r in db.execute("SELECT payload FROM universe")]
    if args.mode == "quick":
        symbols = json.loads(db.execute("SELECT value FROM settings WHERE key='watchlist'").fetchone()[0])
    else:
        symbols = [r["symbol"] for r in universe if not r["listing_warning"] and r["pe"] > 0 and
                   (({"KSE100", "KMI30"} & set(r["indices"]) and r["price"] * r["avg30_volume"] >= 20e6) or
                    ("ALLSHR" in r["indices"] and r["price"] <= 50 and r["price"] * r["avg30_volume"] >= 50e6))]
    results = [candidate(db, s, session, args.provider, args.basis) for s in symbols]
    lookup = {r["symbol"]: r for r in universe}
    for row in results:
        listing = lookup.get(row["symbol"], {})
        row["indices"] = listing.get("indices", [])
        if listing.get("listing_warning"):
            row["reasons"].append("listing_warning")
            row["status"] = "REJECTED"
        elif not listing:
            row.setdefault("data_gaps", []).append("universe_membership_unverified")
            if row["status"] == "REVIEW":
                row["status"] = "DATA_REQUIRED"
        row["evidence"] = current_evidence(db, row["symbol"], datetime.now(PKT).date().isoformat())
    results.sort(key=lambda r: ({"REVIEW": 0, "DATA_REQUIRED": 1, "REJECTED": 2}[r["status"]], -r.get("return20", -1e9)))
    return {"mode": args.mode, "session": session, "analysis_at": stamp(), "source_universe_rows": len(universe),
            "screened": len(results), "status_counts": {k: sum(r["status"] == k for r in results) for k in ["REVIEW", "DATA_REQUIRED", "REJECTED"]},
            "source_universe_checked_at": db.execute("SELECT MIN(observed_at) FROM universe").fetchone()[0],
            "displayed": min(len(results), args.limit), "results": results[:args.limit],
            "note": "Technical triage only. REVIEW is not BUY. Confirm session completion, disclosures, Shariah, costs and execution separately."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("PSX_CACHE_DIR", str(Path.home() / ".cache" / "psx-investing"))) / "research.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    watch = sub.add_parser("watchlist")
    watch.add_argument("--set", nargs="+")
    refresh = sub.add_parser("refresh")
    refresh.add_argument("--mode", choices=["quick", "full"], default="quick")
    refresh.add_argument("--seconds", type=int)
    refresh.add_argument("--max-requests", type=int)
    refresh.add_argument("--force", action="store_true", help="Bypass positive TTL, never endpoint cooldowns")
    seed = sub.add_parser("cache-file")
    seed.add_argument("--url", required=True)
    seed.add_argument("--kind", choices=TTLS, required=True)
    seed.add_argument("--file", type=Path, required=True)
    seed.add_argument("--checked-at", required=True, help="Actual retrieval time, not price observation time")
    track = sub.add_parser("track")
    track.add_argument("--url", required=True)
    track.add_argument("--kind", choices=TTLS, required=True)
    imp = sub.add_parser("import-prices")
    imp.add_argument("--file", required=True)
    imp.add_argument("--provider", required=True)
    imp.add_argument("--basis", required=True)
    imp.add_argument("--return-basis", choices=["price", "total_return"], required=True)
    imp.add_argument("--adjustments-verified", action="store_true")
    imp.add_argument("--replace-series", action="store_true")
    sync = sub.add_parser("sync-prices")
    sync.add_argument("--url-template", required=True)
    sync.add_argument("--symbols", nargs="+", required=True)
    sync.add_argument("--session", required=True)
    sync.add_argument("--start")
    sync.add_argument("--provider", required=True)
    sync.add_argument("--basis", required=True)
    sync.add_argument("--return-basis", choices=["price", "total_return"], required=True)
    sync.add_argument("--adjustments-verified", action="store_true")
    sync.add_argument("--recheck", action="store_true")
    calc = sub.add_parser("screen")
    calc.add_argument("--mode", choices=["quick", "full"], default="quick")
    calc.add_argument("--session", required=True)
    calc.add_argument("--provider")
    calc.add_argument("--basis")
    calc.add_argument("--limit", type=int, default=8)
    evidence = sub.add_parser("record-evidence")
    evidence.add_argument("--file", required=True)
    call = sub.add_parser("record-calls")
    call.add_argument("--file", required=True)
    sub.add_parser("last-calls")
    args = parser.parse_args()
    db = connect(args.db)
    try:
        if args.command == "status":
            result = {"database": str(args.db), "universe_rows": db.execute("SELECT COUNT(*) FROM universe").fetchone()[0],
                      "price_rows": db.execute("SELECT COUNT(*) FROM bars").fetchone()[0],
                      "series": db.execute("SELECT COUNT(*) FROM series").fetchone()[0],
                      "resources": db.execute("SELECT COUNT(*) FROM resources WHERE body IS NOT NULL").fetchone()[0],
                      "latest_cached_price_session": db.execute("SELECT MAX(session) FROM bars").fetchone()[0],
                      "watchlist": json.loads(db.execute("SELECT value FROM settings WHERE key='watchlist'").fetchone()[0]),
                      "endpoint_cooldowns": [dict(r) for r in db.execute("SELECT * FROM health WHERE retry_at>?", (stamp(),))]}
        elif args.command == "watchlist":
            if args.set:
                with db:
                    db.execute("UPDATE settings SET value=? WHERE key='watchlist'", (json.dumps(list(dict.fromkeys(symbol(s) for s in args.set))),))
            result = {"watchlist": json.loads(db.execute("SELECT value FROM settings WHERE key='watchlist'").fetchone()[0])}
        elif args.command == "cache-file":
            checked = datetime.fromisoformat(args.checked_at)
            if checked.tzinfo is None or checked > now():
                raise ValueError("checked-at needs a timezone and cannot be in the future")
            result = store_resource(db, https_url(args.url), args.kind, args.file.read_bytes(), checked_at=checked.astimezone(timezone.utc).isoformat())
        elif args.command == "track":
            with db:
                db.execute("INSERT INTO resources(url,kind) VALUES(?,?) ON CONFLICT(url) DO UPDATE SET kind=excluded.kind", (https_url(args.url), args.kind))
            result = {"tracked": args.url, "kind": args.kind}
        elif args.command == "refresh":
            budget = args.seconds if args.seconds is not None else (45 if args.mode == "quick" else 120)
            request_limit = args.max_requests if args.max_requests is not None else (8 if args.mode == "quick" else 16)
            if not 1 <= budget <= 180 or not 1 <= request_limit <= 30:
                raise ValueError("Budget must be 1–180 seconds and requests 1–30")
            base = [(ROOT + "/indices", "market"), (ROOT + "/screener", "universe"),
                    (ROOT + "/announcements/companies", "announcements"), (ROOT + "/announcements/psx", "shariah-index"),
                    ("https://www.sbp.org.pk/Finc/Govst.asp", "macro")]
            watchlist = json.loads(db.execute("SELECT value FROM settings WHERE key='watchlist'").fetchone()[0])
            sources = base + [(ROOT + "/company/" + s, "company") for s in watchlist[:5 if args.mode == "quick" else 8]]
            sources += [(r["url"], r["kind"]) for r in db.execute("SELECT url,kind FROM resources ORDER BY checked_at")]
            sources = list(dict.fromkeys(sources))
            deadline, calls, results = time.monotonic() + budget, 0, []
            for url, kind in sources:
                if calls >= request_limit or time.monotonic() >= deadline:
                    break
                response = fetch(db, url, kind, deadline, args.force)
                calls += int(response["state"] in {"downloaded", "not_modified", "failed"})
                results.append(response)
            result = {"mode": args.mode, "network_requests": calls, "cache_hits": sum(r["state"] == "cache" for r in results),
                      "changed": [r for r in results if r.get("changed")],
                      "issues": [r for r in results if r["state"] in {"failed", "cooldown", "budget_exhausted"} or r.get("discovery_empty")],
                      "not_processed": len(sources) - len(results),
                      "note": "Downloaded resources do not make old market observations fresh. Price histories update through incremental import-prices."}
        elif args.command == "import-prices":
            result = import_prices(db, load_input(args.file), args.provider, args.basis, args.return_basis, args.adjustments_verified, args.replace_series)
        elif args.command == "sync-prices":
            result = sync_prices(db, args)
        elif args.command == "screen":
            if not 1 <= args.limit <= 500:
                raise ValueError("limit must be 1–500")
            result = screen(db, args)
        elif args.command == "record-evidence":
            rows = load_input(args.file)
            prepared = []
            for r in rows:
                checked = datetime.fromisoformat(r["checked_at"])
                start, end = date.fromisoformat(r["effective_from"]), date.fromisoformat(r["valid_until"])
                if checked.tzinfo is None or checked > now() or end < start:
                    raise ValueError("Invalid evidence dates")
                source = https_url(r["source_url"])
                resource = db.execute("SELECT semantic_hash FROM resources WHERE url=?", (source,)).fetchone()
                prepared.append((symbol(r["symbol"]), r["kind"], json.dumps(r["payload"]), source,
                                 resource[0] if resource else None, checked.isoformat(), start.isoformat(), end.isoformat()))
            with db:
                db.executemany("INSERT INTO evidence(symbol,kind,payload,source_url,source_hash,checked_at,effective_from,valid_until) VALUES(?,?,?,?,?,?,?,?)", prepared)
            result = {"recorded": len(prepared)}
        elif args.command == "record-calls":
            changes, prepared = [], []
            for r in load_input(args.file):
                s = symbol(r["symbol"])
                if r["horizon"] not in HORIZONS or r["call"] not in CALLS:
                    raise ValueError("Invalid horizon or call")
                if date.fromisoformat(r["as_of_session"]) > datetime.now(PKT).date():
                    raise ValueError("Calls cannot be recorded for a future session")
                if r["call"] == "BUY" and not all(r.get("checks", {}).get(k) is True for k in ["price_fresh", "fundamentals", "shariah", "events", "liquidity", "risk_reward", "adjustments"]):
                    raise ValueError("BUY requires explicit completion of every evidence gate")
                semantic = {k: v for k, v in r.items() if k not in {"checked_at", "as_of_session", "quote", "sources", "commentary"}}
                fingerprint = digest(semantic)
                old = db.execute("SELECT * FROM calls WHERE symbol=? AND horizon=? ORDER BY id DESC LIMIT 1", (s, r["horizon"])).fetchone()
                if not old or old["semantic_hash"] != fingerprint:
                    previous = json.loads(old["payload"]) if old else {}
                    old_semantic = {k: v for k, v in previous.items() if k not in {"checked_at", "as_of_session", "quote", "sources", "commentary"}}
                    changes.append({"symbol": s, "horizon": r["horizon"], "previous": previous.get("call"), "call": r["call"],
                                    "changed_fields": sorted(k for k in set(semantic) | set(old_semantic) if semantic.get(k) != old_semantic.get(k))})
                prepared.append((s, r["horizon"], json.dumps(r), fingerprint, stamp()))
            with db:
                db.executemany("INSERT INTO calls(symbol,horizon,payload,semantic_hash,recorded_at) VALUES(?,?,?,?,?)", prepared)
            result = {"reviewed": len(prepared), "changed_calls": changes, "unchanged": len(prepared) - len(changes)}
        else:
            result = {"calls": [json.loads(r[0]) for r in db.execute("SELECT payload FROM calls WHERE id IN (SELECT MAX(id) FROM calls GROUP BY symbol,horizon)")]}
        print(json.dumps(result, indent=2, allow_nan=False))
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
