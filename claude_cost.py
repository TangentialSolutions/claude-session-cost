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
        self.usage = Usage()

# ---------------------------------------------------------------------------
# Usage tracking (skills, MCP, rules/memory files, Bash commands)
# ---------------------------------------------------------------------------
WRAPPERS = {"sudo", "env", "time", "nohup", "nice", "exec", "command", "builtin", "xargs", "timeout", "stdbuf"}
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

def bash_base_commands(cmd):
    """Base command(s) of a shell command line.

    'cd app && FOO=1 sudo -E npm test | tee x' -> ['npm', 'tee'].  Splits on && || ; | and newlines,
    skips cd/pushd/popd/export/source segments, env assignments, and wrappers like sudo/env/time
    (with their flags), and strips paths (/usr/bin/git -> git).
    """
    import shlex
    out = []
    try:
        lex = shlex.shlex((cmd or "").replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
        lex.whitespace_split = True
        lex.commenters = "#"
        toks = list(lex)
    except ValueError:  # unbalanced quotes: fall back to a naive split
        toks = re.sub(r"(&&|\|\||[;|()])", r" \1 ", cmd or "").split()
    segs, cur = [], []
    for t in toks:
        if t and set(t) <= set(";&|()"):
            segs.append(cur); cur = []
        else:
            cur.append(t)
    segs.append(cur)
    for words in segs:
        i = 0
        while i < len(words):
            w = words[i]
            if ASSIGN.match(w) or w in ("(", "{", "!"):
                i += 1
            elif w in WRAPPERS:
                i += 1
                while i < len(words) and (words[i].startswith("-") or (w == "timeout" and re.match(r"^\d", words[i]))):
                    i += 1
            else:
                break
        if i >= len(words):
            continue
        base = os.path.basename(words[i].lstrip("({"))
        if base and base not in ("cd", "pushd", "popd", "export", "source", ".", "true", ":"):
            out.append(base)
    return out

def est_tokens(content):
    """Rough token estimate for tool_result content: ~4 characters per token (images ~1.6k each)."""
    if content is None:
        return 0
    if isinstance(content, str):
        return (len(content) + 3) // 4
    n = 0
    for b in content if isinstance(content, list) else [content]:
        if isinstance(b, dict):
            if b.get("type") == "image":
                n += 1600
            else:
                n += est_tokens(b.get("text") or b.get("content") or "")
        else:
            n += est_tokens(str(b))
    return n

RULE_NAME = re.compile(r"(^|/)(CLAUDE(\.local)?\.md|AGENTS\.md)$|/\.claude/(rules|memory|memories)/|/memory/.*\.md$", re.I)
REMINDER_FILE = re.compile(r"Contents of (\S+?\.md)\b")
IMPORT_RE = re.compile(r"(?:^|\s)@((?:~|\.{0,2})/?[\w./-]+\.md)\b")
CMD_RE = re.compile(r"<command-name>\s*/?([^<\s]+)\s*</command-name>")

class Usage:
    def __init__(self):
        self.skills = {}        # name -> count
        self.slash = {}         # /command -> count
        self.mcp = {}           # "server/tool" -> {"calls", "result_tokens_est", "result_cost_est", "output_tokens_est"}
        self.tools = {}         # tool name -> count (all tools)
        self.bash = {}          # base command -> count
        self.rules = {}         # path -> set(how)

    def add(self, other):
        for attr in ("skills", "slash", "tools", "bash"):
            d = getattr(self, attr)
            for k, v in getattr(other, attr).items():
                d[k] = d.get(k, 0) + v
        for k, v in other.mcp.items():
            d = self.mcp.setdefault(k, {"calls": 0, "result_tokens_est": 0, "result_cost_est": 0.0, "output_tokens_est": 0.0})
            for f in d:
                d[f] += v[f]
        for k, v in other.rules.items():
            self.rules.setdefault(k, set()).update(v)

    def to_json(self):
        return {"skills": self.skills, "slash_commands": self.slash, "tools": self.tools, "bash_commands": self.bash,
                "mcp": {k: {**v, "result_cost_est": round(v["result_cost_est"], 6),
                            "output_tokens_est": round(v["output_tokens_est"])} for k, v in self.mcp.items()},
                "rules_files": {k: sorted(v) for k, v in self.rules.items()},
                "_note": "mcp *_est fields are estimates (tool_result chars/4 priced at the model's base input rate; "
                         "issuing turn's output split evenly across its tool calls)"}

def _texts(content):
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    yield b.get("text") or ""
                elif b.get("type") == "tool_result":
                    yield from _texts(b.get("content"))

def analyze(paths, table=None, since=None):
    """Parse transcript files into {session_id: Session}, deduping API responses."""
    table = table or load_pricing()
    seen = {}       # dedupe key -> (session, tokens, model, fast, sidechain)
    calls = {}      # tool_use id -> (sid, name, input, msg key)
    blocks_per_msg = {}
    results = {}    # tool_use id -> est tokens
    meta = {}
    extra = {}      # sid -> Usage (slash commands, rules)
    for path in paths:
        for e in iter_jsonl(path):
            ts = e.get("timestamp")
            if since and ts and ts < since:
                continue
            sid = e.get("sessionId") or os.path.splitext(os.path.basename(path))[0]
            u = extra.setdefault(sid, Usage())
            msg = e.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            # --- rules / memory files and slash commands (any entry type) ---
            att = e.get("attachment") or {}
            if isinstance(att, dict) and att.get("path") and ("memory" in str(att.get("type", "")).lower() or RULE_NAME.search(att["path"])):
                u.rules.setdefault(att["path"], set()).add("attachment:" + str(att.get("type")))
            for t in _texts(content):
                for p in REMINDER_FILE.findall(t):
                    u.rules.setdefault(p, set()).add("system-reminder")
                if e.get("type") == "user":
                    for c in CMD_RE.findall(t):
                        u.slash["/" + c] = u.slash.get("/" + c, 0) + 1
                    if not t.lstrip().startswith("<"):
                        for p in IMPORT_RE.findall(t):
                            u.rules.setdefault(p, set()).add("@-mention")
            if e.get("type") == "user" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                        results[b["tool_use_id"]] = est_tokens(b.get("content"))
            if e.get("type") != "assistant":
                continue
            usage = msg.get("usage")
            model = msg.get("model")
            if not usage or model == "<synthetic>":
                continue
            # Streaming writes one line per content block, all sharing message.id/requestId
            # and repeating the usage. Keep one per (message.id, requestId); later lines win
            # since they carry the final output_tokens.
            key = (msg.get("id"), e.get("requestId"))
            if key == (None, None):
                key = ("uuid", e.get("uuid") or id(e))
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tid = b.get("id") or f"{key}:{len(calls)}"
                    if tid not in calls:
                        calls[tid] = (sid, b.get("name") or "?", b.get("input") or {}, key)
                        blocks_per_msg[key] = blocks_per_msg.get(key, 0) + 1
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
    # --- tool calls ---
    for tid, (sid, name, inp, key) in calls.items():
        s = sessions.get(sid) or sessions.setdefault(sid, Session(sid))
        u = s.usage
        u.tools[name] = u.tools.get(name, 0) + 1
        if name == "Skill":
            sk = inp.get("skill") or inp.get("command") or inp.get("name") or "?"
            u.skills[sk] = u.skills.get(sk, 0) + 1
        elif name == "Bash":
            for b in bash_base_commands(inp.get("command", "")):
                u.bash[b] = u.bash.get(b, 0) + 1
        elif name.startswith("mcp__"):
            parts = name.split("__", 2)
            label = f"{parts[1]}/{parts[2]}" if len(parts) == 3 else name
            d = u.mcp.setdefault(label, {"calls": 0, "result_tokens_est": 0, "result_cost_est": 0.0, "output_tokens_est": 0.0})
            d["calls"] += 1
            rt = results.get(tid, 0)
            d["result_tokens_est"] += rt
            msg_info = seen.get(key)
            if msg_info:
                rates, _ = price_for(msg_info[2], table)
                if rates:
                    d["result_cost_est"] += rt * rates["input"] / 1e6
                d["output_tokens_est"] += msg_info[1]["output"] / max(1, blocks_per_msg.get(key, 1))
        if name in ("Read", "Edit", "Write", "MultiEdit"):
            fp = inp.get("file_path") or ""
            if RULE_NAME.search(fp):
                u.rules.setdefault(fp, set()).add(f"{name} tool")
    for sid, x in extra.items():
        if sid in sessions:
            sessions[sid].usage.add(x)
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
        nt = sum(s.usage.tools.values()); nm = sum(v["calls"] for v in s.usage.mcp.values())
        if nt:
            parts.append(c("2", f"tools {nt}" + (f" · mcp {nm}" if nm else "")))
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

def top(d, n=8, key=None):
    items = sorted(d.items(), key=key or (lambda kv: -kv[1]))
    s = ", ".join(f"{k} ×{v}" for k, v in items[:n])
    return s + (f", +{len(items) - n} more" if len(items) > n else "") if items else "-"

def usage_report(sessions, limit=None):
    rows = sorted(sessions.values(), key=lambda s: s.last or "", reverse=True)
    if limit:
        rows = rows[:limit]
    total = Usage()
    out = [c("1", "Per-session usage")]
    for s in rows:
        u = s.usage; total.add(u)
        proj = os.path.basename((s.project or "").rstrip("/")) or "-"
        nm = sum(v["calls"] for v in u.mcp.values())
        out.append(c("36", f"{s.id[:8]}  {proj}") + c("2", f"  tools {sum(u.tools.values())} · mcp {nm} · bash {sum(u.bash.values())} · skills {sum(u.skills.values())}"))
        if u.skills or u.slash:
            out.append(f"  skills  {top(u.skills)}" + (f"   slash {top(u.slash)}" if u.slash else ""))
        if u.mcp:
            out.append(f"  mcp     {top({k: v['calls'] for k, v in u.mcp.items()}, 5)}")
        if u.bash:
            out.append(f"  bash    {top(u.bash)}")
        if u.rules:
            out.append(f"  rules   {', '.join(sorted('/'.join(p.rstrip('/').split('/')[-2:]) for p in u.rules))}")
    out.append("")
    out.append(c("1", f"Totals across {len(rows)} sessions"))
    out.append(c("33", "Skills") + f"   {top(total.skills, 20)}")
    if total.slash:
        out.append(c("33", "Slash") + f"    {top(total.slash, 20)}")
    out.append(c("33", "Bash") + f"     {top(total.bash, 20)}")
    out.append(c("33", "Tools") + f"    {top(total.tools, 20)}")
    out.append(c("33", "MCP") + c("2", "  (result tokens & cost are ESTIMATES: chars/4 at the model's input rate; out = issuing turn's output split across its calls)"))
    if total.mcp:
        out.append(f"  {'server/tool':<36} {'calls':>5} {'~result tok':>11} {'~result $':>9} {'~out tok':>9}")
        for k, v in sorted(total.mcp.items(), key=lambda kv: -kv[1]["calls"]):
            out.append(f"  {k[:36]:<36} {v['calls']:>5} {'~' + fmt_tok(v['result_tokens_est']):>11} {'~' + fmt_usd(v['result_cost_est']):>9} {'~' + fmt_tok(round(v['output_tokens_est'])):>9}")
    else:
        out.append("  -")
    out.append(c("33", "Rules/memory files seen") + c("2", "  (only what the transcript reveals; auto-loaded CLAUDE.md usually is NOT logged)"))
    for p, how in sorted(total.rules.items()):
        out.append(f"  {p}  " + c("2", f"[{', '.join(sorted(how))}]"))
    if not total.rules:
        out.append("  - none detected")
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
    r.add_argument("--usage", action="store_true", help="skills, MCP, Bash and rules-file usage instead of the cost table")
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
                     "tokens": s.tokens, "models": s.models, "unpriced_models": s.unknown_models,
                     "usage": s.usage.to_json()}
                    for s in sorted(sessions.values(), key=lambda s: s.last or "", reverse=True)]
            rows = rows[: a.last or None]
            tot = Usage()
            for s in sorted(sessions.values(), key=lambda s: s.last or "", reverse=True)[: a.last or None]:
                tot.add(s.usage)
            print(json.dumps({"sessions": rows, "totals": {"cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
                                                            "usage": tot.to_json()}}, indent=2))
        elif a.usage:
            print(usage_report(sessions, a.last or None))
        else:
            print(report(sessions, a.last or None))
        return 0
    p.print_help()
    return 1

if __name__ == "__main__":
    sys.exit(main())
