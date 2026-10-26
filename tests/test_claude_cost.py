import io, json, os, sys, unittest
from contextlib import redirect_stdout
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import claude_cost as cc

SID = "11111111-aaaa-bbbb-cccc-000000000001"
BASIC = os.path.join(HERE, "fixtures", "basic", SID + ".jsonl")
os.environ["NO_COLOR"] = "1"
import re, tempfile
os.environ["CLAUDE_COST_DIR"] = tempfile.mkdtemp(prefix="claude-cost-test-")
os.environ.pop("CLAUDE_COST_LINKS", None); os.environ.pop("CLAUDE_COST_CACHE_TTL", None); os.environ.pop("TERM_PROGRAM", None)
OSC8 = re.compile(r"\x1b\]8;;[^\x07]*\x07")
def plain(s): return OSC8.sub("", s)

class T(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(cc.normalize_model("claude-opus-4-5-20251101"), "opus-4-5")
        self.assertEqual(cc.normalize_model("claude-sonnet-4-5-20250929[1m]"), "sonnet-4-5")
        self.assertEqual(cc.normalize_model("us.anthropic.claude-sonnet-4-5-20250929-v1:0"), "sonnet-4-5")
        self.assertEqual(cc.normalize_model("claude-3-5-haiku-20241022"), "haiku-3-5")
        self.assertEqual(cc.normalize_model("claude-opus-5-5"), "opus-5-5")

    def test_prefix_and_unknown(self):
        t = cc.load_pricing()
        self.assertEqual(cc.price_for("claude-opus-4-5-preview", t)[1], "opus-4-5")
        self.assertEqual(cc.price_for("claude-opus-4", t)[1], "opus-4")
        self.assertEqual(cc.price_for("claude-nimbus-9", t), (None, None))
        self.assertEqual(cc.price_for(None, t), (None, None))

    def test_split_usage(self):
        u = cc.split_usage({"input_tokens": 1, "cache_creation_input_tokens": 10,
                            "cache_creation": {"ephemeral_1h_input_tokens": 4}})
        self.assertEqual((u["cache_write_5m"], u["cache_write_1h"]), (6, 4))

    def test_basic_session_dedupe_and_cost(self):
        s = cc.analyze(cc.session_files(BASIC))[SID]
        # msg_A (deduped, 3 lines -> 1), msg_B, msg_C, msg_D(unknown), msg_F(subagent file); synthetic ignored
        self.assertEqual(s.messages, 5)
        self.assertEqual(s.tokens["output"], 500 + 1000 + 2000 + 5 + 1000)
        self.assertEqual(s.tokens["cache_write_1h"], 20000)
        self.assertEqual(s.tokens["cache_write_5m"], 4000)
        opus_a = (1000 * 5 + 500 * 25 + 20000 * 10) / 1e6        # 1h write @ $10
        opus_b = (200 * 5 + 1000 * 25 + 4000 * 6.25 + 100000 * 0.5) / 1e6
        haiku_c = (10000 * 1 + 2000 * 5) / 1e6
        sonnet_f = (1000 * 3 + 1000 * 15) / 1e6
        self.assertAlmostEqual(s.cost, opus_a + opus_b + haiku_c + sonnet_f, places=9)
        self.assertAlmostEqual(s.sidechain_cost, haiku_c + sonnet_f, places=9)
        self.assertIn("claude-nimbus-9", s.unknown_models)

    def test_haiku55_long_context_tier(self):
        r = cc.load_pricing()["haiku-5-5"]
        short = cc.split_usage({"input_tokens": 50000, "output_tokens": 0})
        long_ = cc.split_usage({"input_tokens": 150000, "output_tokens": 0})
        self.assertAlmostEqual(cc.cost_of(short, r), 0.005)
        self.assertAlmostEqual(cc.cost_of(long_, r), 0.075)

    def test_web_search_and_fast(self):
        r = cc.load_pricing()["opus-5-5"]
        t = cc.split_usage({"input_tokens": 1_000_000, "server_tool_use": {"web_search_requests": 3}})
        self.assertAlmostEqual(cc.cost_of(t, r), 4 + 0.03)
        self.assertAlmostEqual(cc.cost_of(t, r, fast=True), 8 + 0.03)

    def test_override(self):
        p = os.path.join(HERE, "fixtures", "override.json")
        with open(p, "w") as f:
            json.dump({"claude-nimbus-9": {"input": 1, "cache_write_5m": 1, "cache_write_1h": 1, "cache_read": 1, "output": 1}}, f)
        os.environ["CLAUDE_COST_PRICING"] = p
        try:
            s = cc.analyze([BASIC])[SID]
            self.assertEqual(s.unknown_models, {})
        finally:
            del os.environ["CLAUDE_COST_PRICING"]; os.remove(p)

    def test_statusline(self):
        line = cc.statusline({"session_id": SID, "transcript_path": BASIC,
                              "model": {"id": "claude-opus-4-5", "display_name": "Opus 4.5"},
                              "cost": {"total_cost_usd": 0.33}})
        self.assertIn("[Opus 4.5]", line); self.assertIn("(cc $0.33)", line)
        self.assertIn("cw 24.0k", line); self.assertIn("?unpriced", line)

    def test_statusline_missing_transcript(self):
        self.assertIn("$1.23", cc.statusline({"model": {"display_name": "X"}, "cost": {"total_cost_usd": 1.23}}))
        self.assertIn("$0.00", cc.statusline({}))

    def test_report_cli_and_since(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cc.main(["report", "--dir", os.path.join(HERE, "fixtures", "demo"), "-n", "0", "--json"])
        rows = json.loads(buf.getvalue())["sessions"]
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r["cost_usd"] > 0 for r in rows))
        late = cc.analyze(cc.find_transcripts(os.path.join(HERE, "fixtures", "demo")), since="2026-10-26T00:00:00")
        self.assertLess(len(late), 8)

if __name__ == "__main__":
    unittest.main(verbosity=2)

USID = "22222222-aaaa-bbbb-cccc-000000000002"
UFILE = os.path.join(HERE, "fixtures", "usage", USID + ".jsonl")

class Usage(unittest.TestCase):
    def setUp(self):
        self.s = cc.analyze([UFILE])[USID]
        self.u = self.s.usage

    def test_bash_parsing(self):
        f = cc.bash_base_commands
        self.assertEqual(f("cd app && FOO=1 sudo -E npm test | tee out.log"), ["npm", "tee"])
        self.assertEqual(f("/usr/bin/git status"), ["git"])
        self.assertEqual(f("env A=1 B=2 timeout 30 python3 x.py; cd /; ls"), ["python3", "ls"])
        self.assertEqual(f("cd foo"), [])
        self.assertEqual(f("echo 'a && b' && make"), ["echo", "make"])
        self.assertEqual(f("unbalanced 'quote"), ["unbalanced"])

    def test_skills_and_slash(self):
        self.assertEqual(self.u.skills, {"pdf": 2})
        self.assertEqual(self.u.slash, {"/review": 1})

    def test_tool_counts_dedupe_streaming(self):
        # msg_1 streamed over 3 lines; each tool_use counted once
        self.assertEqual(self.u.tools["Skill"], 2)
        self.assertEqual(self.u.tools["Bash"], 2)
        self.assertEqual(self.s.messages, 3)

    def test_mcp_attribution(self):
        gh = self.u.mcp["github/search_issues"]
        self.assertEqual(gh["calls"], 2)
        self.assertEqual(gh["result_tokens_est"], 1000 + 200)          # 4000 chars/4 + 800 chars/4
        self.assertAlmostEqual(gh["result_cost_est"], 1200 * 3 / 1e6)  # sonnet-4-5 input rate
        self.assertAlmostEqual(gh["output_tokens_est"], 400 / 2 + 300 / 4)
        self.assertEqual(self.u.mcp["linear-server/create_issue"]["calls"], 1)

    def test_rules(self):
        r = self.u.rules
        self.assertIn("system-reminder", r["/home/dev/acme-api/CLAUDE.md"])
        self.assertIn("Read tool", r["/home/dev/.claude/CLAUDE.md"])
        self.assertIn("attachment:nested_memory", r["/home/dev/acme-api/src/CLAUDE.md"])
        self.assertIn("@-mention", r["docs/STYLE.md"])

    def test_usage_report_and_json(self):
        txt = cc.usage_report({USID: self.s})
        for needle in ("pdf ×2", "github/search_issues", "ESTIMATES", "npm ×1", "src/CLAUDE.md"):
            self.assertIn(needle, txt)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cc.main(["report", "--dir", os.path.dirname(UFILE), "--json"])
        d = json.loads(buf.getvalue())
        self.assertEqual(d["totals"]["usage"]["bash_commands"], {"npm": 1, "tee": 1, "git": 1})
        self.assertEqual(d["sessions"][0]["usage"]["skills"], {"pdf": 2})

    def test_statusline_segment(self):
        line = cc.statusline({"session_id": USID, "transcript_path": UFILE, "model": {"display_name": "Sonnet"}})
        self.assertIn("tools 8 · mcp 3", plain(line))

GSID = "33333333-aaaa-bbbb-cccc-000000000003"
GFILE = os.path.join(HERE, "fixtures", "gap", GSID + ".jsonl")

class Links(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cc-links-")
        self.data = {"session_id": USID, "transcript_path": UFILE, "model": {"display_name": "Sonnet"}}

    def test_osc8_and_page(self):
        line = cc.statusline(self.data, out_dir=self.dir)
        page = os.path.join(self.dir, USID + ".html")
        self.assertIn("\x1b]8;;file://" + page + "#tools\x07tools 8\x1b]8;;\x07", line)
        self.assertIn("#mcp\x07mcp 3\x1b]8;;\x07", line)
        h = open(page).read()
        for needle in ('id=tools', 'id=mcp', "github/search_issues", "linear-server", "estimates", "Bash"):
            self.assertIn(needle, h)
        md = open(os.path.join(self.dir, USID + ".md")).read()
        self.assertIn("| github/search_issues | 2 |", md)
        self.assertEqual(open(os.path.join(self.dir, "last-session")).read().strip(), USID)

    def test_page_throttled(self):
        cc.statusline(self.data, out_dir=self.dir)
        page = os.path.join(self.dir, USID + ".html")
        os.utime(page, (1, 1))
        cc.statusline(self.data, out_dir=self.dir)
        self.assertEqual(os.stat(page).st_mtime, 1)          # unchanged counts -> not rewritten
        cc.statusline(dict(self.data, cost={"total_cost_usd": 9.99}), out_dir=self.dir)
        self.assertNotEqual(os.stat(page).st_mtime, 1)       # changed -> rewritten

    def test_links_off(self):
        for env in ({"CLAUDE_COST_LINKS": "0"}, {"TERM_PROGRAM": "Apple_Terminal"}):
            os.environ.update(env)
            try:
                line = cc.statusline(self.data, out_dir=self.dir)
            finally:
                for k in env: os.environ.pop(k)
            self.assertNotIn("\x1b]8", line); self.assertIn("tools 8 · mcp 3", line)
        self.assertNotIn("\x1b]8", cc.statusline(self.data, links=False, out_dir=self.dir))
        self.assertFalse(os.path.exists(os.path.join(self.dir, USID + ".html")))

    def test_html_escaped(self):
        s = cc.Session("<x>"); s.usage.tools["<script>"] = 1
        self.assertNotIn("<script>", cc.usage_html(s)); self.assertIn("&lt;script&gt;", cc.usage_html(s))

    def test_usage_command(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cc.main(["usage", "--dir", os.path.dirname(UFILE), "--usage-dir", self.dir])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), os.path.join(self.dir, USID + ".html"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            cc.main(["usage", "2222", "--md", "--dir", os.path.dirname(UFILE), "--usage-dir", self.dir])
        self.assertTrue(buf.getvalue().strip().endswith(".md"))
        self.assertEqual(cc.main(["usage", "nope", "--dir", os.path.dirname(UFILE), "--usage-dir", self.dir]), 1)

class Gap(unittest.TestCase):
    """Reproduces the statusline-vs-cc gap for a Sonnet [1m] session with 2 subagents."""
    def rates(self):
        return cc.load_pricing()["sonnet-4-5"]

    def test_all_subagent_files_attributed_to_parent(self):
        files = cc.session_files(GFILE)
        names = [os.path.basename(f) for f in files]
        self.assertIn("agent-aaaa1111.jsonl", names)        # <sid>/subagents/, lines without sessionId
        self.assertIn("agent-bbbb2222.jsonl", names)        # legacy sibling with matching sessionId
        self.assertNotIn("agent-cccc3333.jsonl", names)     # other session's sibling
        sessions = cc.analyze(files, default_ttl="5m")
        self.assertEqual(list(sessions), [GSID])
        self.assertEqual(sessions[GSID].messages, 5)

    def test_long_context_tier(self):
        r = self.rates()
        u = cc.split_usage({"input_tokens": 1000, "cache_read_input_tokens": 240000, "cache_creation_input_tokens": 5000, "output_tokens": 2000})
        self.assertAlmostEqual(cc.cost_of(u, r, False), (1000 * 6 + 240000 * 0.6 + 5000 * 7.5 + 2000 * 22.5) / 1e6)
        u = cc.split_usage({"input_tokens": 1000, "cache_read_input_tokens": 150000, "output_tokens": 2000})
        self.assertAlmostEqual(cc.cost_of(u, r, False), (1000 * 3 + 150000 * 0.3 + 2000 * 15) / 1e6)

    def test_unsplit_cache_ttl(self):
        u = {"input_tokens": 0, "cache_creation_input_tokens": 1000, "output_tokens": 0}
        self.assertEqual(cc.split_usage(u)["cache_write_5m"], 1000)
        self.assertEqual(cc.split_usage(u, "1h")["cache_write_1h"], 1000)
        os.environ["CLAUDE_COST_CACHE_TTL"] = "1h"
        try:
            self.assertEqual(cc.default_cache_ttl(), "1h")
        finally:
            os.environ.pop("CLAUDE_COST_CACHE_TTL")
        a = cc.analyze(cc.session_files(GFILE), default_ttl="5m")[GSID].cost
        b = cc.analyze(cc.session_files(GFILE), default_ttl="1h")[GSID].cost
        self.assertAlmostEqual(b - a, 34000 * (6 - 3.75) / 1e6 + 15000 * (12 - 7.5) / 1e6)

    def test_statusline_uses_prompt_cache_ttl_and_subagents(self):
        def cost(ttl):
            line = plain(cc.statusline({"session_id": GSID, "transcript_path": GFILE, "model": {"display_name": "Sonnet 4.5"},
                                        "prompt_cache": {"ttl": ttl}}, links=False))
            return float(re.search(r"\$(\d+\.\d+)", line).group(1))
        self.assertAlmostEqual(cost("5m"), 0.83, places=2)   # was $0.46 before the fixes
        self.assertAlmostEqual(cost("1h"), 0.97, places=2)

    def test_relogged_sidechain_keeps_main_attribution(self):
        import json as _j
        d = tempfile.mkdtemp(); sid = "44444444-0000-0000-0000-000000000004"
        row = {"type": "assistant", "sessionId": sid, "requestId": "r", "timestamp": "2026-10-26T10:00:00Z",
               "message": {"id": "m", "model": "claude-sonnet-4-5", "usage": {"input_tokens": 1000, "output_tokens": 10}}}
        os.makedirs(os.path.join(d, sid, "subagents"))
        open(os.path.join(d, sid + ".jsonl"), "w").write(_j.dumps(row) + "\n")
        open(os.path.join(d, sid, "subagents", "agent-aside_question-x.jsonl"), "w").write(_j.dumps(dict(row, isSidechain=True)) + "\n")
        s = cc.analyze(cc.session_files(os.path.join(d, sid + ".jsonl")))[sid]
        self.assertEqual(s.messages, 1); self.assertEqual(s.sidechain_cost, 0)

if __name__ == "__main__":
    unittest.main()
