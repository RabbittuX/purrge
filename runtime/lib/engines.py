"""AI 引擎：Claude Code、Codex、WorkBuddy（CodeBuddy 命令行）、DeepSeek Harness（dsh）。负责找到命令行工具、安装最新版、检查/拉起登录、调用 AI。
Purrge 本身不依赖任何一家，引擎不可用时 classify.py 会退回规则判断。"""
import contextlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import nodejs

HOME = Path.home()
NAMES = {"claude": "Claude Code", "codex": "Codex", "workbuddy": "WorkBuddy", "deepseek": "DeepSeek Harness"}
BIN = {"claude": "claude", "codex": "codex", "workbuddy": "codebuddy", "deepseek": "dsh"}
NPM_PKG = {"workbuddy": "@tencent-ai/codebuddy-code@latest", "deepseek": "@deepseek-ai/dsh@latest"}
DSH_PATCH = Path(__file__).resolve().parent.parent / "rules" / "dsh-notools.yml"
DSH_TOOL_PLUGINS = ("tool-bash", "tool-pwsh", "tool-jobs", "tool-fs")
SECRETS = Path(os.environ.get("PURRGE_HOME", HOME / ".purrge")) / "secrets.json"   # 只存 DeepSeek API Key，权限 600
MODEL_ERRORS = ("not supported", "requires a newer version", "model_not_found", "does not exist", "invalid model")


@contextlib.contextmanager
def _tmpdir():
    """临时工作目录。AI 命令行（如 CodeBuddy）可能留下后台进程占着目录，Windows 上会删不掉：删不掉就留给系统清理，不能因此报错。"""
    d = tempfile.mkdtemp(prefix="purrge-")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _run(cmd, **kw):
    """后台调用：脱离终端运行，避免 CLI 向终端发查询码、抢用户正在输入的内容。"""
    kw.setdefault("start_new_session", True)
    if sys.platform == "win32":   # AI 命令行输出的是 UTF-8，Windows 默认按系统代码页解码会乱码
        kw.setdefault("encoding", "utf-8")
        kw.setdefault("errors", "replace")
    kw.setdefault("stdin", subprocess.DEVNULL) if "input" not in kw else None
    kw["env"] = nodejs.env(kw.get("env"))   # 用的是 Purrge 自带的 Node 时，npm 装的命令行要能找到它
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def _version(path):
    out = _run([path, "--version"], timeout=20).stdout
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _candidates(engine):
    found = shutil.which(BIN.get(engine, engine))
    paths = [found] if found else []
    if engine in NPM_PKG:    # npm 全局安装的命令行
        b = BIN[engine]
        exe = f"{b}.cmd" if sys.platform == "win32" else b
        paths += [HOME / ".local/bin" / b, "/opt/homebrew/bin/" + b, "/usr/local/bin/" + b, HOME / ".npm-global/bin" / b,
                  nodejs.bin_dir() / exe]
        if sys.platform == "win32":
            paths.append(Path(os.environ.get("APPDATA", HOME / "AppData/Roaming")) / "npm" / exe)
        npm = nodejs.npm()
        if npm:
            prefix = _run([npm, "prefix", "-g"], timeout=20).stdout.strip()
            if prefix:   # Windows 的 npm 全局命令直接放在 prefix 目录，Mac 在 prefix/bin
                paths.append(Path(prefix) / exe if sys.platform == "win32" else Path(prefix) / "bin" / b)
    elif sys.platform == "win32":    # Windows：官方安装器放在 ~/.local/bin，npm 全局命令在 %APPDATA%\\npm
        exe = BIN[engine]
        appdata = Path(os.environ.get("APPDATA", HOME / "AppData/Roaming"))
        paths += [HOME / ".local/bin" / f"{exe}.exe", appdata / "npm" / f"{exe}.cmd", nodejs.bin_dir() / f"{exe}.cmd"]
    elif engine == "claude":
        paths += [HOME / ".local/bin/claude", HOME / ".claude/local/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
    else:   # ChatGPT / Codex 桌面版自带的 codex 往往比命令行装的新
        paths += [HOME / ".local/bin/codex", "/opt/homebrew/bin/codex", "/usr/local/bin/codex",
                  "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
                  "/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex",
                  "/Applications/Codex.app/Contents/Resources/codex"]
    seen, out = set(), []
    for p in paths:
        p = str(p)
        if p not in seen and os.path.isfile(p) and (sys.platform == "win32" or os.access(p, os.X_OK)):
            seen.add(p)
            out.append(p)
    return out


def find(engine):
    """返回版本最新的那个可执行文件路径，没有就返回 None。"""
    paths = _candidates(engine)
    return max(paths, key=_version) if paths else None


def version_text(path):
    v = _version(path)
    return ".".join(map(str, v)) if v != (0, 0, 0) else "未知版本"


# ---------- 安装 ----------

def _npm_install(pkg, npm):
    subprocess.run([npm, "install", "-g", pkg], env=nodejs.env())


def install(engine, say=print, confirm=None):
    """安装最新版，成功返回路径。需要 npm 但电脑上没有 Node.js 时，先（征得同意后）自动安装 Node.js。"""
    if engine in NPM_PKG:
        npm = nodejs.ensure(say, confirm)
        if not npm:
            say(f"{NAMES[engine]} 需要 Node.js（自带 npm）：可以从 https://nodejs.org 手动安装，装好后重新运行安装命令")
            return None
        say(f"正在安装最新版 {NAMES[engine]} 命令行（npm）…")
        _npm_install(NPM_PKG[engine], npm)
        return find(engine)
    if engine == "claude":
        say("正在安装最新版 Claude Code（官方安装脚本）…")
        if sys.platform == "win32":
            p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://claude.ai/install.ps1 | iex"])
        else:
            p = subprocess.run("curl -fsSL https://claude.ai/install.sh | bash", shell=True)
        if p.returncode != 0 and nodejs.npm():
            say("官方脚本失败，改用 npm 安装…")
            _npm_install("@anthropic-ai/claude-code@latest", nodejs.npm())
        return find("claude")
    say("正在安装最新版 Codex…")
    if nodejs.npm():
        _npm_install("@openai/codex@latest", nodejs.npm())
    elif shutil.which("brew"):
        subprocess.run(["brew", "install", "codex"])
    elif sys.platform != "win32":
        _install_codex_release(say)
    else:
        npm = nodejs.ensure(say, confirm)
        if npm:
            _npm_install("@openai/codex@latest", npm)
        else:
            say("Codex 需要 Node.js（自带 npm）：可以从 https://nodejs.org 手动安装，装好后重新运行安装命令")
    return find("codex")


def upgrade(engine, path, say=print):
    """把已有的命令行工具升级到最新版。"""
    if engine in NPM_PKG:
        if nodejs.npm():
            _npm_install(NPM_PKG[engine], nodejs.npm())
        return find(engine)
    if engine == "claude":
        subprocess.run([path, "update"])
    elif "node_modules" in os.path.realpath(path) and nodejs.npm():
        _npm_install("@openai/codex@latest", nodejs.npm())
    elif os.path.realpath(path).startswith(("/opt/homebrew", "/usr/local/Cellar")) and shutil.which("brew"):
        subprocess.run(["brew", "upgrade", "codex"])
    else:
        _install_codex_release(say)
    return find(engine)


def _install_codex_release(say):
    """没有 npm / Homebrew 时，直接从 GitHub 官方发布页下载 codex 到 ~/.local/bin。"""
    arch = "aarch64" if platform.machine() == "arm64" else "x86_64"
    url = f"https://github.com/openai/codex/releases/latest/download/codex-{arch}-apple-darwin.tar.gz"
    dest = HOME / ".local/bin/codex"
    with _tmpdir() as tmp:
        tgz = Path(tmp) / "codex.tar.gz"
        urllib.request.urlretrieve(url, tgz)
        with tarfile.open(tgz) as t:
            t.extractall(tmp, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(tmp)
        binary = next(p for p in Path(tmp).rglob("codex*") if p.is_file() and p.suffix != ".gz")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, dest)
        os.chmod(dest, 0o755)
    say(f"已安装到 {dest}")


# ---------- 登录 ----------

def deepseek_key():
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    try:
        return json.loads(SECRETS.read_text()).get("DEEPSEEK_API_KEY", "")
    except (OSError, json.JSONDecodeError):
        return ""


def save_deepseek_key(key):
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    try:
        data = json.loads(SECRETS.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    data["DEEPSEEK_API_KEY"] = key.strip()
    SECRETS.write_text(json.dumps(data))
    try:
        os.chmod(SECRETS, 0o600)
    except OSError:
        pass


def logged_in(engine, path):
    if engine == "workbuddy":
        return None              # CodeBuddy 没有登录状态命令，交给连接测试判断
    if engine == "deepseek":
        return bool(deepseek_key())
    if engine == "claude":
        p = _run([path, "auth", "status", "--json"], timeout=30)
        try:
            return bool(json.loads(p.stdout).get("loggedIn"))
        except (json.JSONDecodeError, AttributeError):
            return None          # 老版本没有 auth 命令，留给后面的连接测试判断
    return _run([path, "login", "status"], timeout=30).returncode == 0


def login(engine, path):
    """在当前终端里拉起官方登录流程（会打开浏览器）。"""
    if engine == "workbuddy":   # CodeBuddy 只能在交互界面里用 /login 登录
        print("即将打开 CodeBuddy（WorkBuddy 同一账号、同一积分）：请输入 /login 完成登录，登录成功后输入 /exit 返回。", flush=True)
        return subprocess.run([path]).returncode == 0
    if engine == "deepseek":
        import getpass
        try:
            key = getpass.getpass("请输入 DeepSeek API Key（输入时不显示，只保存在本机 ~/.purrge/secrets.json）：")
        except (EOFError, OSError):
            return False
        if key.strip():
            save_deepseek_key(key)
        return bool(key.strip())
    cmd = [path, "auth", "login"] if engine == "claude" else [path, "login"]
    return subprocess.run(cmd).returncode == 0


# ---------- 调用 AI ----------

def codex_models():
    """账号可用的模型（Codex 本地缓存的列表，按推荐顺序）。"""
    try:
        data = json.loads((HOME / ".codex/models_cache.json").read_text(encoding="utf-8"))
        ms = [m for m in data.get("models", []) if m.get("visibility") == "list"]
        return [m["slug"] for m in sorted(ms, key=lambda m: m.get("priority", 99))]
    except (OSError, json.JSONDecodeError, KeyError):
        return []


class AIError(Exception):
    pass


_DSH_CHECKED = {}


def _dsh_tools_disabled(path):
    """确认补丁真的关掉了全部工具插件（dsh 是预览版，配置格式变了就拒绝调用）。"""
    if path not in _DSH_CHECKED:
        p = _run([path, "--profile", "headless", "--patch", str(DSH_PATCH), "--dump-config"], timeout=60)
        blocks = re.split(r"\n(?=- id: )", "\n" + p.stdout)
        state = {}
        for blk in blocks:
            m = re.match(r"- id: (\S+)", blk.strip())
            if m and m.group(1) in DSH_TOOL_PLUGINS:
                state[m.group(1)] = state.get(m.group(1), True) and bool(re.search(r"^\s+disabled: true\s*$", blk, re.M))
        _DSH_CHECKED[path] = p.returncode == 0 and set(state) == set(DSH_TOOL_PLUGINS) and all(state.values())
    return _DSH_CHECKED[path]


def _ask_once(engine, path, prompt, model, timeout):
    if engine == "workbuddy":
        # 用纯文本输出：json 模式会带上整段对话（含它自己很长的系统提示），超过约 54KB 时输出被截断
        cmd = [path, "-p", "--output-format", "text", "--tools", "", "--no-session-persistence"]
        if model:
            cmd += ["--model", model]
        with _tmpdir() as tmp:
            p = _run(cmd, input=prompt, timeout=timeout, cwd=tmp)
        out = p.stdout.strip()
        if p.returncode != 0 or not out or "Authentication required" in out:
            raise AIError((p.stderr or p.stdout)[-400:] or "CodeBuddy 没有返回内容")
        return out
    if engine == "deepseek":
        if not _dsh_tools_disabled(path):
            raise AIError("DeepSeek Harness 的工具插件没能全部关闭，为安全起见不调用（可能是 dsh 版本变化）")
        key = deepseek_key()
        if not key:
            raise AIError("缺少 DeepSeek API Key，请运行 purrge engine deepseek 重新设置")
        env = dict(os.environ, DEEPSEEK_API_KEY=key)
        with _tmpdir() as tmp:
            p = _run([path, "--profile", "headless", "--patch", str(DSH_PATCH), "-"], input=prompt, timeout=timeout, cwd=tmp, env=env)
        if p.returncode != 0 or not p.stdout.strip():
            raise AIError((p.stderr or p.stdout)[-400:] or "DeepSeek Harness 没有返回内容")
        return p.stdout
    if engine == "claude":
        cmd = [path, "-p", "--output-format", "json", "--max-turns", "1", "--tools", "", "--no-session-persistence"]
        if model:
            cmd += ["--model", model]
        p = _run(cmd, input=prompt, timeout=timeout)
        if p.returncode != 0 and not p.stdout.strip():
            raise AIError((p.stderr or p.stdout)[-400:])
        try:
            data = json.loads(p.stdout)
        except json.JSONDecodeError:
            return p.stdout
        # Claude Code 开了 verbose 时，json 模式输出整段消息数组，结果在最后一条 type=result 里
        if isinstance(data, list):
            data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), {})
        return data.get("result", "") if isinstance(data, dict) else ""
    # Codex：只读沙箱、不留会话，在空目录里运行，避免读到别的项目说明
    with _tmpdir() as tmp:
        out = Path(tmp) / "answer.txt"
        cmd = [path, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral", "--color", "never",
               "-o", str(out), "-"]
        if model:
            cmd[2:2] = ["-m", model]
        p = _run(cmd, input=prompt, timeout=timeout, cwd=tmp)
        text = out.read_text(encoding="utf-8") if out.exists() else ""
        if p.returncode != 0 or not text.strip():
            msg = re.findall(r'"message":"([^"]+)"', p.stderr) or [p.stderr[-400:]]
            raise AIError(msg[-1])
        return text


def ask(cfg, prompt, timeout=600, log=print):
    """按配置调用 AI，返回文本。Codex 模型不可用时自动换账号能用的模型，并记住它。"""
    engine = cfg.get("aiEngine")
    if engine not in NAMES:
        raise AIError("没有配置 AI 引擎")
    path = cfg.get(f"{engine}Path") or find(engine)
    if not path or not os.path.exists(path):
        raise AIError(f"找不到 {NAMES[engine]}")
    model = cfg.get(f"{engine}Model") or ""
    tried = [model]
    try:
        return _ask_once(engine, path, prompt, model, timeout), model
    except AIError as e:
        if engine != "codex" or not any(k in str(e).lower() for k in MODEL_ERRORS):
            raise
        last = e
    for m in codex_models():
        if m in tried:
            continue
        tried.append(m)
        log(f"模型 {tried[-2] or '默认'} 不可用，换 {m} 再试…")
        try:
            return _ask_once(engine, path, prompt, m, timeout), m
        except AIError as e:
            last = e
            if not any(k in str(e).lower() for k in MODEL_ERRORS):
                raise
    raise last


def test(cfg, log=print):
    """发一句很短的话，确认 AI 能正常回复。返回 (成功, 用上的模型, 错误信息)。"""
    try:
        text, model = ask(cfg, "只回复两个字母：OK。不要执行任何命令。", timeout=180, log=log)
        return bool(text.strip()), model, ""
    except AIError as e:
        return False, "", str(e)
