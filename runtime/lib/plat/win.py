"""Windows 实现：与 plat/mac.py 接口一致。只用 Python 标准库 + 系统自带的 PowerShell / schtasks / tasklist / explorer。"""
import csv
import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

NAME = "Windows"
FILE_MANAGER = "资源管理器"
_NO_WINDOW = 0x08000000   # CREATE_NO_WINDOW：后台调用不闪黑框


def _run(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("creationflags", _NO_WINDOW)
    try:
        return subprocess.run(cmd, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def _ps(script, timeout=60):
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=timeout)


def _q(s):
    return "'" + str(s).replace("'", "''") + "'"


def data_volume():
    return os.environ.get("SystemDrive", "C:") + "\\"


def disk_status():
    u = shutil.disk_usage(data_volume())
    return u.free, u.total


def _walk_size(path, deadline):
    total, limited = 0, False
    stack = [str(path)]
    while stack:
        if time.time() > deadline:
            return total, True
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        limited = True
        except OSError:
            limited = True
    return total, limited


def du_bytes(path, timeout=600):
    p = Path(path)
    if p.is_file():
        return p.stat().st_size, False
    return _walk_size(p, time.time() + timeout)


def dir_sizes(root, depth, timeout=900):
    """root 下深度 ≤ depth 的各个目录占用 [(字节, 路径)]，与 du -d 的输出口径一致（含 root 本身）。"""
    root = Path(root)
    sizes = {}
    deadline = time.time() + timeout
    for cur, dirs, files in os.walk(root, onerror=lambda e: None):
        if time.time() > deadline:
            return None
        rel = Path(cur).relative_to(root)
        n = 0
        for f in files:
            try:
                n += os.lstat(os.path.join(cur, f)).st_size
            except OSError:
                pass
        parts = rel.parts
        for k in range(0, min(len(parts), depth) + 1):
            key = str(root.joinpath(*parts[:k]))
            sizes[key] = sizes.get(key, 0) + n
    return [(v, k) for k, v in sizes.items()]


def find_large_files(home, min_bytes):
    """Windows 没有 Spotlight 命令：遍历常用目录（跳过 AppData 和隐藏目录）。"""
    out = []
    deadline = time.time() + 120
    for sub in ("Downloads", "Desktop", "Documents", "Videos", "Music", "Pictures"):
        base = Path(home) / sub
        if not base.is_dir():
            continue
        for cur, dirs, files in os.walk(base, onerror=lambda e: None):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in ("appdata", "node_modules")]
            if time.time() > deadline:
                return out
            for f in files:
                p = os.path.join(cur, f)
                try:
                    if os.lstat(p).st_size > min_bytes:
                        out.append(p)
                except OSError:
                    pass
    return out


def file_bytes(path):
    return os.stat(path).st_size


def running_processes():
    p = _run(["tasklist", "/fo", "csv", "/nh"], timeout=30)
    names = set()
    for row in csv.reader(io.StringIO(p.stdout)):
        if row:
            names.add(row[0])
            names.add(row[0][:-4] if row[0].lower().endswith(".exe") else row[0])
    return names


def to_trash(path, home):
    """移到回收站（可在回收站里找回）。优先 send2trash，没有就用系统自带的 VisualBasic 接口。"""
    try:
        from send2trash import send2trash
        send2trash(str(path))
        return Path("回收站") / Path(path).name
    except ImportError:
        pass
    kind = "DeleteDirectory" if os.path.isdir(path) else "DeleteFile"
    p = _ps("Add-Type -AssemblyName Microsoft.VisualBasic; "
            f"[Microsoft.VisualBasic.FileIO.FileSystem]::{kind}({_q(path)}, 'OnlyErrorDialogs', 'SendToRecycleBin')", timeout=600)
    if p.returncode != 0 or os.path.exists(path):
        raise OSError(p.stderr.strip() or "移到回收站失败")
    return Path("回收站") / Path(path).name


def reveal(path, folder):
    _run(["explorer", str(path)] if folder else ["explorer", "/select,", str(path)])


def is_package(path):
    return False


_AUMID = "RabbittuX.Purrge"
_ICON = Path(__file__).resolve().parents[2] / "assets" / "icon.png"
_AUMID_KEY = "HKCU:\\Software\\Classes\\AppUserModelId\\" + _AUMID


def notify(title, text):
    """Windows 10/11 原生通知：标题显示 Purrge 和猫咪图标；不支持时（老系统、通知被关）退回托盘气泡。"""
    toast = (
        f"$k = {_q(_AUMID_KEY)}; New-Item -Path $k -Force | Out-Null; "        # 登记应用身份（当前用户，无需管理员）
        "New-ItemProperty -Path $k -Name DisplayName -Value 'Purrge' -PropertyType String -Force | Out-Null; "
        f"New-ItemProperty -Path $k -Name IconUri -Value {_q(_ICON)} -PropertyType String -Force | Out-Null; "
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null; "
        f"$t = [Security.SecurityElement]::Escape({_q(title)}); $b = [Security.SecurityElement]::Escape({_q(text)}); "
        f"$i = ([Uri]{_q(_ICON)}).AbsoluteUri; "
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument; "
        "$x.LoadXml(\"<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text>"
        "<image placement='appLogoOverride' src='$i'/></binding></visual></toast>\"); "
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier({_q(_AUMID)}).Show("
        "[Windows.UI.Notifications.ToastNotification]::new($x))")
    if _ps(toast, timeout=30).returncode == 0:
        return "toast"
    _ps("Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
        f"$n.ShowBalloonTip(8000, {_q(title)}, {_q(text)}, 'Info'); Start-Sleep -Seconds 9; $n.Dispose()", timeout=20)
    return "balloon"


def show_alert(app_dir, free_txt, total_txt, th_txt, used_frac, snapshot=None):
    """提醒弹窗（WPF 自绘：猫咪图标 + 用量条 + 「帮我看看 / 等会儿再说」，跟随深色模式）；
    显示失败时退回系统对话框。返回 scan / later。snapshot：只把窗口画成 PNG（预览/CI 用）。"""
    args = [f"主人，磁盘只剩 {free_txt} 了", f"已经低于你定的 {th_txt} 啦。要我帮你翻翻哪些能清掉吗？删哪些，你说了算。",
            f"已用 {round(used_frac * 100)}%  ·  总容量 {total_txt}", str(used_frac),
            str(Path(app_dir) / "assets" / "icon-256.png"), "帮我看看", "等会儿再说"] + ([str(snapshot)] if snapshot else [])
    p = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-File",
              str(Path(app_dir) / "lib" / "plat" / "alert.ps1"), *args], timeout=3600)
    if p.returncode == 0 and p.stdout.strip() in ("scan", "later"):
        return p.stdout.strip()
    if snapshot:
        raise RuntimeError((p.stderr or p.stdout)[-800:])
    msg = (f"主人，磁盘只剩 {free_txt} 了，已经低于你定的 {th_txt} 啦。`n`n"
           f"已用 {round(used_frac * 100)}% · 总容量 {total_txt}`n`n要我帮你翻翻哪些能清掉吗？删哪些，你说了算。`n`n"
           "「是」= 帮我看看　「否」= 等会儿再说")
    p = _ps("Add-Type -AssemblyName System.Windows.Forms; "
            f'$r = [System.Windows.Forms.MessageBox]::Show("{msg}", "Purrge", "YesNo", "Warning", "Button1", "DefaultDesktopOnly"); '
            "Write-Output $r", timeout=3600)
    return "scan" if p.stdout.strip() == "Yes" else "later"


def monitor_file(label):
    return Path(os.environ.get("PURRGE_HOME", Path.home() / ".purrge")) / "monitor.task"


def _task_name(label):
    return "Purrge-" + label


def install_monitor(label, python, script, interval_minutes, log_path, path_env):
    py = str(python)
    if py.lower().endswith("python.exe") and os.path.exists(py[:-10] + "pythonw.exe"):
        py = py[:-10] + "pythonw.exe"   # 后台运行不弹黑色窗口
    tr = f'"{py}" "{script}" check'
    p = _run(["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(int(interval_minutes)), "/TN", _task_name(label), "/TR", tr])
    if p.returncode == 0:
        f = monitor_file(label)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_task_name(label))
    return p.returncode == 0


def uninstall_monitor(label):
    _run(["schtasks", "/Delete", "/F", "/TN", _task_name(label)])
    monitor_file(label).unlink(missing_ok=True)
    _ps(f"Remove-Item -Path {_q(_AUMID_KEY)} -Recurse -Force -ErrorAction SilentlyContinue")   # 通知用的应用身份一并清掉


def monitor_loaded(label):
    return _run(["schtasks", "/Query", "/TN", _task_name(label)]).returncode == 0


def full_disk_access():
    return None   # Windows 没有这个概念；只扫用户目录，不需要管理员权限


def default_python():
    return sys.executable or shutil.which("python") or "python"
