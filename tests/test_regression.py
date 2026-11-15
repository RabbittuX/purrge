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
if mode == "notloggedin":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in · Please run /login"})); sys.exit(1)
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
# 假的 pi：--help 里有关工具的开关；真正调用时按 --mode 输出 Pi 的 JSONL 事件流
FAKE["pi"] = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"bin": "pi", "args": args}) + "\n")
if "--version" in args:
    print("9.9.9"); sys.exit(0)
if "--help" in args:
    if os.environ.get("FAKE_PI_NO_FLAGS"):
        print("Usage: pi [options] [messages...]"); sys.exit(0)
    for f in ("--no-tools", "--exclude-tools", "--no-mcp", "--no-extensions", "--no-session", "--mode", "--print", "--tools"):
        print(f"  {f} <x>   something")
    sys.exit(0)
src = sys.stdin.read()
mode = os.environ.get("FAKE_MODE", "ok")
model = args[args.index("--model") + 1] if "--model" in args else ""
ev = lambda o: print(json.dumps(o, ensure_ascii=False), flush=True)
ev({"type": "session", "version": 3, "id": "fake"})
# 系统消息里带着这次交给模型的工具清单：没关干净时这里就不是 (none)
tools = "(none)" if ("--no-tools" in args and "--exclude-tools" in args and "*" in args) else "- bash: Run commands"
ev({"type": "message_end", "message": {"role": "system", "content": "", "sections": {"tools": "<tools>\n" + tools + "\n</tools>"}}})
if mode == "fail-model" and model and model != "fake/good-model":
    sys.stderr.write('Error: Model "' + model + '" not found. Use --list-models to see available models.')
    sys.exit(1)
m = json.loads(os.environ.get("FAKE_PI_ITEMS", "[]"))
out = {"summary": "测试总结", "items": [{"id": it["id"], "tier": "primary", "title": "AI:" + it["id"], "reason": "AI 理由", "category": "测试"} for it in m]}
text = {"ok": "这是结果：" + json.dumps(out, ensure_ascii=False), "text": "OK", "empty": "",
        "fail-model": "这是结果：" + json.dumps(out, ensure_ascii=False),
        "toolcall": "这是结果：" + json.dumps(out, ensure_ascii=False)}[mode]
if mode == "toolcall":     # 工具没关干净：事件流里会出现工具调用
    ev({"type": "tool_execution_start", "toolCallId": "t1", "toolName": "bash", "args": {}})
if mode == "empty":
    sys.exit(0)
ev({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                                      "provider": "fake", "model": model or "default-model", "stopReason": "stop"}})
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



class TestCleanRobust(Base):
    """#6：移到回收站这一步出任何异常都不能中断整批，也不能让审查页一直转圈。"""

    def test_trash_error_does_not_abort_batch(self):
        h = self.e.home
        (h / "a.mov").write_bytes(b"x" * 8192)
        (h / "moved.mov").write_bytes(b"x" * 8192)
        (h / "cache").mkdir(); (h / "cache/x.bin").write_bytes(b"x" * 4096)
        r = self.e.run(r"""
        import os, shutil
        from pathlib import Path
        import clean as C
        H = Path.home()
        def bad_trash(path):
            if path.endswith("moved.mov"):              # 接口报错，但文件其实已经移走了
                shutil.move(path, str(H / "elsewhere.mov"))
            raise AttributeError("'NoneType' object has no attribute 'strip'")
        C._to_trash = bad_trash
        m = lambda p: os.stat(p).st_mtime
        items = [
          {"id": "c1", "path": str(H/"a.mov"), "kind": "large-file", "mode": "whole", "tier": "optional", "mtimeAtScan": m(H/"a.mov")},
          {"id": "c2", "path": str(H/"moved.mov"), "kind": "large-file", "mode": "whole", "tier": "optional", "mtimeAtScan": m(H/"moved.mov")},
          {"id": "c3", "path": str(H/"cache"), "kind": "cache", "mode": "contents", "tier": "primary"},
        ]
        out = C.clean({"items": items}, ["c1", "c2", "c3"], log=lambda *a: None)
        print("@@" + json.dumps({x["id"]: [x["status"], x.get("trashedBytes", 0) > 0] for x in out["results"]}
                                | {"a_kept": (H/"a.mov").exists(), "cache_empty": not any((H/"cache").iterdir())}))
        """)
        self.assertEqual(r["c1"], ["failed", False])
        self.assertEqual(r["c2"], ["trashed", True], "报错但文件已移走：如实显示已移到回收站")
        self.assertEqual(r["c3"], ["deleted", False], "前面的项失败，后面的项照常清理")
        self.assertTrue(r["a_kept"] and r["cache_empty"])

    def test_win_to_trash_stderr_none(self):
        r = self.e.run(r"""
        import subprocess, sys
        from pathlib import Path
        sys.modules["send2trash"] = None                 # 强制走 PowerShell 路径
        from plat import win
        win._ps = lambda script, timeout=60: subprocess.CompletedProcess(["powershell"], 1, "", None)
        try:
            win.to_trash(str(Path.home()), Path.home()); res = "ok"
        except Exception as e:
            res = type(e).__name__
        print("@@" + json.dumps(res))
        """)
        self.assertEqual(r, "OSError")

    def test_server_clean_always_json(self):
        r = self.e.run(r"""
        import threading, time, urllib.request
        from pathlib import Path
        from common import new_run_dir
        import server
        def boom(*a, **k): raise RuntimeError("boom")
        server.clean = boom
        d = new_run_dir()
        (d / "review.json").write_text(json.dumps({"items": [], "summary": "", "judgedBy": "rules"}))
        threading.Thread(target=server.serve, args=(d,), kwargs={"open_browser": False, "log": lambda *a: None}, daemon=True).start()
        for _ in range(300):
            if (d / "review-url.txt").exists(): break
            time.sleep(0.1)
        url = (d / "review-url.txt").read_text(); base = url.split("/?")[0]; tok = url.split("token=")[1]
        req = urllib.request.Request(base + "/api/clean", data=b'{"ids": []}', headers={"X-DG-Token": tok, "Content-Type": "application/json"})
        print("@@" + json.dumps(json.loads(urllib.request.urlopen(req, timeout=30).read())))
        """)
        self.assertEqual(r["results"], [])
        self.assertIn("boom", r["error"])

    @unittest.skipUnless(WIN, "只在 Windows 上有 PowerShell")
    def test_win_ps_gbk_output(self):
        r = self.e.run(r"""
        from plat import win
        a = win._ps("[Console]::OutputEncoding=[Text.Encoding]::GetEncoding(936); Write-Error '无法访问路径'; exit 1")
        b = win._ps("Write-Output '中文输出测试'")
        c = win._ps("Write-Output 42")
        print("@@" + json.dumps({"a": type(a.stderr).__name__, "b": b.stdout.strip(), "c": c.stdout}))
        """)
        self.assertEqual(r, {"a": "str", "b": "中文输出测试", "c": "42\n"})

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
        empty = "AI 没有返回任何内容"
        self.assertEqual(got, {"ok": [True, ""], "verbose": [True, ""], "verbose-noresult": [False, empty],
                               "scalar": [False, empty], "text": [True, ""]})

    def test_claude_not_logged_in(self):
        """#8：未登录时 claude 输出 is_error=true 的 result，连接测试和逐项判断都不能当成 AI 回答。"""
        self.e.extra["FAKE_MODE"] = "notloggedin"
        r = self.e.run(textwrap.dedent(TestClassify.CAND) + textwrap.dedent(r'''
        import engines, shutil
        from common import load_config, save_config
        from classify import classify
        cfg = {"aiEngine": "claude", "claudePath": shutil.which("claude"), "claudeModel": ""}
        ok, model, err = engines.test(cfg, log=lambda *a: None)
        c = load_config(); c.update(cfg); save_config(c)
        logs = []
        rv = classify(cand, log=logs.append)
        print("@@" + json.dumps({"test": [ok, err], "by": rv["judgedBy"], "why": " ".join(logs)}))
        '''))
        self.assertEqual(r["test"], [False, "Not logged in · Please run /login"])
        self.assertEqual(r["by"], "rules")
        self.assertIn("Not logged in", r["why"], "日志里要能看到真实原因")

    def test_desktop_cli_paths(self):
        """#8：Windows 上 Codex / Claude 桌面版自带、但不在 PATH 里的命令行。"""
        r = self.e.run(r'''
        import engines
        from pathlib import Path
        local = Path.home() / "LocalAppData"
        for rel in ("OpenAI/Codex/bin/a1/codex.exe", "Claude-3p/claude-code/2.1.309/9078/claude.exe", "Claude-3p/claude-code-vm/x/claude.exe"):
            (local / rel).parent.mkdir(parents=True); (local / rel).write_bytes(b"MZ")
        (local / "OpenAI/Codex/bin/not-a-file/codex.exe").mkdir(parents=True)
        rel = lambda xs: sorted(Path(x).relative_to(local).as_posix() for x in xs)
        print("@@" + json.dumps({e: rel(engines._desktop_paths(e, local)) for e in ("codex", "claude", "workbuddy")}))
        ''')
        self.assertEqual(r, {"codex": ["OpenAI/Codex/bin/a1/codex.exe"],
                             "claude": ["Claude-3p/claude-code-vm/x/claude.exe", "Claude-3p/claude-code/2.1.309/9078/claude.exe"],
                             "workbuddy": []})

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
        for ans in ("", "1", "2", "3", "4", "5", "codex", "9"):
            installer.ask = lambda prompt, default="", a=ans: a or default
            installer.has_tty = lambda: True
            res[ans or "回车"] = installer.choose_engine([])
        print("@@" + json.dumps(res))
        ''')
        self.assertEqual(r, {"回车": "claude", "1": "claude", "2": "codex", "3": "workbuddy", "4": "deepseek",
                             "5": "pi", "codex": "codex", "9": "claude"})

    def test_pi_caller_detected(self):
        """Pi 里跑 purrge install 时，要能认出是 Pi 在代为安装。"""
        self.e.extra["PI_CODING_AGENT"] = "true"
        r = self.e.run(r'''
        import installer
        installer.has_tty = lambda: False
        print("@@" + json.dumps(installer.choose_engine([])))
        ''')
        self.assertEqual(r, "pi")


class TestPiEngine(Base):
    """Pi（pi.dev）：关掉全部工具、只认 JSONL 里的助手回复、模型不可用时退回默认模型。"""

    def test_pi_no_tools_and_reply(self):
        r = self.e.run(r'''
        import engines, shutil, json
        cfg = {"aiEngine": "pi", "piPath": shutil.which("pi")}
        print("@@" + json.dumps(list(engines.test(cfg, log=lambda *a: None))))
        ''')
        self.assertEqual(r, [True, "", ""])
        a = [c["args"] for c in self.e.calls() if c["bin"] == "pi" and "--print" in c["args"]][0]
        self.assertIn("--no-tools", a)
        self.assertEqual(a[a.index("--exclude-tools") + 1], "*", "最后一道过滤：连扩展塞进来的工具也要关掉")
        self.assertIn("--no-session", a)
        self.assertIn("--no-extensions", a, "用户装的扩展不能参与判断（它们可能自带工具）")
        self.assertEqual(a[a.index("--mode") + 1], "json")

    def test_pi_refuses_without_tool_flags(self):
        """pi 版本变化、帮助里找不到关工具的开关时，宁可不用也不能让它带着工具跑。"""
        self.e.extra["FAKE_PI_NO_FLAGS"] = "1"
        r = self.e.run(r'''
        import engines, shutil
        print("@@" + json.dumps(list(engines.test({"aiEngine": "pi", "piPath": shutil.which("pi")}, log=lambda *a: None))))
        ''')
        self.assertFalse(r[0]); self.assertIn("工具", r[2])
        self.assertFalse([c for c in self.e.calls() if c["bin"] == "pi" and "--print" in c["args"]],
                         "工具没关掉时绝不能真正调用")

    def test_pi_tool_call_rejected(self):
        """事件流里出现工具调用 = 没关干净，这次结果不能用。"""
        self.e.extra["FAKE_MODE"] = "toolcall"
        r = self.e.run(r'''
        import engines, shutil
        try:
            engines.ask({"aiEngine": "pi", "piPath": shutil.which("pi")}, "hi", log=lambda *a: None)
            print("@@" + json.dumps("no-error"))
        except engines.AIError as e:
            print("@@" + json.dumps(str(e)))
        ''')
        self.assertIn("工具", r)

    def test_pi_model_fallback(self):
        """指定的模型不可用（名字写错 / 来源分不清）时，退回 Pi 当前的默认模型。"""
        self.e.extra["FAKE_MODE"] = "fail-model"
        r = self.e.run(r'''
        import engines, shutil
        cfg = {"aiEngine": "pi", "piPath": shutil.which("pi"), "piModel": "bad-model"}
        logs = []
        print("@@" + json.dumps(list(engines.test(cfg, log=logs.append))))
        ''')
        self.assertEqual(r, [True, "", ""])
        models = [c["args"][c["args"].index("--model") + 1] for c in self.e.calls()
                  if c["bin"] == "pi" and "--print" in c["args"] and "--model" in c["args"]]
        self.assertEqual(models[:1], ["bad-model"], "先按用户指定的模型试")
        self.assertEqual(len([c for c in self.e.calls() if c["bin"] == "pi" and "--print" in c["args"] and "--model" not in c["args"]]), 1,
                         "失败后不带 --model 再试一次")

    def test_pi_npm_install_flags(self):
        """装 Pi 用官方 npm 包，并且按官方建议不跑依赖的生命周期脚本。"""
        r = self.e.run(r'''
        import engines
        calls = []
        engines.nodejs.ensure = lambda say, confirm: "npm"
        engines._npm_install = lambda pkg, npm, engine=None: calls.append([pkg, engine, list(engines.NPM_FLAGS.get(engine, ()))] or True)
        engines.find = lambda e: "/fake/pi"
        got = engines.install("pi", say=lambda m: None, confirm=lambda q: True)
        print("@@" + json.dumps({"got": got, "calls": calls, "pkg": engines.NPM_PKG["pi"]}))
        ''')
        self.assertEqual(r["got"], "/fake/pi")
        self.assertEqual(r["pkg"], "@earendil-works/pi-coding-agent@latest")
        self.assertEqual(r["calls"], [["@earendil-works/pi-coding-agent@latest", "pi", ["--ignore-scripts"]]])

    def test_pi_classify(self):
        """整条判断流程：Pi 返回的 JSON 直接被 classify 用上。"""
        self.e.extra["FAKE_PI_ITEMS"] = json.dumps([{"id": "c001"}, {"id": "c002"}, {"id": "c003"}])
        r = self.e.run(textwrap.dedent(TestClassify.CAND) + textwrap.dedent(r'''
        import engines, shutil, json
        from common import load_config, save_config
        c = load_config(); c.update(aiEngine="pi", piPath=shutil.which("pi")); save_config(c)
        from classify import classify
        rv = classify(cand, log=lambda *a: None)
        print("@@" + json.dumps({"by": rv["judgedBy"], "tiers": {x["id"]: x["tier"] for x in rv["items"]},
                                 "engine": rv["engine"], "title": rv["items"][0]["title"]}))
        '''))
        self.assertEqual(r, {"by": "ai", "tiers": {"c001": "primary", "c002": "optional", "c003": "keep"},
                             "engine": "Pi", "title": "AI:c001"})


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


class TestScanDirs(Base):
    """#5：用户可配置的额外扫描目录（其他分区 / 项目文件夹）。"""

    def make_data(self):
        d = Path(self.e.tmp.name) / "data"
        (d / "proj").mkdir(parents=True)
        for i in range(5):
            (d / "proj" / f"s{i}.txt").write_bytes(b"x" * 1000)
        (d / "big.bin").write_bytes(b"x" * 8192)
        for sub in (".hid", "$RECYCLE.BIN", "node_modules"):
            (d / sub).mkdir()
            (d / sub / "inner.bin").write_bytes(b"x" * 8192)
        return d

    def test_config_list(self):
        d = self.make_data()
        self.e.extra["DATA"] = str(d)
        r = self.e.run(r"""
        import os, sys
        from pathlib import Path
        import dg
        from common import load_config
        out = {}
        def run(*a):
            try:
                dg.cmd_config(list(a)); return "ok"
            except SystemExit as e:
                return str(e)
        D = os.environ["DATA"]
        root = os.environ.get("SystemDrive", "C:") + "\\" if sys.platform == "win32" else "/"
        out["add"] = run("scanDirs", "add", D)
        out["dup"] = run("scanDirs", D)
        out["home"] = run("scanDirs", "add", str(Path.home()))
        out["root"] = run("scanDirs", "add", root)
        if sys.platform != "win32":       # Windows 上 "/" 是「当前所在盘」的根目录，不一定是系统盘
            out["slash"] = run("scanDirs", "add", "/")
        out["missing"] = run("scanDirs", "add", D + "/nope")
        out["after_add"] = load_config()["scanDirs"]
        out["protect"] = run("protect", "add", D + "/proj")
        out["protect_list"] = load_config()["protect"]
        out["remove"] = run("scanDirs", "remove", D)
        out["after_remove"] = load_config()["scanDirs"]
        run("scanDirs", "add", D); run("scanDirs", "clear")
        out["after_clear"] = load_config()["scanDirs"]
        out["threshold"] = run("thresholdGB", "20"); out["th"] = load_config()["thresholdGB"]
        out["real"] = str(Path(D).resolve())
        print("@@" + json.dumps(out))
        """)
        self.assertEqual((r["add"], r["dup"]), ("ok", "ok"))
        self.assertEqual(r["after_add"], [r["real"]], "添加时去重、存完整路径")
        self.assertIn("主目录", r["home"])
        self.assertIn("不能添加", r["root"])
        if not WIN:
            self.assertIn("不能添加", r["slash"])
        self.assertIn("不是一个存在的文件夹", r["missing"])
        self.assertEqual(r["protect_list"], [str(Path(r["real"]) / "proj")], "protect 也按列表追加，不再被写成字符串")
        self.assertEqual((r["after_remove"], r["after_clear"]), ([], []))
        self.assertEqual((r["threshold"], r["th"]), ("ok", 20), "普通配置项照旧")

    def test_scan_extra_dirs(self):
        d = self.make_data()
        self.e.extra["DATA"] = str(d)
        tmp = self.e.home / "AppData/Local/Temp"      # Windows：%TEMP% 会被整体列为缓存，测试数据不能放在真实的 %TEMP% 里
        tmp.mkdir(parents=True)
        self.e.extra.update(TEMP=str(tmp), TMP=str(tmp), LOCALAPPDATA=str(self.e.home / "AppData/Local"))
        r = self.e.run(r"""
        import os
        from pathlib import Path
        import scan as S
        from common import load_config, save_config
        c = load_config(); c["scanDirs"] = [os.environ["DATA"], str(Path.home()), "/", "C:\\"]; save_config(c)  # 后几个不合法，扫描时跳过
        orig = S.load_rules
        def rules():
            r = orig(); r["largeScan"] = dict(r["largeScan"], fileMinMB=0.004, dirMinMB=0.004); return r
        S.load_rules = rules
        out = S.scan(progress=lambda *a: None)
        base = str(Path(os.environ["DATA"]).resolve())
        rel = lambda p: os.path.relpath(os.path.realpath(p), base).replace(os.sep, "/")
        mine = [x for x in out["items"] if os.path.realpath(x["path"]).startswith(base)]
        print("@@" + json.dumps(sorted([rel(x["path"]), x["kind"], x["defaultTier"]] for x in mine)))
        """)
        self.assertIn(["big.bin", "large-file", "optional"], r)
        self.assertIn(["proj", "large-dir", "optional"], r)
        names = [x[0] for x in r]
        for bad in (".hid", ".hid/inner.bin", "$RECYCLE.BIN", "$RECYCLE.BIN/inner.bin", "node_modules/inner.bin"):
            self.assertNotIn(bad, names)
        self.assertTrue(all(x[2] == "optional" for x in r), "额外目录里找到的只能是「需要你决定」")

    def test_default_scan_unchanged_without_scan_dirs(self):
        """没配 scanDirs 时，常用目录里的隐藏 / $ 开头文件夹照旧会被统计（不改变原有行为）。"""
        dl = self.e.home / "Downloads" / ".bigcache"
        dl.mkdir(parents=True)
        for i in range(5):
            (dl / f"s{i}.bin").write_bytes(b"x" * 2000)
        r = self.e.run(r"""
        import scan as S
        orig = S.load_rules
        def rules():
            r = orig(); r["largeScan"] = dict(r["largeScan"], fileMinMB=1, dirMinMB=0.004); return r
        S.load_rules = rules
        out = S.scan(progress=lambda *a: None)
        print("@@" + json.dumps([x["name"] for x in out["items"] if x["kind"] == "large-dir"]))
        """)
        self.assertIn(".bigcache", r)

    @unittest.skipUnless(WIN and os.environ.get("CI"), "会注册真实的计划任务，只在 Windows CI 上跑")
    def test_win_monitor_runs_on_battery(self):
        """#8：后台任务在笔记本用电池时也要照常运行。"""
        r = self.e.run(r"""
        import re, subprocess, sys
        from pathlib import Path
        from plat import win
        label = "com.rabbittux.purrge.citest"
        ok = win.install_monitor(label, sys.executable, str(Path(sys.path[0]) / "dg.py"), 30, str(Path.home() / "m.log"), "")
        xml = subprocess.run(["schtasks", "/Query", "/TN", win._task_name(label), "/XML"], capture_output=True, text=True, errors="replace").stdout
        loaded = win.monitor_loaded(label)
        win.uninstall_monitor(label)
        get = lambda k: (re.search(f"<{k}>(\\w+)</{k}>", xml) or [None, "true"])[1]
        print("@@" + json.dumps({"ok": ok, "loaded": loaded, "dis": get("DisallowStartIfOnBatteries"), "stop": get("StopIfGoingOnBatteries"),
                                 "gone": not win.monitor_loaded(label)}))
        """)
        self.assertEqual(r, {"ok": True, "loaded": True, "dis": "false", "stop": "false", "gone": True})

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

    def test_ai_prompt_per_platform(self):
        """Windows 不能用写着 macOS 的提示词（issue #12）；两份规则除系统相关内容外要一致。"""
        mac = (ROOT / "runtime/rules/ai-rules.md").read_text(encoding="utf-8")
        win = (ROOT / "runtime/rules/ai-rules.win.md").read_text(encoding="utf-8")
        self.assertIn("macOS 磁盘清理顾问", mac)
        self.assertIn("Windows 磁盘清理顾问", win)
        self.assertNotIn("macOS", win)
        self.assertNotIn(".dmg", win)
        for key in ("## 三个档位", "## 硬规则", "## 每项输出", "## 输出格式", "items 必须覆盖候选清单里的每一个 id"):
            self.assertIn(key, win)
        src = (LIB / "classify.py").read_text(encoding="utf-8")
        self.assertIn('"ai-rules.win.md" if sys.platform == "win32"', src)


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

    def test_background_run_log_is_live(self):
        """#8：后台扫描的 run.log 要实时写入，扫描完、审查页还开着时就能看到进度。"""
        r = self.e.run(r'''
        import subprocess, time
        import dg
        from common import DG_HOME
        got = []
        class FakePopen:                      # 截下后台启动命令，由测试自己启动，测完直接结束，不留进程
            def __init__(self, cmd, **kw):
                got.append(cmd); kw["stdout"].close()
        DG_HOME.mkdir(parents=True, exist_ok=True)
        real = subprocess.Popen
        subprocess.Popen = FakePopen
        dg.cmd_run(["--background", "--no-open"])
        subprocess.Popen = real
        log = DG_HOME / "run.log"
        with open(log, "a") as f:
            p = real(got[0], stdout=f, stderr=subprocess.STDOUT)
        try:
            for _ in range(900):
                text = log.read_text(encoding="utf-8", errors="replace")
                if "审查页面" in text or p.poll() is not None:
                    break
                time.sleep(0.1)
        finally:
            p.kill(); p.wait()
        print("@@" + json.dumps({"alive_when_read": "审查页面" in text, "log": text}))
        ''')
        self.assertIn("扫描完成", r["log"])
        self.assertTrue(r["alive_when_read"], "审查页还开着时日志就应该已经写进文件")

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
