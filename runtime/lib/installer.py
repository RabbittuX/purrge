"""交互式安装：选 AI 引擎（Claude Code / Codex / WorkBuddy / DeepSeek / Pi）→ 缺 Node.js 时自动安装 → 检查安装 → 检查登录 → 测试连接 → 设阈值 → 注册后台监控。
用 /dev/tty 读输入，所以 `curl ... | bash` 方式运行也能正常提问。"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import engines
WIN = sys.platform == "win32"
from common import APP_DIR, CONFIG, DG_HOME, OFFICIAL, VERSION, disk_status, human, load_config, save_config

INSTALLED_APP = DG_HOME / "app"
CLI_LINK = Path.home() / ".local/bin/purrge"
WIN_CLI = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Microsoft/WindowsApps/purrge.cmd"
SKILL_DIRS = {"claude": Path.home() / ".claude/skills/purrge", "codex": Path.home() / ".codex/skills/purrge",
              "workbuddy": Path.home() / ".codebuddy/skills/purrge",
              "pi": Path.home() / ".pi/agent/skills/purrge"}   # Pi 的用户级技能目录是 ~/.pi/agent/skills
ENGINE_ORDER = ("claude", "codex", "workbuddy", "deepseek", "pi")   # 安装时的选项顺序；1、2 与旧版一致，新引擎排在后面

B, D, G, Y, R, X = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"


def say(msg=""):
    print(msg, flush=True)


def ok(msg):
    say(f"  {G}✓{X} {msg}")


def warn(msg):
    say(f"  {Y}!{X} {msg}")


def fail(msg):
    say(f"  {R}✗{X} {msg}")
    sys.exit(1)


def ask(prompt, default=""):
    """从终端读一行；没有终端（比如被别的程序调用）时返回 None。"""
    if WIN:
        try:
            ans = input(prompt) if sys.stdin and sys.stdin.isatty() else None
        except (EOFError, OSError):
            return None
        return None if ans is None else (ans.strip() or default)
    try:
        with open("/dev/tty") as tin, open("/dev/tty", "w") as tout:
            tout.write(prompt)
            tout.flush()
            ans = tin.readline()
    except OSError:
        return None
    ans = ans.strip()
    return ans if ans else default


def confirm_yes(question):
    """问一句 [Y/n]，直接回车算同意；没有终端（AI 代为安装）时视为同意，安装本来就是用户要求的。"""
    ans = ask(f"    {question}", "y")
    return ans is None or ans.strip().lower() in ("y", "yes", "是", "好")


def _flag(args, name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def has_tty():
    if WIN:
        return bool(sys.stdin and sys.stdin.isatty())
    try:
        open("/dev/tty").close()
        return True
    except OSError:
        return False


def caller_engine():
    """被 Claude Code / Codex / Pi 代为运行时，它们会在环境变量里留下标记。"""
    if os.environ.get("CLAUDECODE"):
        return "claude"
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID"):
        return "codex"
    if os.environ.get("PI_CODING_AGENT") or os.environ.get("PI_SESSION_ID"):
        return "pi"
    return None


def choose_engine(args):
    eng = _flag(args, "--engine")
    if eng in engines.NAMES:
        return eng
    if not has_tty():                    # 没有终端可以提问：由 AI 代装，或被脚本调用
        eng = caller_engine()
        if eng:
            ok(f"检测到由 {engines.NAMES[eng]} 代为安装，就用 {engines.NAMES[eng]} 来做判断")
            return eng
        for e in ENGINE_ORDER:
            p = engines.find(e)
            if p and engines.logged_in(e, p):
                ok(f"自动选择已登录的 {engines.NAMES[e]}")
                return e
        fail("没有可交互的终端，也没找到正在使用的 AI 命令行。请加参数：--engine claude / codex / workbuddy / deepseek / pi")
    say(f"\n{B}Purrge 用哪个 AI 来判断哪些东西能清理？{X}")
    for i, e in enumerate(ENGINE_ORDER, 1):
        p = engines.find(e)
        state = f"{G}已安装 {engines.version_text(p)}{X}" if p else f"{D}未安装，会自动安装最新版{X}"
        say(f"  {i}) {engines.NAMES[e]:<17} {state}")
    ans = (ask(f"请输入 1～{len(ENGINE_ORDER)} [1]：", "1") or "1").strip().lower()
    if ans in ENGINE_ORDER:
        return ans
    return ENGINE_ORDER[int(ans) - 1] if ans.isdigit() and 1 <= int(ans) <= len(ENGINE_ORDER) else "claude"


def ensure_engine(engine):
    """确保引擎已安装、已登录，返回可执行文件路径。"""
    name = engines.NAMES[engine]
    path = engines.find(engine)
    if path:
        ok(f"已安装 {name} {engines.version_text(path)}（{path}）")
    else:
        warn(f"没有检测到 {name}，开始安装最新版…")
        path = engines.install(engine, say=lambda m: say(f"    {m}"), confirm=confirm_yes)
        if not path:
            fail(f"{name} 安装失败。请按官网说明手动安装后，重新运行安装命令。")
        ok(f"{name} 安装完成 {engines.version_text(path)}")
    state = engines.logged_in(engine, path)
    if state is False:
        warn(f"{name} 还没有登录，正在打开登录页面，请在浏览器里完成登录…")
        engines.login(engine, path)
        if engines.logged_in(engine, path) is False:
            fail(f"{name} 仍未登录。登录后重新运行安装命令即可。")
        ok(f"{name} 登录成功")
    elif state:
        ok(f"{name} 已登录")
    return path


def connect(cfg, engine, path):
    """测一次 AI 连接；版本太旧会自动升级，没登录会拉起登录。返回是否可用。"""
    name = engines.NAMES[engine]
    say(f"  … 正在测试 {name} 能否正常回复（约 10～30 秒）")
    good, model, err = engines.test(cfg, log=lambda m: say(f"    {m}"))
    low = err.lower()
    if not good and "newer version" in low:
        warn(f"{name} 版本太旧，正在升级到最新版…")
        cfg[f"{engine}Path"] = engines.upgrade(engine, path, say=lambda m: say(f"    {m}")) or path
        good, model, err = engines.test(cfg, log=lambda m: say(f"    {m}"))
        low = err.lower()
    if not good and engine == "workbuddy" and not has_tty():   # CodeBuddy 只能在交互界面登录，没有终端时拉起会卡住
        warn("WorkBuddy 还没登录：请在终端运行 codebuddy，输入 /login 登录后，再运行 purrge engine workbuddy")
    elif not good and engine == "pi" and not has_tty():        # Pi 的登录同样只能在交互界面里做
        warn("Pi 还没登录：请在终端运行 pi，输入 /login 选择模型来源并授权，然后运行 purrge engine pi")
    elif not good and any(k in low for k in ("login", "log in", "auth", "401", "unauthorized", "api key")):
        warn(f"{name} 需要重新登录，正在打开登录页面…")
        engines.login(engine, cfg[f"{engine}Path"])
        good, model, err = engines.test(cfg, log=lambda m: say(f"    {m}"))
    if good:
        cfg[f"{engine}Model"] = model
        ok(f"{name} 连接正常" + (f"，使用模型 {model}" if model else ""))
    else:
        warn(f"{name} 暂时没法回复：{err[:160]}")
        warn("先改用规则判断，功能照常可用；问题解决后运行 `purrge engine " + engine + "` 重新连接")
    return good


def copy_runtime():
    if APP_DIR.resolve() != INSTALLED_APP.resolve():
        if INSTALLED_APP.exists():
            shutil.rmtree(INSTALLED_APP)
        shutil.copytree(APP_DIR, INSTALLED_APP, ignore=shutil.ignore_patterns("__pycache__"))
    os.chmod(INSTALLED_APP / "bin/purrge", 0o755)


def _link_cli_win():
    """Windows：在 WindowsApps（默认就在 PATH 里）放一个 purrge.cmd。"""
    target = WIN_CLI
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'@"{sys.executable}" "{INSTALLED_APP / "lib/dg.py"}" %*\r\n', encoding="utf-8")
    return str(target.parent).lower() in os.environ.get("PATH", "").lower()


def link_cli():
    """装一个 purrge 命令；已经通过 Homebrew 等方式装过的，就不再重复放一个。"""
    if WIN:
        return _link_cli_win()
    for d in os.environ.get("PATH", "").split(":"):
        other = Path(d) / "purrge"
        if other != CLI_LINK and other.exists() and os.access(other, os.X_OK):
            if CLI_LINK.is_symlink():
                CLI_LINK.unlink()
            return True
    CLI_LINK.parent.mkdir(parents=True, exist_ok=True)
    if CLI_LINK.is_symlink() or CLI_LINK.exists():
        CLI_LINK.unlink()
    CLI_LINK.symlink_to(INSTALLED_APP / "bin/purrge")
    on_path = str(CLI_LINK.parent) in os.environ.get("PATH", "").split(":")
    return on_path


def install_skill(engine):
    """让 Claude Code / Codex 能听懂"帮我清理磁盘"：放一个说明文件，只调用 purrge 命令，不直接删文件。"""
    src = INSTALLED_APP / "integrations/SKILL.md"
    if engine not in SKILL_DIRS or not src.exists() or not SKILL_DIRS[engine].parent.parent.exists():
        return False
    SKILL_DIRS[engine].mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, SKILL_DIRS[engine] / "SKILL.md")
    return True


def apply_engine(cfg, engine):
    path = ensure_engine(engine)
    cfg["aiEngine"], cfg[f"{engine}Path"] = engine, path
    connect(cfg, engine, path)
    return cfg


def cmd_install(args):
    from dg import has_full_disk_access, install_monitor, migrate_from_disk_guard
    if sys.platform not in ("darwin", "win32"):
        fail("Purrge 目前只支持 macOS 和 Windows")
    say(f"\n{B}🐾 Purrge {VERSION} by RabbittuX{X}  {D}官方来源：{OFFICIAL}{X}")
    say(f"{D}基于 AI 的 {'Windows' if WIN else 'macOS'} 磁盘空间管理工具：低空间预警、智能识别可清理项、经用户审批后执行清理{X}")
    migrate_from_disk_guard()
    cfg = load_config()
    engine = choose_engine(args)

    # 先把要问的都问完，再调用 AI 命令行（它们运行时会占用终端，提前敲的字会丢）
    say(f"\n{B}1/3 提醒阈值{X}")
    th = _flag(args, "--threshold")
    if th is None:
        free, total = disk_status()
        cur = f"{cfg['thresholdGB']:g}"
        th = ask(f"  当前剩余 {human(free)} / 共 {human(total)}。剩余空间低于多少 GB 时提醒你？[{cur}]：", cur) or cur
    try:
        cfg["thresholdGB"] = float(th) if "." in str(th) else int(th)
    except ValueError:
        warn(f"「{th}」不是数字，沿用 {cfg['thresholdGB']} GB")
    ok(f"剩余低于 {cfg['thresholdGB']:g} GB 时提醒")

    say(f"\n{B}2/3 准备 {engines.NAMES[engine]}{X}")
    copy_runtime()
    apply_engine(cfg, engine)

    say(f"\n{B}3/3 开启后台监控{X}")
    save_config(cfg)
    install_monitor(cfg)
    ok(f"每 {cfg['intervalMinutes']} 分钟检查一次（只看剩余空间，不调用 AI）")
    on_path = link_cli()
    hint = "重新打开一个 PowerShell 窗口后可用" if WIN else f"~/.local/bin 不在 PATH 里，可用完整路径 {CLI_LINK}"
    ok("命令行工具：purrge" + ("" if on_path else f"  {D}（{hint}）{X}"))
    if install_skill(engine):
        ok(f"已教会 {engines.NAMES[engine]}：直接说「帮我清理磁盘」也能用")
    if has_full_disk_access() is False:
        say(f"  {D}可选：在「系统设置 → 隐私与安全性 → 完全磁盘访问权限」里给终端打开权限，能扫到更多系统缓存{X}")

    say(f"\n{G}{B}安装完成！{X}常用命令：")
    say("  purrge scan        立即扫描，完成后自动打开审查页")
    say("  purrge status      查看剩余空间和监控状态")
    say("  purrge engine      查看或切换 AI（claude / codex / workbuddy / deepseek / pi）")
    say("  purrge uninstall   关闭后台监控")
    if "--yes" not in args and (ask("\n现在就扫描一次吗？[y/N]：", "n") or "n").lower() in ("y", "yes", "是"):
        from dg import cmd_run
        cmd_run(["--background"])


def cmd_engine(args):
    from dg import install_monitor
    cfg = load_config()
    if not args:
        e = cfg.get("aiEngine")
        say(f"当前 AI：{engines.NAMES.get(e, '未设置（只用规则判断）')}"
            + (f"，模型 {cfg.get(e + 'Model') or '默认'}，路径 {cfg.get(e + 'Path')}" if e in engines.NAMES else ""))
        say("切换：purrge engine claude | codex | workbuddy | deepseek | pi")
        return
    engine = args[0].lower()
    if engine not in engines.NAMES:
        fail("只支持 claude、codex、workbuddy、deepseek、pi")
    apply_engine(cfg, engine)
    save_config(cfg)
    install_monitor(cfg)
    install_skill(engine)
    ok(f"已切换到 {engines.NAMES[engine]}")
