#!/usr/bin/env python3
"""claude-cost: per-session cost for Claude Code.

  statusline   read Claude Code's statusLine JSON on stdin, print a cost line
  report       summarize past sessions from ~/.claude/projects/**/*.jsonl

Single file, Python 3.8+ standard library only. MIT licensed.
"""
import argparse, datetime as dt, glob, json, os, re, sys

# ---------------------------------------------------------------------------
# Pricing (USD per million tokens).
# Source: https://docs.claude.com/en/docs/about-claude/pricing  (retrieved 2026-10-26)
# Columns: input, 5m cache write, 1h cache write, cache read (hit/refresh), output.
# Override: set CLAUDE_COST_PRICING=/path/to/pricing.json (same shape; merged over these),
# or drop ~/.claude/claude-cost-pricing.json.
# ---------------------------------------------------------------------------
PRICING_SOURCE = "https://docs.claude.com/en/docs/about-claude/pricing"
PRICING_DATE = "2026-10-26"
PRICING = {
    "fable-5-1":  {"input": 10,   "cache_write_5m": 12.5,  "cache_write_1h": 20,   "cache_read": 0.25, "output": 50},
    "mythos-5-1": {"input": 10,   "cache_write_5m": 12.5,  "cache_write_1h": 20,   "cache_read": 0.25, "output": 50},
    "fable-5":    {"input": 10,   "cache_write_5m": 12.5,  "cache_write_1h": 20,   "cache_read": 1.0,  "output": 50},
    "mythos-5":   {"input": 10,   "cache_write_5m": 12.5,  "cache_write_1h": 20,   "cache_read": 1.0,  "output": 50},
    "opus-5-5":   {"input": 4,    "cache_write_5m": 5,     "cache_write_1h": 8,    "cache_read": 0.20, "output": 20,
                   "fast": {"input": 8, "output": 40}},
    "opus-5":     {"input": 5,    "cache_write_5m": 6.25,  "cache_write_1h": 10,   "cache_read": 0.50, "output": 25,
                   "fast": {"input": 10, "output": 50}},
    "opus-4-8":   {"input": 5,    "cache_write_5m": 6.25,  "cache_write_1h": 10,   "cache_read": 0.50, "output": 25,
                   "fast": {"input": 10, "output": 50}},
    "opus-4-7":   {"input": 5,    "cache_write_5m": 6.25,  "cache_write_1h": 10,   "cache_read": 0.50, "output": 25},
    "opus-4-6":   {"input": 5,    "cache_write_5m": 6.25,  "cache_write_1h": 10,   "cache_read": 0.50, "output": 25},
    "opus-4-5":   {"input": 5,    "cache_write_5m": 6.25,  "cache_write_1h": 10,   "cache_read": 0.50, "output": 25},
    "opus-4-1":   {"input": 15,   "cache_write_5m": 18.75, "cache_write_1h": 30,   "cache_read": 1.50, "output": 75},
    "opus-4":     {"input": 15,   "cache_write_5m": 18.75, "cache_write_1h": 30,   "cache_read": 1.50, "output": 75},
    "sonnet-5-5": {"input": 2,    "cache_write_5m": 2.5,   "cache_write_1h": 4,    "cache_read": 0.10, "output": 10},
    "sonnet-5":   {"input": 2,    "cache_write_5m": 2.5,   "cache_write_1h": 4,    "cache_read": 0.20, "output": 10},
    "sonnet-4-6": {"input": 3,    "cache_write_5m": 3.75,  "cache_write_1h": 6,    "cache_read": 0.30, "output": 15},
    "sonnet-4-5": {"input": 3,    "cache_write_5m": 3.75,  "cache_write_1h": 6,    "cache_read": 0.30, "output": 15},
    "sonnet-4":   {"input": 3,    "cache_write_5m": 3.75,  "cache_write_1h": 6,    "cache_read": 0.30, "output": 15},
    # Haiku 5.5 is priced by prompt length: prompts over 100k tokens (input+cache) use "long".
    "haiku-5-5":  {"input": 0.10, "cache_write_5m": 0.125, "cache_write_1h": 0.20, "cache_read": 0.01, "output": 0.50,
                   "long_threshold": 100000,
                   "long": {"input": 0.50, "cache_write_5m": 0.625, "cache_write_1h": 1.0, "cache_read": 0.05, "output": 2.50}},
    "haiku-4-5":  {"input": 1,    "cache_write_5m": 1.25,  "cache_write_1h": 2,    "cache_read": 0.10, "output": 5},
    "haiku-3-5":  {"input": 0.80, "cache_write_5m": 1,     "cache_write_1h": 1.6,  "cache_read": 0.08, "output": 4},
}

def load_pricing():
    table = {k: dict(v) for k, v in PRICING.items()}
    for path in (os.path.expanduser("~/.claude/claude-cost-pricing.json"), os.environ.get("CLAUDE_COST_PRICING")):
        if path and os.path.isfile(path):
            with open(path) as f:
                for k, v in json.load(f).items():
                    table[normalize_model(k) or k] = {**table.get(normalize_model(k) or k, {}), **v}
    return table

def normalize_model(model):
    """'claude-opus-4-5-20251101[1m]' / 'us.anthropic.claude-sonnet-4-5-v1:0' -> 'opus-4-5'."""
    if not model:
        return None
    m = model.lower().split("/")[-1]
    m = re.sub(r"\[.*?\]", "", m)
    m = re.sub(r"^.*?claude-", "", m)
    m = re.sub(r"(-v\d+(:\d+)?|@\d+|-\d{8}|-latest)+$", "", m)
    # older naming: claude-3-5-haiku -> haiku-3-5
    old = re.match(r"^(\d(?:-\d)?)-(opus|sonnet|haiku)$", m)
    if old:
        m = f"{old.group(2)}-{old.group(1)}"
    return m

def price_for(model, table):
    """Return (rates, matched_key) or (None, None) for unknown models."""
    key = normalize_model(model)
    if not key:
        return None, None
    if key in table:
        return table[key], key
    # longest prefix match, e.g. 'opus-4-5-foo' -> 'opus-4-5'
    for k in sorted(table, key=len, reverse=True):
        if key.startswith(k + "-"):
            return table[k], k
    return None, None

# ---------------------------------------------------------------------------
# Usage + cost
# ---------------------------------------------------------------------------
FIELDS = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")

def split_usage(u):
    """Map an Anthropic usage object to our five buckets.

    cache_creation_input_tokens is split via usage.cache_creation.ephemeral_{5m,1h}_input_tokens
    when present; otherwise all cache writes are treated as 5-minute writes.
    """
    u = u or {}
    cw_total = int(u.get("cache_creation_input_tokens") or 0)
    cc = u.get("cache_creation") or {}
    w5 = int(cc.get("ephemeral_5m_input_tokens") or 0)
    w1 = int(cc.get("ephemeral_1h_input_tokens") or 0)
    if w5 + w1 < cw_total:          # unsplit remainder -> 5m (the API default TTL)
        w5 += cw_total - (w5 + w1)
    return {
        "input": int(u.get("input_tokens") or 0),
        "cache_write_5m": w5,
        "cache_write_1h": w1,
        "cache_read": int(u.get("cache_read_input_tokens") or 0),
        "output": int(u.get("output_tokens") or 0),
        "web_search": int(((u.get("server_tool_use") or {}).get("web_search_requests")) or 0),
    }

WEB_SEARCH_USD = 10 / 1000  # $10 per 1,000 searches (same pricing page)

def cost_of(tokens, rates, fast=False):
    if rates is None:
        return None
    r = dict(rates)
    thr = r.get("long_threshold")
    if thr and tokens["input"] + tokens["cache_write_5m"] + tokens["cache_write_1h"] + tokens["cache_read"] > thr:
        r.update(r.get("long", {}))
    if fast and "fast" in r:  # fast-mode input/output; cache multipliers scale off fast input
        f = r["fast"]; mult = f["input"] / r["input"]
        r = {**r, "input": f["input"], "output": f["output"],
             "cache_write_5m": r["cache_write_5m"] * mult, "cache_write_1h": r["cache_write_1h"] * mult,
             "cache_read": r["cache_read"] * mult}
    usd = sum(tokens[k] * r[k] for k in FIELDS) / 1e6
    return usd + tokens.get("web_search", 0) * WEB_SEARCH_USD

def iter_jsonl(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue  # partially-written last line, etc.
    except OSError:
        return

class Session:
    def __init__(self, sid):
        self.id = sid
        self.project = None
        self.first = self.last = None
        self.tokens = {k: 0 for k in FIELDS + ("web_search",)}
        self.cost = 0.0
        self.models = {}           # model -> cost
        self.unknown_models = {}   # model -> tokens not priced
        self.messages = 0
        self.sidechain_cost = 0.0

def analyze(paths, table=None, since=None):
    """Parse transcript files into {session_id: Session}, deduping API responses."""
    table = table or load_pricing()
    seen = {}      # dedupe key -> (session, tokens, model, fast, sidechain)
    meta = {}
    for path in paths:
        for e in iter_jsonl(path):
            if e.get("type") != "assistant":
                continue
            msg = e.get("message") or {}
            usage = msg.get("usage")
            model = msg.get("model")
            if not usage or model == "<synthetic>":
                continue
            ts = e.get("timestamp")
            if since and ts and ts < since:
                continue
            sid = e.get("sessionId") or os.path.splitext(os.path.basename(path))[0]
            # Streaming writes one line per content block, all sharing message.id/requestId
            # and repeating the usage. Keep one per (message.id, requestId); later lines win
            # since they carry the final output_tokens.
            key = (msg.get("id"), e.get("requestId"))
            if key == (None, None):
                key = ("uuid", e.get("uuid") or id(e))
            tokens = split_usage(usage)
            fast = (usage.get("speed") == "fast")
            prev = seen.get(key)
            if prev and prev[1]["output"] > tokens["output"]:
                tokens = prev[1]
            seen[key] = (sid, tokens, model, fast, bool(e.get("isSidechain")))
            m = meta.setdefault(sid, {"project": None, "first": ts, "last": ts})
            m["project"] = m["project"] or e.get("cwd")
            if ts:
                m["first"] = min(filter(None, [m["first"], ts]))
                m["last"] = max(filter(None, [m["last"], ts]))
    sessions = {}
    for sid, tokens, model, fast, side in seen.values():
        s = sessions.get(sid) or sessions.setdefault(sid, Session(sid))
        s.messages += 1
        for k in s.tokens:
            s.tokens[k] += tokens.get(k, 0)
        rates, _ = price_for(model, table)
        c = cost_of(tokens, rates, fast)
        if c is None:
            s.unknown_models[model] = s.unknown_models.get(model, 0) + sum(tokens[k] for k in FIELDS)
            continue
        s.cost += c
        s.models[model] = s.models.get(model, 0) + c
        if side:
            s.sidechain_cost += c
    for sid, s in sessions.items():
        m = meta.get(sid, {})
        s.project, s.first, s.last = m.get("project"), m.get("first"), m.get("last")
    return sessions

def session_files(transcript_path):
    """Main transcript plus any subagent transcripts stored beside it (<session>/subagents/*.jsonl)."""
    files = [transcript_path]
    base = os.path.splitext(transcript_path)[0]
    files += sorted(glob.glob(os.path.join(base, "subagents", "*.jsonl")))
    return files

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def color_enabled():
    return not os.environ.get("NO_COLOR")

def c(code, s):
    return f"\033[{code}m{s}\033[0m" if color_enabled() else s

def fmt_tok(n):
    if n >= 1_000_000: return f"{n/1e6:.1f}M"
    if n >= 1_000: return f"{n/1e3:.1f}k"
    return str(n)

def fmt_usd(x):
    if x is None: return "n/a"
    return f"${x:.4f}" if x < 0.01 else f"${x:.2f}"

def statusline(data, table=None):
    model = data.get("model") or {}
    name = model.get("display_name") or model.get("id") or "?"
    tp = data.get("transcript_path")
    s = None
    if tp and os.path.isfile(tp):
        sessions = analyze(session_files(tp), table)
        s = sessions.get(data.get("session_id")) or (next(iter(sessions.values())) if sessions else None)
    cc_cost = (data.get("cost") or {}).get("total_cost_usd")
    parts = [c("36", f"[{name}]")]
    if s:
        t = s.tokens
        parts.append(c("1;33", fmt_usd(s.cost)))
        if cc_cost is not None:
            parts.append(c("2", f"(cc {fmt_usd(cc_cost)})"))
        parts.append(f"in {fmt_tok(t['input'])} · out {fmt_tok(t['output'])} · "
                     f"cw {fmt_tok(t['cache_write_5m'] + t['cache_write_1h'])} · cr {fmt_tok(t['cache_read'])}")
        if s.unknown_models:
            parts.append(c("31", "?unpriced model"))
    elif cc_cost is not None:
        parts.append(c("1;33", fmt_usd(cc_cost)) + c("2", " (cc)"))
    else:
        parts.append(c("2", "$0.00"))
    return " │ ".join(parts)

def report(sessions, limit=None):
    rows = sorted(sessions.values(), key=lambda s: s.last or "", reverse=True)
    if limit:
        rows = rows[:limit]
    hdr = f"{'last activity':<16}  {'session':<8}  {'project':<22} {'model':<18} {'input':>7} {'output':>7} {'c.write':>8} {'c.read':>8} {'cost':>9}"
    out = [c("1", hdr), "─" * len(hdr)]
    tot = {k: 0 for k in FIELDS}; total = 0.0; unknown = False
    for s in rows:
        when = (s.last or "")[:16].replace("T", " ")
        if s.last:
            try:
                when = dt.datetime.fromisoformat(s.last.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
        proj = os.path.basename((s.project or "").rstrip("/")) or "-"
        model = max(s.models, key=s.models.get) if s.models else (next(iter(s.unknown_models), "-"))
        model = normalize_model(model) or model
        if len(s.models) > 1: model += f" +{len(s.models)-1}"
        flag = c("31", "*") if s.unknown_models else " "
        t = s.tokens
        out.append(f"{when:<16}  {s.id[:8]:<8}  {proj[:22]:<22} {model[:18]:<18} {fmt_tok(t['input']):>7} {fmt_tok(t['output']):>7} "
                   f"{fmt_tok(t['cache_write_5m']+t['cache_write_1h']):>8} {fmt_tok(t['cache_read']):>8} {c('33', f'{fmt_usd(s.cost):>9}')}{flag}")
        for k in FIELDS: tot[k] += t[k]
        total += s.cost; unknown |= bool(s.unknown_models)
    out.append("─" * len(hdr))
    out.append(c("1", f"{'TOTAL':<16}  {len(rows):<8}  {'sessions':<22} {'':<18} {fmt_tok(tot['input']):>7} {fmt_tok(tot['output']):>7} "
                      f"{fmt_tok(tot['cache_write_5m']+tot['cache_write_1h']):>8} {fmt_tok(tot['cache_read']):>8} {fmt_usd(total):>9}"))
    if unknown:
        out.append(c("31", "* includes tokens from a model missing from the pricing table (not counted); add it via CLAUDE_COST_PRICING"))
    out.append(c("2", f"API list prices from {PRICING_SOURCE} ({PRICING_DATE}). Estimate only; see README."))
    return "\n".join(out)

def find_transcripts(root):
    return sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))

def main(argv=None):
    p = argparse.ArgumentParser(prog="claude-cost", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("statusline", help="read statusLine JSON on stdin (default when stdin is piped)")
    r = sub.add_parser("report", help="per-session costs from past transcripts")
    r.add_argument("-n", "--last", type=int, default=10, help="show the N most recent sessions (default 10, 0=all)")
    r.add_argument("--today", action="store_true", help="only usage since local midnight")
    r.add_argument("--days", type=int, help="only usage from the last N days")
    r.add_argument("--dir", default=os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")), "projects"),
                   help="transcripts root (default ~/.claude/projects)")
    r.add_argument("--json", action="store_true", help="machine-readable output")
    sub.add_parser("pricing", help="print the active pricing table")
    a = p.parse_args(argv)
    cmd = a.cmd or ("statusline" if not sys.stdin.isatty() else None)
    if cmd == "statusline":
        try:
            data = json.load(sys.stdin)
        except ValueError:
            data = {}
        try:
            print(statusline(data))
        except Exception as ex:  # never blank the statusline
            print(f"claude-cost: {ex}")
        return 0
    if cmd == "pricing":
        print(json.dumps({"source": PRICING_SOURCE, "retrieved": PRICING_DATE, "usd_per_mtok": load_pricing()}, indent=2))
        return 0
    if cmd == "report":
        since = None
        if a.today:
            since = dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        elif a.days:
            since = dt.datetime.now().astimezone() - dt.timedelta(days=a.days)
        since_s = since.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") if since else None
        sessions = analyze(find_transcripts(a.dir), since=since_s)
        if a.json:
            rows = [{"session_id": s.id, "project": s.project, "first": s.first, "last": s.last,
                     "cost_usd": round(s.cost, 6), "sidechain_cost_usd": round(s.sidechain_cost, 6),
                     "tokens": s.tokens, "models": s.models, "unpriced_models": s.unknown_models}
                    for s in sorted(sessions.values(), key=lambda s: s.last or "", reverse=True)]
            print(json.dumps(rows[: a.last or None], indent=2))
        else:
            print(report(sessions, a.last or None))
        return 0
    p.print_help()
    return 1

if __name__ == "__main__":
    sys.exit(main())
