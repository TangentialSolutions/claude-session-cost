"""Generate realistic FAKE transcript fixtures (no real data)."""
import json, os, random
HERE = os.path.dirname(os.path.abspath(__file__))

def asst(sid, mid, rid, model, usage, ts, cwd="/home/dev/acme-api", side=False, block="text"):
    return {"type": "assistant", "sessionId": sid, "uuid": f"u-{mid}-{block}", "requestId": rid,
            "timestamp": ts, "cwd": cwd, "isSidechain": side,
            "message": {"id": mid, "type": "message", "role": "assistant", "model": model,
                        "content": [{"type": block}], "usage": usage}}

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
            rows.append(asst(sid, f"msg_{i}_{t}", f"req_{i}_{t}", model, u, ts, cwd=f"/home/dev/{proj}"))
            rows.append(asst(sid, f"msg_{i}_{t}", f"req_{i}_{t}", model, u, ts, cwd=f"/home/dev/{proj}", block="tool_use"))
        write(os.path.join(HERE, "fixtures", "demo", f"-home-dev-{proj}", sid + ".jsonl"), rows)

if __name__ == "__main__":
    basic(); demo()
