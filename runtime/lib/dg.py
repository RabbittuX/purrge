"""Purrge by RabbittuX：macOS / Windows 磁盘清理，AI（Claude Code、Codex、WorkBuddy 或 DeepSeek Harness）判断，你确认后才清理。

用法：purrge <命令>
  install                  安装：选择 AI、检查安装和登录、设阈值、开启后台监控
                           （可加 --engine claude|codex|workbuddy|deepseek --threshold 15 --yes）
  scan                     立即扫描，完成后自动打开审查页面
  status                   剩余空间、阈值、AI 和后台监控状态
  engine [名称]            查看或切换 AI：claude / codex / workbuddy / deepseek
  config [键 值]           查看或修改设置，如：config thresholdGB 20
  review                   重新打开最近一次的审查页面
  update                   更新到最新版（设置、扫描记录、AI 引擎都保留）
  uninstall                关闭后台监控（--purge 同时删除设置和扫描记录）
  version                  版本与官方来源
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plat  # noqa: E402
from common import (OFFICIAL, VERSION, APP_DIR, CONFIG, DG_HOME, disk_status, human, latest_run, load_config, new_run_dir,  # noqa: E402
                    save_config)

LABEL = "com.rabbittux.purrge"
PLIST = plat.monitor_file(LABEL)
INSTALLED_APP = DG_HOME / "app"
STATE = DG_HOME / "state.json"


def notify(title, text):
    plat.notify(title, text)


def migrate_from_disk_guard():
    """旧版叫 disk-guard：停掉旧的后台任务，并把设置和扫描记录搬到新目录（旧目录原样保留）。"""
    old_home, old_label = Path.home() / ".disk-guard", "com.diskguard.monitor"
    old_plist = Path.home() / "Library/LaunchAgents" / f"{old_label}.plist"
    if old_plist.exists():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{old_label}"], capture_output=True)
        old_plist.unlink()
    if (old_home / "config.json").exists() and not CONFIG.exists():
        DG_HOME.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_home / "config.json", CONFIG)
        if (old_home / "runs").is_dir() and not (DG_HOME / "runs").exists():
            shutil.copytree(old_home / "runs", DG_HOME / "runs")
        return str(old_home)
    return None


def cmd_setup(args):          # 兼容旧命令
    from installer import cmd_install
    cmd_install(args if "--engine" in args else args + ["--yes"])


def _monitor_path(cfg):
    """后台任务的 PATH：带上 AI 命令行和 node（npm 装的 codex 需要 node）所在目录。"""
    dirs = ["/usr/local/bin", "/opt/homebrew/bin", str(Path.home() / ".local/bin")]
    for key in ("claudePath", "codexPath"):
        if cfg.get(key):
            dirs.append(str(Path(cfg[key]).parent))
    if shutil.which("node"):
        dirs.append(str(Path(shutil.which("node")).parent))
    dirs += ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    return os.pathsep.join(dict.fromkeys(dirs))


def install_monitor(cfg):
    if os.environ.get("PURRGE_TEST_NO_MONITOR"):     # 测试专用：不碰真实的后台任务
        (DG_HOME / "monitor.test").write_text(json.dumps({"interval": cfg["intervalMinutes"]}))
        return
    plat.install_monitor(LABEL, plat.default_python(), INSTALLED_APP / "lib/dg.py", cfg["intervalMinutes"],
                         DG_HOME / "monitor.log", _monitor_path(cfg))


def has_full_disk_access():
    return plat.full_disk_access()


def _state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def ask_user(free):
    """弹出原生提醒窗（NSAlert，带图标和用量条）；失败时退回系统对话框。返回 scan / later。"""
    cfg = load_config()
    _, total = disk_status()
    th = f"{cfg['thresholdGB']:g} GB"
    return plat.show_alert(APP_DIR, human(free), human(total), th, 1 - free / total)


def cmd_popup(args):
    """预览弹窗（不需要空间真的不足）：先发一条通知，再弹提醒窗，不会触发扫描。
    --notify 只发通知；--snapshot 图片.png 只把提醒窗画成图片（Windows，CI 检查样式用）。"""
    free, total = disk_status()
    if "--snapshot" in args:
        out = args[args.index("--snapshot") + 1]
        th = f"{load_config()['thresholdGB']:g} GB"
        plat.show_alert(APP_DIR, human(free), human(total), th, 1 - free / total, snapshot=out)
        print(out)
        return
    how = plat.notify("Purrge", "收到！正在帮你翻找能清理的东西，翻完会把清单拿给你看～")
    print("通知：已发出" + (f"（{how}）" if how else ""))
    if "--notify" not in args:
        print("提醒窗：你选了「" + ("帮我看看" if ask_user(free) == "scan" else "等会儿再说") + "」（预览，不会开始扫描）")


def cmd_check(args):
    cfg = load_config()
    free, _ = disk_status()
    st = _state()
    low = free < cfg["thresholdGB"] * 1024 ** 3
    print(time.strftime("%F %T"), "free", human(free), "threshold", cfg["thresholdGB"], "GB", "low" if low else "ok")
    try:                                    # 顺带看一眼有没有新版本（每天最多联网一次，失败不影响检查）
        import update
        update.check_latest()
    except Exception:
        pass
    if not low and "--force" not in args:
        return
    if time.time() - st.get("lastPrompt", 0) < cfg["cooldownHours"] * 3600 and "--force" not in args:
        return
    st["lastPrompt"] = time.time()
    STATE.write_text(json.dumps(st))
    choice = ask_user(free)
    if choice == "scan":
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run"], start_new_session=True,
                         stdout=open(DG_HOME / "run.log", "a"), stderr=subprocess.STDOUT)


def cmd_run(args):
    if "--background" in args:   # 立即返回，扫描完成后自动打开审查页面
        rest = [a for a in args if a != "--background"]
        log = open(DG_HOME / "run.log", "a")
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run", *rest], start_new_session=True,
                         stdout=log, stderr=subprocess.STDOUT)
        print("已开始扫描（约 1～2 分钟：扫描 10 秒 + AI 判断），完成后会自动在浏览器打开审查页面。"
              f"进度日志：{DG_HOME / 'run.log'}")
        return
    from classify import classify
    from scan import scan
    from server import serve
    run_dir = new_run_dir()
    notify("Purrge", "收到！正在帮你翻找能清理的东西，翻完会把清单拿给你看～")
    t0 = time.time()
    cand = scan()
    (run_dir / "candidates.json").write_text(json.dumps(cand, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"扫描完成：{len(cand['items'])} 项，用时 {time.time() - t0:.0f}s")
    review = classify(cand)
    (run_dir / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"判断完成（{review.get('engine') or '规则'}），打开审查页面…")
    serve(run_dir, open_browser="--no-open" not in args)


def cmd_review(args):
    from server import serve
    run = latest_run()
    if not run or not (run / "review.json").exists():
        print("还没有扫描记录，请先运行 run")
        return
    serve(run, open_browser="--no-open" not in args)


def cmd_config(args):
    cfg = load_config()
    if len(args) >= 2:
        key, val = args[0], args[1]
        if key in ("threshold", "阈值"):
            key = "thresholdGB"
        old = cfg.get(key)
        cfg[key] = type(old)(val) if isinstance(old, (int, float)) and not isinstance(old, bool) else val
        if isinstance(old, (int, float)):
            cfg[key] = float(val) if "." in str(val) else int(val)
        save_config(cfg)
        if key == "intervalMinutes" and PLIST.exists():
            install_monitor(cfg)
    print(json.dumps(cfg, ensure_ascii=False, indent=1))


def cmd_scan(args):
    cmd_run(["--background", *args])


def cmd_status(args):
    import engines
    cfg = load_config()
    free, total = disk_status()
    loaded = plat.monitor_loaded(LABEL)
    run = latest_run()
    print(json.dumps({"free": human(free), "total": human(total), "thresholdGB": cfg["thresholdGB"],
                      "belowThreshold": free < cfg["thresholdGB"] * 1024 ** 3, "monitor": "运行中" if loaded else "未安装",
                      "intervalMinutes": cfg["intervalMinutes"], "lastRun": run.name if run else None,
                      "ai": engines.NAMES.get(cfg.get("aiEngine"), "未设置（规则判断）"),
                      **({"update": f"有新版本 {_upd}，运行 purrge update 更新"} if (_upd := _update_available()) else {})},
                     ensure_ascii=False, indent=1))


def _update_available():
    try:
        import update
        return update.available()
    except Exception:
        return None


def cmd_update(args):
    import update
    sys.exit(update.cmd_update(args))


def cmd_post_update(args):
    """更新后由新程序自己执行：重新注册后台任务、更新 AI 说明文件、自检。失败返回非 0，外层会换回旧版本。"""
    from installer import install_skill
    cfg = load_config()
    install_monitor(cfg)
    if cfg.get("aiEngine"):
        install_skill(cfg["aiEngine"])
    free, total = disk_status()
    assert total > 0 and 0 <= free <= total, "磁盘信息读取失败"
    assert (INSTALLED_APP / "web/review.html").is_file() and (INSTALLED_APP / "rules").is_dir(), "程序文件不完整"
    if not os.environ.get("PURRGE_TEST_NO_MONITOR"):
        assert plat.monitor_loaded(LABEL), "后台任务没有注册成功"
    print(f"自检通过：Purrge {VERSION}")


def _delete_after_exit(path, delay=2.0):
    """删除当前正在运行的 purrge.cmd：等这条命令退出后，由后台进程删掉。
    不用 cmd + ping 当计时器：ICMP 被安全软件拦截或网络栈异常时，ping 会多花好几秒
    （实测 ping -n 3 127.0.0.1 需要 9 秒），删除时机不可控。"""
    code = ("import os, sys, time\n"
            "time.sleep(float(sys.argv[1]))\n"
            "for _ in range(10):\n"
            "    try:\n"
            "        os.remove(sys.argv[2])\n"
            "        break\n"
            "    except FileNotFoundError:\n"
            "        break\n"
            "    except OSError:\n"          # 父进程还没放开文件，稍后重试
            "        time.sleep(0.5)\n")
    subprocess.Popen([sys.executable, "-c", code, str(delay), str(path)],
                     creationflags=0x00000008 | 0x08000000,   # DETACHED_PROCESS | CREATE_NO_WINDOW
                     close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_uninstall(args):
    if os.environ.get("PURRGE_TEST_NO_MONITOR"):     # 测试专用：不碰真实的后台任务
        (DG_HOME / "monitor.test").unlink(missing_ok=True)
    else:
        plat.uninstall_monitor(LABEL)
    from installer import CLI_LINK, SKILL_DIRS, WIN_CLI
    if CLI_LINK.is_symlink():
        CLI_LINK.unlink()
    if sys.platform == "win32" and WIN_CLI.exists():
        # Windows 的 purrge 命令是 WindowsApps 里的 purrge.cmd，而且此刻正在运行：直接删掉，cmd 会报 "The batch file cannot be found."
        # 所以交给一个后台小任务，等这次命令结束后再删
        _delete_after_exit(WIN_CLI)
    for d in SKILL_DIRS.values():
        shutil.rmtree(d, ignore_errors=True)
    if "--purge" in args:
        shutil.rmtree(DG_HOME, ignore_errors=True)
    print("已关闭后台监控，移除了 purrge 命令和 AI 里的说明文件" +
          ("，并删除了设置和扫描记录" if "--purge" in args else "（设置和扫描记录保留在 ~/.purrge，加 --purge 可一起删除）"))


def main():
    if sys.platform == "win32":   # Windows 控制台输出被程序（如 AI 代装）捕获时默认不是 UTF-8，中文会报错
        for s in (sys.stdout, sys.stderr):
            if s is not None and hasattr(s, "reconfigure"):
                s.reconfigure(encoding="utf-8", errors="replace")
    if sys.stdout is None:   # Windows 后台用 pythonw 运行时没有控制台：输出写进日志
        DG_HOME.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(DG_HOME / "monitor.log", "a", encoding="utf-8")
    from installer import cmd_engine, cmd_install
    cmds = {"install": cmd_install, "setup": cmd_setup, "scan": cmd_scan, "run": cmd_run, "check": cmd_check,
            "review": cmd_review, "config": cmd_config, "status": cmd_status, "engine": cmd_engine,
            "uninstall": cmd_uninstall, "update": cmd_update, "_post_update": cmd_post_update, "popup": cmd_popup}
    if len(sys.argv) > 1 and sys.argv[1] in ("version", "--version", "-v"):
        print(f"Purrge {VERSION} by RabbittuX（官方来源：{OFFICIAL}）")
        return
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(f"Purrge {VERSION} by RabbittuX（官方来源：{OFFICIAL}）")
        print(__doc__)
        return
    DG_HOME.mkdir(parents=True, exist_ok=True)
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
