"""Purrge 回归测试：锁住现有行为（v0.2.2），重构和新增功能前后都必须全部通过。
运行：python3 -m unittest discover -s tests -v
每个用例都在临时 HOME / PURRGE_HOME 里的独立子进程中运行，不碰真实的 ~/.purrge、废纸篓和后台任务。"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

WIN = sys.platform == "win32"
ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "runtime" / "lib"
FAKE = {
    # 假的 claude：记录参数，按 stdin 里的候选清单返回一份 AI 判断
    "claude": r'''#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"bin": "claude", "args": args}) + "\n")
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True})); sys.exit(0)
if "--version" in args:
    print("9.9.9 (Claude Code)"); sys.exit(0)
src = sys.stdin.read()
m = re.search(r"```json\n(.*)\n```", src, re.S)
items = json.loads(m.group(1)) if m else []
out = {"summary": "测试总结", "items": [{"id": it["id"], "tier": "primary", "title": "AI:" + it["id"], "reason": "AI 理由", "category": "测试"} for it in items]}
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "fail":
    sys.stderr.write("boom"); sys.exit(1)
result = {"type": "result", "subtype": "success", "result": "这是结果：" + json.dumps(out, ensure_ascii=False)}
if mode == "verbose":    # Claude Code 开了 verbose：输出整段消息数组
    print(json.dumps([{"type": "system", "subtype": "init"}, {"type": "assistant", "message": {}}, result], ensure_ascii=False))
elif mode == "verbose-noresult":
    print(json.dumps([{"type": "system", "subtype": "init"}, {"type": "assistant", "message": {}}]))
elif mode == "scalar":
    print(json.dumps("OK"))
elif mode == "text":
    print("OK")
else:
    print(json.dumps(result, ensure_ascii=False))
''',
    # 假的 codex：默认模型报"不支持"，换成缓存里的模型才成功
    "codex": r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"bin": "codex", "args": args}) + "\n")
if "--version" in args:
    print("codex-cli 9.9.9"); sys.exit(0)
if args[:2] == ["login", "status"]:
    sys.exit(0)
model = args[args.index("-m") + 1] if "-m" in args else ""
if model != "good-model":
    sys.stderr.write('ERROR: {"message":"The model is not supported when using Codex"}'); sys.exit(1)
out = args[args.index("-o") + 1]
sys.stdin.read()
open(out, "w").write("OK")
''',
}


FAKE["codebuddy"] = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"bin": "codebuddy", "args": args}) + "\n")
if "--version" in args:
    print("2.173.0"); sys.exit(0)
sys.stdin.read()
if args[args.index("--output-format") + 1] == "text":
    print("OK")
else:   # json 模式输出整段对话（真实 CodeBuddy 会带上很长的系统提示）
    print(json.dumps([{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "OK"}]}, {"type": "result", "result": "OK"}]))
'''
FAKE["dsh"] = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"bin": "dsh", "args": args, "key": os.environ.get("DEEPSEEK_API_KEY", "")}) + "\n")
if "--version" in args:
    print("0.2.1"); sys.exit(0)
if "--dump-config" in args:
    pp = args[args.index("--patch") + 1] if "--patch" in args else ""
    if pp and not os.path.exists(pp):
        sys.stderr.write("patch not found"); sys.exit(2)
    off = bool(pp) and "disabled: true" in open(pp).read()
    for t in ("tool-bash", "tool-pwsh", "tool-jobs", "tool-fs"):
        print(f"- id: {t}\n  name: x" + ("\n  disabled: true" if off else ""))
    sys.exit(0)
sys.stdin.read()
print("OK")
'''


class Env:
    """一个隔离的运行环境：临时 HOME、PURRGE_HOME、假的 AI 命令行。"""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.log = Path(self.tmp.name) / "calls.jsonl"
        self.log.write_text("")
        for name, src in FAKE.items():
            if WIN:   # Windows 不认 shebang：用 name.cmd 调 python 跑 name.py
                (self.bin / f"{name}.py").write_text(src, encoding="utf-8")
                (self.bin / f"{name}.cmd").write_text(f'@"{sys.executable}" "%~dp0{name}.py" %*\r\n', encoding="utf-8")
                continue
            p = self.bin / name
            p.write_text(src)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        self.extra = {}

    def run(self, code, check=True):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), PURRGE_HOME=str(self.home / ".purrge"), FAKE_LOG=str(self.log),
                   PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
                   PURRGE_NO_UPDATE_CHECK="1", PURRGE_TEST_NO_MONITOR="1", **self.extra)
        prog = "import sys, json\nsys.path.insert(0, %r)\n" % str(LIB) + textwrap.dedent(code)
        p = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, env=env, timeout=120, encoding="utf-8")
        if check and p.returncode:
            raise AssertionError(p.stderr[-2000:])
        last = [l for l in p.stdout.splitlines() if l.startswith("@@")]
        return json.loads(last[-1][2:]) if last else None

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines() if l.strip()]

    def close(self):
        self.tmp.cleanup()


class Base(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.close()


class TestCleanSafety(Base):
    """清理只处理勾选项；保护名单、mtime 变化、废纸篓、contents 模式。"""

    def make(self):
        h = self.e.home
        (h / "cache/sub").mkdir(parents=True)
        (h / "cache/a.bin").write_bytes(b"x" * 4096)
        (h / "cache/sub/b.bin").write_bytes(b"x" * 4096)
        (h / "big.mov").write_bytes(b"x" * 8192)
        (h / "keep.mov").write_bytes(b"x" * 8192)
        (h / "changed.mov").write_bytes(b"x" * 8192)
        (h / ".claude").mkdir()
        (h / ".claude/settings.json").write_text("{}")
        (h / "notselected.mov").write_bytes(b"x" * 8192)

    def test_clean(self):
        self.make()
        r = self.e.run(r'''
        import os, time
        from pathlib import Path
        from clean import clean
        H = Path.home()
        m = lambda p: os.stat(p).st_mtime
        items = [
          {"id": "c1", "path": str(H/"cache"), "kind": "cache", "mode": "contents", "tier": "primary"},
          {"id": "c2", "path": str(H/"big.mov"), "kind": "large-file", "mode": "whole", "tier": "optional", "mtimeAtScan": m(H/"big.mov")},
          {"id": "c3", "path": str(H/"keep.mov"), "kind": "large-file", "mode": "whole", "tier": "keep", "mtimeAtScan": m(H/"keep.mov")},
          {"id": "c4", "path": str(H/".claude"), "kind": "cache", "mode": "whole", "tier": "primary"},
          {"id": "c5", "path": str(H/"changed.mov"), "kind": "large-file", "mode": "whole", "tier": "optional", "mtimeAtScan": m(H/"changed.mov") - 100},
          {"id": "c6", "path": str(H/"notselected.mov"), "kind": "large-file", "mode": "whole", "tier": "optional", "mtimeAtScan": m(H/"notselected.mov")},
        ]
        out = clean({"items": items}, ["c1", "c2", "c3", "c4", "c5", "ghost"], log=lambda *a: None)
        st = {x["id"]: x["status"] for x in out["results"]}
        print("@@" + json.dumps({"st": st,
          "cache_dir": (H/"cache").is_dir(), "cache_empty": not any((H/"cache").iterdir()),
          "big_gone": not (H/"big.mov").exists(), "big_in_trash": (H/".Trash/big.mov").exists(),
          "keep": (H/"keep.mov").exists(), "claude": (H/".claude/settings.json").exists(),
          "changed": (H/"changed.mov").exists(), "notselected": (H/"notselected.mov").exists(),
          "keys": sorted(out.keys())}))
        ''')
        self.assertEqual(r["st"], {"c1": "deleted", "c2": "trashed", "c3": "skipped", "c4": "skipped", "c5": "skipped", "ghost": "skipped"})
        self.assertTrue(r["cache_dir"] and r["cache_empty"], "contents 模式保留目录本身、清空内容")
        self.assertTrue(r["big_gone"] and (WIN or r["big_in_trash"]), "需要你决定的项目默认移到废纸篓 / 回收站")
        self.assertTrue(r["keep"] and r["claude"] and r["changed"] and r["notselected"])
        self.assertEqual(r["keys"], ["finishedAt", "freeAfter", "freeBefore", "freedBytes", "results"])

    def test_delete_mode(self):
        self.make()
        r = self.e.run(r'''
        import os
        from pathlib import Path
        from common import load_config, save_config
        from clean import clean
        c = load_config(); c["optionalAction"] = "delete"; save_config(c)
        H = Path.home()
        it = {"id": "c2", "path": str(H/"big.mov"), "kind": "large-file", "mode": "whole", "tier": "optional", "mtimeAtScan": os.stat(H/"big.mov").st_mtime}
        out = clean({"items": [it]}, ["c2"], log=lambda *a: None)
        print("@@" + json.dumps({"st": out["results"][0]["status"], "gone": not (H/"big.mov").exists(), "trash": (H/".Trash/big.mov").exists()}))
        ''')
        self.assertEqual(r, {"st": "deleted", "gone": True, "trash": False})


class TestClassify(Base):
    """AI 判断：保护名单强制 keep、用户文件不进首要清理、AI 失败退回规则。"""

    CAND = r'''
    cand = {"items": [
      {"id": "c001", "path": "/x/cache", "sizeBytes": 10, "kind": "cache", "name": "缓存", "defaultTier": "primary", "regenerable": True, "protected": False},
      {"id": "c002", "path": "/x/big.mov", "sizeBytes": 10, "kind": "large-file", "name": None, "defaultTier": "optional", "regenerable": False, "protected": False},
      {"id": "c003", "path": "/x/prot", "sizeBytes": 10, "kind": "cache", "name": "受保护", "defaultTier": "primary", "regenerable": True, "protected": True},
    ]}
    '''

    def test_ai(self):
        r = self.e.run(textwrap.dedent(self.CAND) + textwrap.dedent(r'''
        from common import load_config, save_config
        import shutil
        c = load_config(); c.update(aiEngine="claude", claudePath=shutil.which("claude")); save_config(c)
        from classify import classify
        rv = classify(cand, log=lambda *a: None)
        print("@@" + json.dumps({"by": rv["judgedBy"], "engine": rv.get("engine"), "summary": rv["summary"], "tiers": {x["id"]: x["tier"] for x in rv["items"]}, "title": rv["items"][0]["title"]}))
        '''))
        self.assertEqual(r["by"], "ai")
        self.assertEqual(r["engine"], "Claude Code")
        self.assertEqual(r["tiers"], {"c001": "primary", "c002": "optional", "c003": "keep"})
        self.assertEqual(r["title"], "AI:c001")
        claude = [c for c in self.e.calls() if c["bin"] == "claude" and "-p" in c["args"]][0]["args"]
        for need in ("-p", "--tools", "--no-session-persistence", "--max-turns"):
            self.assertIn(need, claude)
        self.assertEqual(claude[claude.index("--tools") + 1], "", "Claude 必须关掉全部工具")

    def test_fallback(self):
        self.e.extra["FAKE_MODE"] = "fail"
        r = self.e.run(textwrap.dedent(self.CAND) + textwrap.dedent(r'''
        from common import load_config, save_config
        import shutil
        c = load_config(); c.update(aiEngine="claude", claudePath=shutil.which("claude")); save_config(c)
        from classify import classify
        rv = classify(cand, log=lambda *a: None)
        print("@@" + json.dumps({"by": rv["judgedBy"], "tiers": {x["id"]: x["tier"] for x in rv["items"]}}))
        '''))
        self.assertEqual(r, {"by": "rules", "tiers": {"c001": "primary", "c002": "optional", "c003": "keep"}})

    def test_ai_verbose_array(self):
        self.e.extra["FAKE_MODE"] = "verbose"
        r = self.e.run(textwrap.dedent(self.CAND) + textwrap.dedent(r'''
        from common import load_config, save_config
        import shutil
        c = load_config(); c.update(aiEngine="claude", claudePath=shutil.which("claude")); save_config(c)
        from classify import classify
        rv = classify(cand, log=lambda *a: None)
        print("@@" + json.dumps({"by": rv["judgedBy"], "tiers": {x["id"]: x["tier"] for x in rv["items"]}, "title": rv["items"][0]["title"]}))
        '''))
        self.assertEqual(r, {"by": "ai", "tiers": {"c001": "primary", "c002": "optional", "c003": "keep"}, "title": "AI:c001"})

    def test_no_engine(self):
        r = self.e.run(textwrap.dedent(self.CAND) + textwrap.dedent(r'''
        from classify import classify
        rv = classify(cand, log=lambda *a: None)
        print("@@" + json.dumps({"by": rv["judgedBy"], "n": len(rv["items"])}))
        '''))
        self.assertEqual(r, {"by": "rules", "n": 3})


class TestEngines(Base):
    def test_codex_readonly_and_model_fallback(self):
        (self.e.home / ".codex").mkdir()
        (self.e.home / ".codex/models_cache.json").write_text(json.dumps({"models": [
            {"slug": "bad-model", "visibility": "list", "priority": 1}, {"slug": "good-model", "visibility": "list", "priority": 2}]}))
        r = self.e.run(r'''
        import engines, shutil
        cfg = {"aiEngine": "codex", "codexPath": shutil.which("codex"), "codexModel": ""}
        print("@@" + json.dumps(list(engines.test(cfg, log=lambda *a: None))))
        ''')
        self.assertEqual(r, [True, "good-model", ""])
        ex = [c["args"] for c in self.e.calls() if c["bin"] == "codex" and "exec" in c["args"]]
        self.assertTrue(all(a[a.index("--sandbox") + 1] == "read-only" and "--ephemeral" in a for a in ex), "Codex 必须只读、不留会话")

    def test_claude_output_formats(self):
        """Claude 的 json 输出：对象、verbose 数组、数组里没有 result、非对象、纯文本，都不能崩。"""
        got = {}
        for mode in ("ok", "verbose", "verbose-noresult", "scalar", "text"):
            self.e.extra["FAKE_MODE"] = mode
            got[mode] = self.e.run(r'''
            import engines, shutil
            cfg = {"aiEngine": "claude", "claudePath": shutil.which("claude"), "claudeModel": ""}
            ok, model, err = engines.test(cfg, log=lambda *a: None)
            print("@@" + json.dumps([ok, err]))
            ''')
        self.assertEqual(got, {"ok": [True, ""], "verbose": [True, ""], "verbose-noresult": [False, ""],
                               "scalar": [False, ""], "text": [True, ""]})

    def test_names_and_find(self):
        r = self.e.run(r'''
        import engines
        print("@@" + json.dumps({"names": engines.NAMES, "claude": bool(engines.find("claude")), "codex": bool(engines.find("codex")),
              "logged": [engines.logged_in("claude", engines.find("claude")), engines.logged_in("codex", engines.find("codex"))]}))
        ''')
        self.assertEqual(r["names"]["claude"], "Claude Code")
        self.assertEqual(r["names"]["codex"], "Codex")
        self.assertTrue(r["claude"] and r["codex"])
        self.assertEqual(r["logged"], [True, True])

    def test_unknown_engine(self):
        r = self.e.run(r'''
        import engines
        try:
            engines.ask({"aiEngine": ""}, "hi"); print("@@" + json.dumps("no-error"))
        except engines.AIError:
            print("@@" + json.dumps("AIError"))
        ''')
        self.assertEqual(r, "AIError")


class TestNewEngines(Base):
    def test_workbuddy_no_tools(self):
        r = self.e.run(r'''
        import engines, shutil
        print("@@" + json.dumps(list(engines.test({"aiEngine": "workbuddy", "workbuddyPath": shutil.which("codebuddy")}, log=lambda *a: None))))
        ''')
        self.assertEqual(r, [True, "", ""])
        a = [c["args"] for c in self.e.calls() if c["bin"] == "codebuddy" and "-p" in c["args"]][0]
        self.assertEqual(a[a.index("--tools") + 1], "", "WorkBuddy 必须关掉全部工具")
        self.assertIn("--no-session-persistence", a)
        self.assertEqual(a[a.index("--output-format") + 1], "text", "json 模式输出过长会被截断")

    def test_deepseek_patch_and_key(self):
        r = self.e.run(r'''
        import engines, shutil
        cfg = {"aiEngine": "deepseek", "deepseekPath": shutil.which("dsh")}
        no_key = engines.test(cfg, log=lambda *a: None)
        engines.save_deepseek_key("sk-test")
        import os, stat
        mode = oct(os.stat(engines.SECRETS).st_mode & 0o777)
        print("@@" + json.dumps({"no_key": list(no_key), "ok": list(engines.test(cfg, log=lambda *a: None)), "mode": mode}))
        ''')
        self.assertFalse(r["no_key"][0])
        self.assertEqual(r["ok"], [True, "", ""])
        if not WIN:
            self.assertEqual(r["mode"], "0o600")
        run = [c for c in self.e.calls() if c["bin"] == "dsh" and "-" in c["args"]][0]
        self.assertIn("--patch", run["args"]); self.assertEqual(run["key"], "sk-test")

    def test_deepseek_refuses_without_patch(self):
        r = self.e.run(r'''
        import engines, shutil
        engines.DSH_PATCH = engines.Path("/nonexistent.yml")
        engines.save_deepseek_key("sk-test")
        print("@@" + json.dumps(list(engines.test({"aiEngine": "deepseek", "deepseekPath": shutil.which("dsh")}, log=lambda *a: None))))
        ''')
        self.assertFalse(r[0]); self.assertIn("工具", r[2])
        self.assertFalse([c for c in self.e.calls() if c["bin"] == "dsh" and "-" in c["args"]], "工具没关掉时绝不能真正调用")

    def test_installer_choice_compat(self):
        r = self.e.run(r'''
        import installer
        res = {}
        for ans in ("", "1", "2", "3", "4", "codex", "9"):
            installer.ask = lambda prompt, default="", a=ans: a or default
            installer.has_tty = lambda: True
            res[ans or "回车"] = installer.choose_engine([])
        print("@@" + json.dumps(res))
        ''')
        self.assertEqual(r, {"回车": "claude", "1": "claude", "2": "codex", "3": "workbuddy", "4": "deepseek", "codex": "codex", "9": "claude"})


class TestConfig(Base):
    def test_defaults(self):
        r = self.e.run(r'''
        from common import load_config
        print("@@" + json.dumps(load_config()))
        ''')
        for k, v in {"thresholdGB": 15, "intervalMinutes": 30, "cooldownHours": 6, "optionalAction": "trash", "protect": [], "aiEngine": ""}.items():
            self.assertEqual(r[k], v, k)

    def test_migrate_v01(self):
        (self.e.home / ".purrge").mkdir()
        (self.e.home / ".purrge/config.json").write_text(json.dumps({"thresholdGB": 20, "claudePath": "/x/claude", "aiModel": "m1"}))
        r = self.e.run(r'''
        from common import load_config
        print("@@" + json.dumps(load_config()))
        ''')
        self.assertEqual((r["aiEngine"], r["claudeModel"], r["thresholdGB"], "aiModel" in r), ("claude", "m1", 20, False))


class TestPlatform(Base):
    """两个系统实现的接口必须一致（防止只改了一边）。"""
    def test_same_interface(self):
        import ast
        names = {}
        for f in ("mac.py", "win.py"):
            tree = ast.parse((LIB / "plat" / f).read_text(encoding="utf-8"))
            names[f] = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")} | \
                       {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name) and t.id.isupper() and not t.id.startswith("_")}
        self.assertEqual(names["mac.py"], names["win.py"])

    def test_rules_valid(self):
        for f in ("registry.json", "registry.win.json"):
            r = json.loads((ROOT / "runtime/rules" / f).read_text(encoding="utf-8"))
            self.assertTrue({"rules", "genericCacheRoots", "largeScan", "protected"} <= set(r), f)
            for rule in r["rules"]:
                self.assertTrue({"id", "name", "paths", "mode", "tier"} <= set(rule), (f, rule.get("id")))
                self.assertIn(rule["tier"], ("primary", "optional", "keep"))
            self.assertIn("~/.purrge", r["protected"], f)


class TestNodeAutoInstall(Base):
    """没有 Node.js 时自动安装：已有 npm 不动、用户拒绝不装、官方压缩包核对 SHA256、装好后能用来装 WorkBuddy。"""

    SETUP = r'''
    import os, sys, io, hashlib, tarfile, zipfile, shutil
    from pathlib import Path
    H = Path.home()
    empty = H / "emptybin"; empty.mkdir(exist_ok=True)
    os.environ["PATH"] = str(empty)             # 模拟电脑上没有 node / npm / brew
    WIN = sys.platform == "win32"
    def make_dist(bad_sum=False):
        import nodejs
        dist = H / "dist"; ver = "v22.1.0"; (dist / ver).mkdir(parents=True, exist_ok=True)
        (dist / "index.json").write_text(json.dumps([{"version": "v23.0.0", "lts": False}, {"version": ver, "lts": "Jod"}]))
        name = f"node-{ver}-{'win' if WIN else 'darwin'}-{nodejs._arch()}"
        npm_py = ("import os, sys, pathlib\n"
                  "a = sys.argv[1:]\n"
                  "if a[:2] == ['prefix', '-g']: print(os.environ['npm_config_prefix']); sys.exit(0)\n"
                  "pre = pathlib.Path(os.environ['npm_config_prefix'])\n"
                  "open(pre / 'npm-calls.txt', 'a').write(' '.join(a) + '\\n')\n"
                  "if os.name == 'nt': (pre / 'codebuddy.cmd').write_text('@echo 2.0.0\\r\\n')\n"
                  "else:\n"
                  "    (pre / 'bin').mkdir(exist_ok=True); f = pre / 'bin' / 'codebuddy'; f.write_text('#!/bin/sh\\necho 2.0.0\\n'); f.chmod(0o755)\n")
        buf = io.BytesIO()
        if WIN:
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr(f"{name}/npm.py", npm_py)
                z.writestr(f"{name}/npm.cmd", f'@"{sys.executable}" "%~dp0npm.py" %*\r\n')
            fname = name + ".zip"
        else:
            with tarfile.open(fileobj=buf, mode="w:gz") as t:
                data = (f"#!{sys.executable}\n" + npm_py).encode()
                ti = tarfile.TarInfo(f"{name}/bin/npm"); ti.size = len(data); ti.mode = 0o755
                t.addfile(ti, io.BytesIO(data))
            fname = name + ".tar.gz"
        (dist / ver / fname).write_bytes(buf.getvalue())
        h = "0" * 64 if bad_sum else hashlib.sha256(buf.getvalue()).hexdigest()
        (dist / ver / "SHASUMS256.txt").write_text(f"{h}  {fname}\n{'1'*64}  other.tar.gz\n")
        nodejs.DIST = dist.as_uri()
    '''

    def test_existing_npm_untouched(self):
        r = self.e.run(textwrap.dedent(self.SETUP) + textwrap.dedent(r'''
        npm = empty / ("npm.cmd" if WIN else "npm"); npm.write_text("@echo 1\r\n" if WIN else "#!/bin/sh\necho 1\n"); npm.chmod(0o755)
        import nodejs
        nodejs.DIST = "http://127.0.0.1:9/never"   # 已有 npm 时绝不能联网下载
        got = nodejs.ensure(say=lambda m: None, confirm=lambda q: 1/0)
        e = nodejs.env()
        print("@@" + json.dumps([os.path.normcase(got) == os.path.normcase(str(npm)), (H / ".purrge/node").exists(), "npm_config_prefix" in e, e["PATH"] == os.environ["PATH"]]))
        '''))
        self.assertEqual(r, [True, False, False, True], "已经有 npm 时：不问、不下载、不改环境变量")

    def test_declined(self):
        r = self.e.run(textwrap.dedent(self.SETUP) + textwrap.dedent(r'''
        make_dist()
        import nodejs
        asked = []
        got = nodejs.ensure(say=lambda m: None, confirm=lambda q: asked.append(q) or False)
        print("@@" + json.dumps([got, len(asked), (H / ".purrge/node").exists()]))
        '''))
        self.assertEqual(r, [None, 1, False])

    def test_portable_install_and_workbuddy(self):
        r = self.e.run(textwrap.dedent(self.SETUP) + textwrap.dedent(r'''
        make_dist()
        import nodejs, engines
        p = engines.install("workbuddy", say=lambda m: None, confirm=lambda q: True)
        calls = (H / ".purrge/node/npm-calls.txt").read_text()
        print("@@" + json.dumps([bool(nodejs.npm()), str(H / ".purrge/node") in (p or ""), engines.version_text(p), "@tencent-ai/codebuddy-code@latest" in calls,
                                 nodejs.env()["npm_config_prefix"] == str(H / ".purrge/node")]))
        '''))
        self.assertEqual(r, [True, True, "2.0.0", True, True])

    def test_checksum_mismatch(self):
        r = self.e.run(textwrap.dedent(self.SETUP) + textwrap.dedent(r'''
        make_dist(bad_sum=True)
        import nodejs
        msgs = []
        got = nodejs.ensure(say=msgs.append, confirm=lambda q: True)
        print("@@" + json.dumps([got, (H / ".purrge/node").exists(), any("校验" in m for m in msgs)]))
        '''))
        self.assertEqual(r, [None, False, True], "校验不通过必须拒绝安装")


class TestUpdate(Base):
    """purrge update：成功更新保留设置；新版本坏了自动换回旧版本；已是最新不动。"""

    def setUp(self):
        super().setUp()
        import shutil
        self.ph = self.e.home / ".purrge"
        self.app = self.ph / "app"
        shutil.copytree(ROOT / "runtime", self.app, ignore=shutil.ignore_patterns("__pycache__"))
        self._set_version(self.app, "0.2.2")            # 模拟装着旧版本
        (self.ph / "config.json").write_text(json.dumps({"thresholdGB": 9, "intervalMinutes": 60, "optionalAction": "delete", "protect": ["~/x"]}))
        (self.ph / "runs/20261020-000000").mkdir(parents=True)

    def _set_version(self, runtime, v):
        import re
        f = runtime / "lib/common.py"
        f.write_text(re.sub(r'VERSION = "[^"]+"', f'VERSION = "{v}"', f.read_text(encoding="utf-8")), encoding="utf-8")

    def _ver(self, runtime):
        import re
        return re.search(r'VERSION = "([^"]+)"', (runtime / "lib/common.py").read_text(encoding="utf-8")).group(1)

    def update(self, src, cli=None):
        env = dict(os.environ, HOME=str(self.e.home), USERPROFILE=str(self.e.home), PURRGE_HOME=str(self.ph), PYTHONUTF8="1",
                   PURRGE_NO_UPDATE_CHECK="1", PURRGE_TEST_NO_MONITOR="1")
        return subprocess.run([sys.executable, str((cli or self.app) / "lib/dg.py"), "update", "--from", str(src)], capture_output=True,
                              text=True, encoding="utf-8", env=env, timeout=180)

    def test_update_ok(self):
        before = (self.ph / "config.json").read_text()
        p = self.update(ROOT)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self._ver(self.app), self._ver(ROOT / "runtime"))
        self.assertEqual(self._ver(self.ph / "app.bak"), "0.2.2", "旧版本要留备份")
        self.assertEqual((self.ph / "config.json").read_text(), before, "设置不能被改动")
        self.assertTrue((self.ph / "runs/20261020-000000").is_dir(), "扫描记录要保留")
        self.assertEqual(json.loads((self.ph / "monitor.test").read_text())["interval"], 60, "用原来的检查频率重新注册后台任务")

    def test_update_rollback(self):
        import shutil
        bad = Path(self.e.tmp.name) / "bad"
        shutil.copytree(ROOT, bad, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self._set_version(bad / "runtime", "9.9.9")
        (bad / "runtime/web/review.html").unlink()       # 新版本缺文件 → 自检必须失败
        p = self.update(bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self._ver(self.app), "0.2.2", "自检失败要自动换回旧版本")
        self.assertTrue((self.app / "web/review.html").is_file())
        self.assertIn("已恢复到 0.2.2", p.stdout)

    def test_already_latest(self):
        self._set_version(self.app, self._ver(ROOT / "runtime"))
        p = self.update(ROOT)
        self.assertEqual(p.returncode, 0)
        self.assertIn("已经是最新版本", p.stdout)
        self.assertFalse((self.ph / "app.bak").exists())

    def test_sync_stale_app(self):
        """只做了 brew upgrade：命令行（仓库里的新版）已是新版、后台程序还是 0.2.2 → update 要同步、留备份、保留设置。"""
        before = (self.ph / "config.json").read_text()
        p = self.update(ROOT, cli=ROOT / "runtime")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("后台程序还是 0.2.2", p.stdout)
        self.assertEqual(self._ver(self.app), self._ver(ROOT / "runtime"))
        self.assertEqual(self._ver(self.ph / "app.bak"), "0.2.2")
        self.assertEqual((self.ph / "config.json").read_text(), before)
        p = self.update(ROOT, cli=ROOT / "runtime")
        self.assertIn("已经是最新版本", p.stdout)

    def test_never_downgrade(self):
        """下载到的代码比已装的旧（比如 master 还没发布新版）：不能把后台程序降级。"""
        import shutil
        old = Path(self.e.tmp.name) / "old"
        shutil.copytree(ROOT, old, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self._set_version(old / "runtime", "0.1.0")
        self._set_version(self.app, self._ver(ROOT / "runtime"))
        p = self.update(old, cli=ROOT / "runtime")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("已经是最新版本", p.stdout)
        self.assertEqual(self._ver(self.app), self._ver(ROOT / "runtime"))
        self.assertFalse((self.ph / "app.bak").exists())

    def test_version_compare(self):
        r = self.e.run(r'''
        import update
        print("@@" + json.dumps([update.newer("0.3.0", "0.3.0-beta"), update.newer("0.3.0-beta", "0.2.2"), update.newer("0.2.2", "0.3.0-beta"),
              update.newer("0.3.0", "0.3.0"), update.check_latest(), update.available()]))
        ''')
        self.assertEqual(r, [True, True, False, False, None, None])


class TestCLI(Base):
    def cli(self, *args):
        env = dict(os.environ, HOME=str(self.e.home), USERPROFILE=str(self.e.home), PURRGE_HOME=str(self.e.home / ".purrge"), FAKE_LOG=str(self.e.log),
                   PATH=f"{self.e.bin}{os.pathsep}{os.environ.get('PATH', '')}", PYTHONUTF8="1",
                   PURRGE_NO_UPDATE_CHECK="1", PURRGE_TEST_NO_MONITOR="1")
        return subprocess.run([sys.executable, str(LIB / "dg.py"), *args], capture_output=True, text=True, env=env, timeout=60, encoding="utf-8")

    def test_version_help(self):
        self.assertIn("by RabbittuX", self.cli("version").stdout)
        out = self.cli().stdout
        for cmd in ("install", "scan", "status", "engine", "config", "review", "uninstall"):
            self.assertIn(cmd, out)

    def test_config_set(self):
        out = self.cli("config", "thresholdGB", "20").stdout
        self.assertEqual(json.loads(out)["thresholdGB"], 20)
        self.assertEqual(json.loads((self.e.home / ".purrge/config.json").read_text())["thresholdGB"], 20)

    def test_status(self):
        s = json.loads(self.cli("status").stdout)
        for k in ("free", "total", "thresholdGB", "belowThreshold", "monitor", "intervalMinutes", "lastRun", "ai"):
            self.assertIn(k, s)


class TestWindowsRules(Base):
    """保护名单不能把规则库里的缓存目录一起盖掉（否则规则永远不生效）。"""

    @unittest.skipUnless(WIN, "Windows 规则只在 Windows 上生效")
    def test_edge_cache_not_shadowed(self):
        r = self.e.run(r'''
        from common import expand, is_protected, load_config, load_rules
        rules, cfg = load_rules(), load_config()
        edge = next(x for x in rules["rules"] if x["id"] == "edge-cache")
        out = {p.split("/")[-1]: is_protected(expand(p.replace("*", "Default")), cfg, rules) for p in edge["paths"]}
        out.update({
            "dpapi": is_protected(expand("%LOCALAPPDATA%/Microsoft/Credentials"), cfg, rules),
            "appdata_ms": is_protected(expand("%APPDATA%/Microsoft"), cfg, rules),
            "chrome": is_protected(expand("%LOCALAPPDATA%/Google/Chrome/User Data/Default/Cache"), cfg, rules),
            "system": is_protected(expand("%SystemRoot%"), cfg, rules)})
        print("@@" + json.dumps(out))
        ''')
        self.assertEqual(r, {"Cache": False, "Code Cache": False, "dpapi": True,
                             "appdata_ms": True, "chrome": False, "system": True})

    @unittest.skipUnless(WIN, "Windows 规则只在 Windows 上生效")
    def test_edge_profile_state_still_protected(self):
        r = self.e.run(r'''
        from common import expand, is_protected, load_config, load_rules
        rules, cfg = load_rules(), load_config()
        ud = "%LOCALAPPDATA%/Microsoft/Edge/User Data/"
        names = ["Profile 1/Cache", "Default/Login Data", "Profile 1/Login Data", "Default/Cookies", "Default/Bookmarks",
                 "Local State", "Default", "", "../../Outlook", "../../Windows/UsrClass.dat"]
        print("@@" + json.dumps({n: is_protected(expand(ud + n), cfg, rules) for n in names}))
        ''')
        self.assertEqual(r, {"Profile 1/Cache": False, **{n: True for n in list(r)[1:]}})

    def test_protect_exempt(self):
        """protectExempt 只放行宽泛的上层保护：用户保护、自身/内部受保护、软链接指向别处都照旧。"""
        r = self.e.run(r'''
        import os
        from pathlib import Path
        from common import is_protected
        ms = Path.home() / "AppData/Local/Microsoft"; ud = ms / "Edge/User Data"
        for d in ["Default/Cache/data", "Profile 1/Code Cache", "Default/Cache2", "Default/Network"]:
            (ud / d).mkdir(parents=True)
        (ms / "Outlook").mkdir()
        (ud / "Evil").mkdir()
        if os.name != "nt":                        # Windows 建软链接要管理员/开发者模式
            os.symlink(ms / "Outlook", ud / "Evil/Cache", target_is_directory=True)
        rules = {"protected": [str(ms), str(ud / "Default/Cache/keep")],
                 "protectExempt": [str(ud / "*/Cache"), str(ud / "*/Code Cache")]}
        P = lambda n, cfg={}: is_protected(ud / n, cfg, rules)
        print("@@" + json.dumps({
            "default_cache": P("Default/Cache/data"), "profile1_code": P("Profile 1/Code Cache"),
            "cache2": P("Default/Cache2"), "network": P("Default/Network"), "profile": P("Default"),
            "local_state": P("Local State"), "outlook": is_protected(ms / "Outlook", {}, rules),
            "keep_inside": P("Default/Cache/keep"), "cache_parent_of_keep": P("Default/Cache"),
            "symlink_escape": P("Evil/Cache") if os.name != "nt" else True,
            "user_wins": P("Profile 1/Code Cache", {"protect": [str(ud / "Profile 1")]})}))
        ''')
        self.assertEqual(r, {"default_cache": False, "profile1_code": False, "cache2": True, "network": True,
                             "profile": True, "local_state": True, "outlook": True, "keep_inside": True,
                             "cache_parent_of_keep": True, "symlink_escape": True, "user_wins": True})


class TestScanAndServer(Base):
    def test_scan_shape(self):
        (self.e.home / "Library/Caches/Big").mkdir(parents=True)
        r = self.e.run(r'''
        from scan import scan
        c = scan(progress=lambda *a: None)
        print("@@" + json.dumps({"keys": sorted(c.keys()), "items": c["items"][:3]}))
        ''')
        self.assertTrue({"items", "freeBytes", "totalBytes"} <= set(r["keys"]))

    def test_server(self):
        r = self.e.run(r'''
        import threading, time, urllib.request
        from pathlib import Path
        from common import new_run_dir
        d = new_run_dir()
        (d / "review.json").write_text(json.dumps({"items": [{"id": "c1", "path": str(Path.home()), "kind": "cache"}], "summary": "", "judgedBy": "rules"}))
        from server import serve
        threading.Thread(target=serve, args=(d,), kwargs={"open_browser": False, "log": lambda *a: None}, daemon=True).start()
        for _ in range(300):
            if (d / "review-url.txt").exists(): break
            time.sleep(0.1)
        url = (d / "review-url.txt").read_text(); base = url.split("/?")[0]; tok = url.split("token=")[1]
        def call(p, body=None, token=tok):
            req = urllib.request.Request(base + p, data=json.dumps(body).encode() if body is not None else None, headers={"X-DG-Token": token, "Content-Type": "application/json"})
            try:
                return json.loads(urllib.request.urlopen(req).read())
            except urllib.error.HTTPError as e:
                return {"http": e.code}
        print("@@" + json.dumps({"page": urllib.request.urlopen(url).status, "review": sorted(call("/api/review").keys()),
              "bad": call("/api/review", token="nope"), "reveal_unknown": call("/api/reveal", {"id": "zzz"})}))
        ''')
        self.assertEqual(r["page"], 200)
        self.assertEqual(r["review"], ["config", "freeBytes", "review", "totalBytes"])
        self.assertEqual(r["bad"], {"http": 403})
        self.assertEqual(r["reveal_unknown"], {"ok": False})



class TestLifecycle(Base):
    """完整生命周期：安装 → 手动扫描 → 审查页 → 卸载干净（都在临时 HOME 里，不碰真实的后台任务和浏览器）。"""

    def setUp(self):
        super().setUp()
        (self.e.home / ".claude").mkdir()                      # 让安装程序给 Claude Code 放说明文件
        self.e.extra = {"LOCALAPPDATA": str(self.e.home / "AppData/Local"), "APPDATA": str(self.e.home / "AppData/Roaming")}

    def test_install_then_uninstall(self):
        r = self.e.run(r'''
        import os, subprocess
        from pathlib import Path
        H, P = Path.home(), Path(os.environ["PURRGE_HOME"])
        dg = str(Path(sys.path[0]) / "dg.py")
        def sh(*a):
            return subprocess.run([sys.executable, *a], capture_output=True, text=True, encoding="utf-8")
        a = sh(dg, "install", "--engine", "claude", "--threshold", "15", "--yes")
        import installer
        cli = [c for c in (installer.CLI_LINK, installer.WIN_CLI) if c.exists() or c.is_symlink()]
        before = {"app": (P / "app/lib/dg.py").is_file(), "skill": (H / ".claude/skills/purrge/SKILL.md").is_file(),
                  "monitor": (P / "monitor.test").is_file(), "threshold": json.loads((P / "config.json").read_text())["thresholdGB"],
                  "engine": json.loads((P / "config.json").read_text())["aiEngine"]}
        b = sh(str(P / "app/lib/dg.py"), "uninstall", "--purge")
        import time
        for _ in range(40):                                    # Windows 的 purrge.cmd 由后台小任务在命令结束后约 2 秒删除
            if not any(c.exists() or c.is_symlink() for c in cli):
                break
            time.sleep(0.25)
        after = {"home": P.exists(), "skill": (H / ".claude/skills/purrge").exists(), "cli": [str(c) for c in cli if c.exists() or c.is_symlink()]}
        print("@@" + json.dumps({"rc": [a.returncode, b.returncode], "before": before, "after": after, "log": (a.stdout + a.stderr)[-800:] + b.stdout}))
        ''')
        self.assertEqual(r["rc"], [0, 0], r["log"])
        self.assertEqual(r["before"], {"app": True, "skill": True, "monitor": True, "threshold": 15, "engine": "claude"})
        self.assertEqual(r["after"], {"home": False, "skill": False, "cli": []}, "卸载后设置、程序、说明文件、purrge 命令都要删掉")

    def test_manual_scan_to_review(self):
        (self.e.home / "Library/Caches/SomeApp").mkdir(parents=True)
        (self.e.home / "Library/Caches/SomeApp/blob.bin").write_bytes(b"x" * 4096)
        r = self.e.run(r'''
        import threading, time, urllib.request, shutil
        from pathlib import Path
        from common import load_config, save_config, DG_HOME
        c = load_config(); c["aiEngine"] = "claude"; c["claudePath"] = shutil.which("claude"); save_config(c)
        import dg
        dg.notify = lambda *a: None                            # 测试里不弹真实通知
        threading.Thread(target=dg.cmd_run, args=(["--no-open"],), daemon=True).start()
        url = None
        for _ in range(600):
            f = list((DG_HOME / "runs").glob("*/review-url.txt")) if (DG_HOME / "runs").exists() else []
            if f:
                url = f[0].read_text(); break
            time.sleep(0.1)
        run = f[0].parent
        rv = json.loads((run / "review.json").read_text(encoding="utf-8"))
        base, tok = url.split("/?")[0], url.split("token=")[1]
        req = urllib.request.Request(base + "/api/close", data=b"{}", headers={"X-DG-Token": tok, "Content-Type": "application/json"})
        closed = json.loads(urllib.request.urlopen(req).read())
        print("@@" + json.dumps({"cand": (run / "candidates.json").is_file(), "judgedBy": rv.get("judgedBy"),
                                 "page": urllib.request.urlopen(url).status, "closed": closed}))
        ''')
        self.assertIn(r.pop("judgedBy"), ("ai", "rules"))         # 判断本身由 TestClassify 覆盖，这里只看流程走通
        self.assertEqual(r, {"cand": True, "page": 200, "closed": {"ok": True}})


if __name__ == "__main__":
    unittest.main()
