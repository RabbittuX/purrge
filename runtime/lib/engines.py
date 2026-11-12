"""AI 引擎：Claude Code、Codex、WorkBuddy（CodeBuddy 命令行）、DeepSeek Harness（dsh）、Pi（pi）。负责找到命令行工具、安装最新版、检查/拉起登录、调用 AI。
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
NAMES = {"claude": "Claude Code", "codex": "Codex", "workbuddy": "WorkBuddy", "deepseek": "DeepSeek Harness",
         "pi": "Pi"}
BIN = {"claude": "claude", "codex": "codex", "workbuddy": "codebuddy", "deepseek": "dsh", "pi": "pi"}
NPM_PKG = {"workbuddy": "@tencent-ai/codebuddy-code@latest", "deepseek": "@deepseek-ai/dsh@latest",
           "pi": "@earendil-works/pi-coding-agent@latest"}
NPM_FLAGS = {"pi": ("--ignore-scripts",)}     # Pi 官方推荐：安装时不跑依赖的生命周期脚本
DSH_PATCH = Path(__file__).resolve().parent.parent / "rules" / "dsh-notools.yml"
DSH_TOOL_PLUGINS = ("tool-bash", "tool-pwsh", "tool-jobs", "tool-fs")
SECRETS = Path(os.environ.get("PURRGE_HOME", HOME / ".purrge")) / "secrets.json"   # 只存 DeepSeek API Key，权限 600
MODEL_ERRORS = ("not supported", "requires a newer version", "model_not_found", "does not exist", "invalid model")
# Pi 指定了模型却用不了（名字写错、同一模型有多个来源分不清）时，自动退回默认模型再试一次
PI_MODEL_ERRORS = ("not found", "ambiguous", "no api key found")


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


def _desktop_paths(engine, local):
    """桌面版应用自带、但不会加进 PATH 的命令行（Codex / Claude 桌面版都是这种）。"""
    patterns = {
        "codex": ["OpenAI/Codex/bin/*/codex.exe",
                  "Programs/codex/codex.exe",
                  "Programs/Codex/codex.exe"],
        "claude": ["Claude-3p/claude-code/*/*/claude.exe",
                   "Claude-3p/claude-code-vm/*/claude.exe"],
    }.get(engine, [])
    found = []
    for pat in patterns:
        found += sorted(str(p) for p in local.glob(pat) if p.is_file())
    return found


def _managed_paths(engine):
    """不走 npm、由官方安装程序自己管理的命令行位置。"""
    if engine == "pi":   # pi.dev 的安装脚本把命令放在 ~/.pi/agent/bin（Windows 上是 pi.cmd，也在 PATH 里）
        return [HOME / ".pi/agent/bin" / ("pi.cmd" if sys.platform == "win32" else "pi")]
    return []


def _candidates(engine):
    found = shutil.which(BIN.get(engine, engine))
    paths = [found] if found else []
    paths += _managed_paths(engine)
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
        local = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData/Local"))
        paths += [HOME / ".local/bin" / f"{exe}.exe", appdata / "npm" / f"{exe}.cmd", nodejs.bin_dir() / f"{exe}.cmd"]
        paths += _desktop_paths(engine, local)
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

def _npm_install(pkg, npm, engine=None):
    subprocess.run([npm, "install", "-g", *NPM_FLAGS.get(engine, ()), pkg], env=nodejs.env())


def install(engine, say=print, confirm=None):
    """安装最新版，成功返回路径。需要 npm 但电脑上没有 Node.js 时，先（征得同意后）自动安装 Node.js。"""
    if engine in NPM_PKG:
        npm = nodejs.ensure(say, confirm)
        if not npm:
            say(f"{NAMES[engine]} 需要 Node.js（自带 npm）：可以从 https://nodejs.org 手动安装，装好后重新运行安装命令")
            return None
        say(f"正在安装最新版 {NAMES[engine]} 命令行（npm）…")
        _npm_install(NPM_PKG[engine], npm, engine)
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
    if engine == "pi":   # 官方安装程序装的那份用 pi update 自己升级；失败再退回 npm
        if _run([path, "update"], timeout=600).returncode == 0:
            return find(engine)
        if nodejs.npm():
            _npm_install(NPM_PKG["pi"], nodejs.npm(), "pi")
        return find(engine)
    if engine in NPM_PKG:
        if nodejs.npm():
            _npm_install(NPM_PKG[engine], nodejs.npm(), engine)
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
    if engine == "pi":
        # Pi 的登录状态跟「用哪个来源的哪个模型」绑在一起（pi auth check 必须指定 provider 或 model），
        # 而且还可以只靠环境变量里的 Key 工作：这里不猜，交给连接测试判断
        return None
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
    if engine == "pi":          # Pi 也只有在交互界面里用 /login 登录（选模型来源、授权或填 API Key）
        print("即将打开 Pi：请输入 /login 完成登录（选择模型来源并授权），登录成功后输入 /exit 返回。", flush=True)
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


# Pi：关掉全部可以动文件 / 执行命令的工具，只让它读清单、写判断。
# --exclude-tools "*" 是最后一道过滤（扩展塞进来的工具也会被关掉），--no-mcp 顺带断开 MCP 服务器；
# 扩展、项目配置和信任文件一律不加载（--no-extensions / --no-approve / --no-context-files），
# 每次都在空目录里跑、不留会话。
PI_TOOLS = ("--no-tools", "--exclude-tools", "*", "--no-mcp", "--no-extensions", "--no-skills",
            "--no-prompt-templates", "--no-context-files", "--no-approve")
PI_REQUIRED_FLAGS = ("--no-tools", "--exclude-tools", "--no-mcp", "--no-extensions", "--no-session", "--mode")
_PI_CHECKED = {}


def _pi_tools_disabled(path):
    """确认这个 pi 认得关工具的开关（Pi 迭代很快，参数一改就拒绝调用，不能让它带着工具去判断）。"""
    if path not in _PI_CHECKED:
        p = _run([path, "--no-extensions", "--offline", "--help"], timeout=60)   # 不加载扩展：快，而且核心参数都还在
        if p.returncode != 0:
            p = _run([path, "--help"], timeout=120)
        help_text = p.stdout + p.stderr
        _PI_CHECKED[path] = p.returncode == 0 and all(f in help_text for f in PI_REQUIRED_FLAGS)
    return _PI_CHECKED[path]


def _pi_reply(stdout):
    """从 Pi 的 JSONL 事件流里取最后一条助手回复，同时确认这次调用手上确实一个工具都没有。"""
    text, declared = "", None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind, msg = ev.get("type"), ev.get("message") or {}
        if kind in ("tool_execution_start", "tool_call"):
            raise AIError("Pi 的工具没能全部关闭，为安全起见不调用")
        if kind == "message_update":
            inner = ev.get("assistantMessageEvent") or {}
            if inner.get("type") == "error":
                raise AIError(str(inner.get("error") or inner.get("reason") or "Pi 返回了错误")[:400])
        elif kind == "message_end" and msg.get("role") == "system":
            declared = ((msg.get("sections") or {}).get("tools") or "")     # 交给模型看的工具清单
        elif kind == "message_end" and msg.get("role") == "assistant":
            if msg.get("stopReason") == "error":
                raise AIError(str(msg.get("error") or "Pi 返回了错误")[:400])
            parts = [c.get("text", "") for c in (msg.get("content") or []) if isinstance(c, dict) and c.get("type") == "text"]
            if "".join(parts).strip():     # 只认最后一条有内容的助手消息
                text = "".join(parts)
    if declared is not None and "(none)" not in declared:
        # 事件流里自报的工具清单：没有 "(none)" 就说明它拿到了工具，哪怕输出看着正常也不能用
        raise AIError("Pi 带着工具启动了，为安全起见不采用这次结果")
    return text


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
    if engine == "pi":
        if not _pi_tools_disabled(path):
            raise AIError("Pi 的工具没能全部关闭，为安全起见不调用（可能是 pi 版本变化）")
        cmd = [path, "--print", "--mode", "json", "--no-session", *PI_TOOLS]
        if model:
            cmd += ["--model", model]
        with _tmpdir() as tmp:      # 空目录：读不到别的项目的说明文件
            p = _run(cmd, input=prompt, timeout=timeout, cwd=tmp)
        text = _pi_reply(p.stdout)
        if p.returncode != 0 or not text.strip():
            raise AIError((p.stderr or p.stdout)[-400:] or "Pi 没有返回内容")
        return text
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
        if isinstance(data, dict) and data.get("is_error"):
            # 没登录 / 鉴权失败时 claude 也输出一条 result（is_error=true，result 是报错文字，退出码 1），
            # 不能把这句话当成 AI 的回答（#8）
            raise AIError(str(data.get("result") or "Claude Code 返回了错误")[:400])
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
        if engine == "pi" and model and any(k in str(e).lower() for k in PI_MODEL_ERRORS):
            log(f"模型 {model} 不可用，改用 Pi 当前的默认模型再试…")
            return _ask_once(engine, path, prompt, "", timeout), ""
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


_REFUSE = re.compile(r"not logged in|please run /login|unauthorized|invalid api key|authentication[ _]?error"
                     r"|no api key found", re.I)


def test(cfg, log=print):
    """发一句很短的话，确认 AI 能正常回复。返回 (成功, 用上的模型, 错误信息)。"""
    try:
        text, model = ask(cfg, "只回复两个字母：OK。不要执行任何命令。", timeout=180, log=log)
    except AIError as e:
        return False, "", str(e)
    text = (text or "").strip()
    if not text:
        return False, model, "AI 没有返回任何内容"
    if _REFUSE.search(text):
        # 未登录 / 鉴权失败时，命令行会把这句话当正常输出打印出来（退出码仍是 1），
        # 只看「有没有文字」会把这种情况误判成连接正常。
        return False, model, text.splitlines()[0][:200]
    return True, model, ""
