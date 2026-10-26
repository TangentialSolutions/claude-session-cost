import io, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import claude_cost as cc

SRC = open(os.path.join(ROOT, "claude_cost.py"), encoding="utf-8").read()
OLD = SRC.replace(f'__version__ = "{cc.__version__}"', '__version__ = "0.0.1"')

class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cc-upd-")
        self.target = os.path.join(self.home, "claude_cost.py")
        # files the updater must never touch
        self.keep = {"settings.json": '{"statusLine": {}}', "claude-cost-pricing.json": "{}",
                     os.path.join("claude-cost", "x.html"): "<p>page</p>"}
        for rel, txt in self.keep.items():
            os.makedirs(os.path.dirname(os.path.join(self.home, rel)), exist_ok=True)
            open(os.path.join(self.home, rel), "w").write(txt)
    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
    def assertUntouched(self):
        for rel, txt in self.keep.items():
            self.assertEqual(open(os.path.join(self.home, rel)).read(), txt)
    def baks(self):
        return sorted(f for f in os.listdir(self.home) if f.startswith("claude_cost.py.bak-"))
    def leftovers(self):
        return [f for f in os.listdir(self.home) if f.startswith(".claude_cost.")]

class PyUpdate(Base):
    def run_update(self, payload, **kw):
        lines = []
        def fake(url, dest):
            self.url = url
            open(dest, "w", encoding="utf-8").write(payload)
        with mock.patch.object(cc, "_download", fake):
            rc = cc.self_update(home=self.home, out=lines.append, **kw)
        return rc, "\n".join(lines)

    def test_fresh_install_and_idempotent(self):
        rc, out = self.run_update(SRC)
        self.assertEqual(rc, 0); self.assertIn(f"none -> {cc.__version__}", out)
        self.assertEqual(open(self.target).read(), SRC)
        self.assertTrue(os.access(self.target, os.X_OK))
        rc, out = self.run_update(SRC)
        self.assertEqual(rc, 0); self.assertIn("already up to date", out)
        self.assertEqual(self.baks(), []); self.assertEqual(self.leftovers(), [])
        self.assertUntouched()

    def test_upgrade_backs_up_and_keeps_three(self):
        open(self.target, "w").write(OLD)
        rc, out = self.run_update(SRC)
        self.assertEqual(rc, 0); self.assertIn(f"0.0.1 -> {cc.__version__}", out)
        self.assertEqual(len(self.baks()), 1)
        self.assertEqual(open(os.path.join(self.home, self.baks()[0])).read(), OLD)
        for i in range(5):
            open(self.target + f".bak-2020010{i}-000000", "w").write("old")
        open(self.target, "w").write(OLD)
        self.run_update(SRC)
        self.assertEqual(len(self.baks()), 3)
        self.assertNotIn("claude_cost.py.bak-20200100-000000", self.baks())
        self.assertUntouched()

    def test_ref_in_url(self):
        self.run_update(SRC, ref="v0.4.0")
        self.assertEqual(self.url, cc.REPO_RAW + "/v0.4.0/claude_cost.py")

    def test_rejects_bad_downloads(self):
        open(self.target, "w").write(OLD)
        for payload, msg in (("", "empty"), ("def (:\n", "does not compile"),
                             ("import sys; sys.exit(3)\n", "--version"), ("print('')\n", "--version")):
            rc, out = self.run_update(payload)
            self.assertEqual(rc, 1, payload); self.assertIn(msg, out)
            self.assertEqual(open(self.target).read(), OLD)
        self.assertEqual(self.baks(), []); self.assertEqual(self.leftovers(), [])
        self.assertUntouched()

    def test_download_error(self):
        def boom(url, dest): raise OSError("offline")
        with mock.patch.object(cc, "_download", boom):
            self.assertEqual(cc.self_update(home=self.home, out=lambda *_: None), 1)
        self.assertEqual(self.leftovers(), [])

    def test_cli_and_env_home(self):
        with mock.patch.object(cc, "_download", lambda u, d: open(d, "w").write(SRC)), \
             mock.patch.dict(os.environ, {"CLAUDE_COST_HOME": self.home}), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(cc.main(["update"]), 0)
        self.assertIn("updated", out.getvalue()); self.assertTrue(os.path.exists(self.target))

    def test_version_flag(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "claude_cost.py"), "--version"], capture_output=True, text=True)
        self.assertEqual(p.stdout.strip(), f"claude-cost {cc.__version__}")

@unittest.skipUnless(shutil.which("bash") and shutil.which("curl"), "needs bash and curl")
class ShellUpdate(Base):
    def sh(self, src_text, *args, env_extra=None):
        src = os.path.join(self.home, "..", os.path.basename(self.home) + "-src.py")
        open(src, "w").write(src_text)
        self.addCleanup(lambda: os.path.exists(src) and os.remove(src))
        env = dict(os.environ, HOME=self.home, CLAUDE_COST_UPDATE_URL="file://" + os.path.abspath(src))
        env.pop("CLAUDE_COST_HOME", None)
        env.update(env_extra or {})
        # same invocation shape as `curl ... | bash -s -- args`
        script = open(os.path.join(ROOT, "update.sh")).read()
        return subprocess.run(["bash", "-s", "--", *args], input=script, capture_output=True, text=True, env=env)

    def test_install_upgrade_noop(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        tgt = os.path.join(self.home, ".claude", "claude_cost.py")
        open(tgt, "w").write(OLD)
        p = self.sh(SRC)
        self.assertEqual(p.returncode, 0, p.stderr); self.assertIn(f"0.0.1 -> {cc.__version__}", p.stdout)
        self.assertEqual(open(tgt).read(), SRC)
        self.assertEqual(len([f for f in os.listdir(os.path.dirname(tgt)) if ".bak-" in f]), 1)
        p = self.sh(SRC)
        self.assertIn("already up to date", p.stdout)
        self.assertUntouched()

    def test_home_override_keep3_and_reject(self):
        for i in range(5):
            open(self.target + f".bak-2020010{i}-000000", "w").write("old")
        open(self.target, "w").write(OLD)
        p = self.sh(SRC, "--ref", "v9", env_extra={"CLAUDE_COST_HOME": self.home})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.baks()), 3)
        for bad in ("", "def (:\n", "import sys; sys.exit(1)\n"):
            open(self.target, "w").write(OLD)
            p = self.sh(bad, env_extra={"CLAUDE_COST_HOME": self.home})
            self.assertNotEqual(p.returncode, 0); self.assertEqual(open(self.target).read(), OLD)
        self.assertEqual(self.leftovers(), [])
        self.assertUntouched()

    def test_bad_arg(self):
        self.assertEqual(self.sh(SRC, "--bogus").returncode, 2)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
    def test_shellcheck(self):
        p = subprocess.run(["shellcheck", os.path.join(ROOT, "update.sh")], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)

if __name__ == "__main__":
    unittest.main()
