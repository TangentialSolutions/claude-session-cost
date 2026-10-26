"""Generate realistic FAKE transcript fixtures (no real data)."""
import json, os, random
HERE = os.path.dirname(os.path.abspath(__file__))

def asst(sid, mid, rid, model, usage, ts, cwd="/home/dev/acme-api", side=False, block="text", content=None):
    return {"type": "assistant", "sessionId": sid, "uuid": f"u-{mid}-{block}", "requestId": rid,
            "timestamp": ts, "cwd": cwd, "isSidechain": side,
            "message": {"id": mid, "type": "message", "role": "assistant", "model": model,
                        "content": content or [{"type": block}], "usage": usage}}

def tu(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}

def user(sid, ts, content, **kw):
    return {"type": "user", "sessionId": sid, "timestamp": ts, "message": {"role": "user", "content": content}, **kw}

def tr(tid, text):
    return {"type": "tool_result", "tool_use_id": tid, "content": text}

def write(path, rows, extra=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
        f.write(extra)

def basic():
    sid = "11111111-aaaa-bbbb-cccc-000000000001"
    u1 = {"input_tokens": 1000, "output_tokens": 500, "cache_creation_input_tokens": 20000,
          "cache_read_input_tokens": 0,
          "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 20000}}
    u2 = {"input_tokens": 200, "output_tokens": 1000, "cache_creation_input_tokens": 4000,
          "cache_read_input_tokens": 100000}          # no split -> treated as 5m
    rows = [
        {"type": "user", "sessionId": sid, "timestamp": "2026-10-26T13:00:00.000Z", "message": {"role": "user", "content": "hi"}},
        # streaming duplicates: same message id + request id, one line per content block
        asst(sid, "msg_A", "req_A", "claude-opus-4-5-20251101", dict(u1, output_tokens=12), "2026-10-26T13:00:05.000Z", block="thinking"),
        asst(sid, "msg_A", "req_A", "claude-opus-4-5-20251101", u1, "2026-10-26T13:00:06.000Z", block="text"),
        asst(sid, "msg_A", "req_A", "claude-opus-4-5-20251101", u1, "2026-10-26T13:00:06.500Z", block="tool_use"),
        asst(sid, "msg_B", "req_B", "claude-opus-4-5-20251101", u2, "2026-10-26T13:01:00.000Z"),
        # sidechain (Task subagent) on Haiku
        asst(sid, "msg_C", "req_C", "claude-haiku-4-5-20251001",
             {"input_tokens": 10000, "output_tokens": 2000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
             "2026-10-26T13:02:00.000Z", side=True),
        # unknown model -> not priced, flagged
        asst(sid, "msg_D", "req_D", "claude-nimbus-9",
             {"input_tokens": 5, "output_tokens": 5}, "2026-10-26T13:03:00.000Z"),
        # synthetic message (Claude Code local error) -> ignored
        asst(sid, "msg_E", "req_E", "<synthetic>", {"input_tokens": 0, "output_tokens": 0}, "2026-10-26T13:03:01.000Z"),
    ]
    write(os.path.join(HERE, "fixtures", "basic", sid + ".jsonl"), rows, extra='{"type":"assistant","truncated')
    # subagent transcript stored beside the session
    write(os.path.join(HERE, "fixtures", "basic", sid, "subagents", "agent-x.jsonl"), [
        asst(sid, "msg_F", "req_F", "claude-sonnet-4-5-20250929",
             {"input_tokens": 1000, "output_tokens": 1000, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
             "2026-10-26T13:04:00.000Z", side=True)])

def demo():
    """Larger realistic-looking fake history for the screenshot."""
    random.seed(7)
    projects = ["acme-api", "web-dashboard", "infra-terraform", "data-pipeline", "mobile-app"]
    models = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-4-7", "claude-sonnet-4-6"]
    for i in range(8):
        sid = f"{random.getrandbits(32):08x}-demo-4000-8000-{i:012d}"
        proj = projects[i % len(projects)]; model = models[i % len(models)]
        rows, ctx = [], 18000
        day, hour = 26 - i // 3, 9 + (i * 2) % 9
        for t in range(random.randint(15, 60)):
            ctx += random.randint(800, 6000)
            u = {"input_tokens": random.randint(3, 40), "output_tokens": random.randint(80, 2500),
                 "cache_creation_input_tokens": random.randint(500, 6000), "cache_read_input_tokens": ctx,
                 "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
            u["cache_creation"]["ephemeral_1h_input_tokens"] = u["cache_creation_input_tokens"]
            ts = f"2026-10-{day:02d}T{hour + t // 30:02d}:{(t*2) % 60:02d}:00.000Z"
            if t == 0:
                rows.append(user(sid, ts, [{"type": "text", "text": f"<system-reminder>Contents of /home/dev/{proj}/CLAUDE.md (project instructions)</system-reminder>"}]))
            tools = demo_usage(random, i, t)
            rows.append(asst(sid, f"msg_{i}_{t}", f"req_{i}_{t}", model, u, ts, cwd=f"/home/dev/{proj}"))
            rows.append(asst(sid, f"msg_{i}_{t}", f"req_{i}_{t}", model, u, ts, cwd=f"/home/dev/{proj}", content=tools or None, block="text"))
            if tools:
                rows.append(user(sid, ts, [tr(b["id"], "r" * random.randint(200, 24000)) for b in tools]))
        write(os.path.join(HERE, "fixtures", "demo", f"-home-dev-{proj}", sid + ".jsonl"), rows)

def usage():
    sid = "22222222-aaaa-bbbb-cccc-000000000002"
    M = "claude-sonnet-4-5-20250929"
    U = {"input_tokens": 100, "output_tokens": 400, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    T = "2026-10-26T14:00:%02d.000Z"
    rows = [
        user(sid, T % 0, "<command-name>/review</command-name><command-message>review</command-message>"),
        user(sid, T % 1, [{"type": "text", "text": "<system-reminder>Contents of /home/dev/acme-api/CLAUDE.md (project instructions, checked into the codebase):\n- use pnpm</system-reminder>"}]),
        user(sid, T % 2, "please follow @docs/STYLE.md and fix the bug"),
        {"type": "attachment", "sessionId": sid, "timestamp": T % 3, "attachment": {"type": "nested_memory", "path": "/home/dev/acme-api/src/CLAUDE.md"}},
        # one API response streamed as 3 lines: text, then two tool_use blocks (one per line)
        asst(sid, "msg_1", "req_1", M, U, T % 4, content=[{"type": "text", "text": "ok"}]),
        asst(sid, "msg_1", "req_1", M, U, T % 4, content=[tu("t1", "Skill", {"skill": "pdf"})]),
        asst(sid, "msg_1", "req_1", M, U, T % 4, content=[tu("t2", "mcp__github__search_issues", {"q": "bug"})]),
        user(sid, T % 5, [tr("t1", "skill loaded"), tr("t2", "x" * 4000)]),
        asst(sid, "msg_2", "req_2", M, dict(U, output_tokens=300), T % 6, content=[
            tu("t3", "Bash", {"command": "cd app && FOO=1 sudo -E npm test | tee out.log"}),
            tu("t4", "Bash", {"command": "/usr/bin/git status"}),
            tu("t5", "mcp__github__search_issues", {"q": "x"}),
            tu("t6", "Read", {"file_path": "/home/dev/.claude/CLAUDE.md"})]),
        user(sid, T % 7, [tr("t3", "ok"), tr("t4", "clean"), tr("t5", [{"type": "text", "text": "y" * 800}]), tr("t6", "rules")]),
        asst(sid, "msg_3", "req_3", M, U, T % 8, content=[tu("t7", "Skill", {"skill": "pdf"}), tu("t8", "mcp__linear-server__create_issue", {})]),
    ]
    write(os.path.join(HERE, "fixtures", "usage", sid + ".jsonl"), rows)

def gap():
    """Sonnet 4.5 [1m] session with 2 subagents, built to reproduce the ways claude-cost used to under-count."""
    sid = "33333333-aaaa-bbbb-cccc-000000000003"
    M = "claude-sonnet-4-5-20250929[1m]"
    T = "2026-10-26T15:%02d:00.000Z"
    d = os.path.join(HERE, "fixtures", "gap")
    def U(inp, cr, cw, out):  # no cache_creation split (older transcripts)
        return {"input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}
    main = [asst(sid, "g1", "r1", M, U(2000, 150000, 20000, 3000), T % 1, content=[tu("a1", "Task", {"prompt": "x"}), tu("a2", "Task", {"prompt": "y"})]),
            # >200k prompt: long-context tier on Sonnet 4.5 1M beta
            asst(sid, "g2", "r2", M, U(1000, 230000, 10000, 4000), T % 2),
            asst(sid, "g3", "r3", M, U(1000, 240000, 5000, 2000), T % 3)]
    write(os.path.join(d, sid + ".jsonl"), main)
    # subagent 1: current layout, but its lines carry no sessionId
    sub1 = [asst(sid, "s1", "q1", "claude-sonnet-4-5-20250929", U(500, 40000, 8000, 1500), T % 4) for _ in range(1)]
    for r in sub1: r.pop("sessionId"); r["agentId"] = "aaaa1111"
    write(os.path.join(d, sid, "subagents", "agent-aaaa1111.jsonl"), sub1)
    # subagent 2: older layout, sibling agent-*.jsonl in the project dir
    write(os.path.join(d, "agent-bbbb2222.jsonl"),
          [asst(sid, "s2", "q2", "claude-sonnet-4-5-20250929", U(500, 30000, 6000, 1200), T % 5, side=True)])
    # unrelated sibling agent file from another session: must NOT be attributed
    write(os.path.join(d, "agent-cccc3333.jsonl"),
          [asst("99999999-0000-0000-0000-000000000000", "s3", "q3", "claude-sonnet-4-5-20250929", U(1, 0, 0, 1), T % 6, side=True)])

def demo_usage(rng, i, t):
    """Fake tool_use blocks for the demo screenshot."""
    pool = [("Bash", {"command": c}) for c in ["git status", "cd web && pnpm test", "npm run build", "rg TODO src",
            "sudo docker compose up -d", "NODE_ENV=test npx jest", "python3 -m pytest -q", "terraform plan", "ls -la"]]
    pool += [("mcp__github__get_pull_request", {}), ("mcp__github__search_code", {}), ("mcp__linear__list_issues", {}),
             ("mcp__notion__fetch", {}), ("Skill", {"skill": "frontend-design"}), ("Skill", {"skill": "pdf"}),
             ("Read", {"file_path": "/home/dev/x.ts"}), ("Edit", {"file_path": "/home/dev/x.ts"})]
    k = rng.randint(0, 2)
    return [tu(f"tu_{i}_{t}_{j}", *rng.choice(pool)) for j in range(k)]

if __name__ == "__main__":
    basic(); demo(); usage(); gap()
