"""Bounded, read-only large-file inventory for an explicitly selected Windows disk."""
import heapq
import json
import os
import stat
import sys
import time
import uuid
from collections import deque
from pathlib import Path

def load_rules():
    app_dir = Path(__file__).resolve().parents[1]
    name = "registry.win.json" if sys.platform == "win32" else "registry.json"
    return json.loads((app_dir / "rules" / name).read_text(encoding="utf-8"))


MIB = 1024 * 1024
PACKAGES = {".msi", ".msix", ".msixbundle", ".appx", ".appxbundle"}
ARCHIVES = {".zip", ".7z", ".rar", ".iso", ".tar", ".gz", ".xz"}
COMPONENTS = {".exe", ".msp", ".cab"}
SMALLER = PACKAGES | ARCHIVES | COMPONENTS
SKIP_DIRS = {
    "windows", "windowsapps", "wpsystem", "system volume information", "$recycle.bin",
    "program files", "program files (x86)", "programdata", "appdata", "apps", "agent",
    "steam", "steamlibrary", "steamapps", "wegameapps", "wudownloadcache",
    "deliveryoptimization", "node_modules", "site-packages", "venv", "__pycache__",
}
PROJECT_MARKERS = (".git", ".hg", ".svn")
SKIP_ATTRIBUTES = 0x400 | 0x4 | 0x2


def fixed_volumes():
    """Return accessible Windows fixed drive roots (for example C:\\ and D:\\)."""
    if os.name != "nt":
        return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    get_type = ctypes.windll.kernel32.GetDriveTypeW
    return [f"{chr(65 + i)}:\\" for i in range(26)
            if mask & (1 << i) and get_type(f"{chr(65 + i)}:\\\\") == 3]


def scan_volume(root, cfg, seconds=12, limit=40, package_min=100 * MIB, other_min=500 * MIB):
    root = Path(root).resolve(strict=True)
    rules = load_rules()
    protected = tuple(os.path.normcase(str(Path(p).resolve())) for p in
                      cfg.get("protect", []) + rules.get("protected", []) +
                      [os.environ[k] for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
                       if os.environ.get(k)])

    def excluded(path):
        key = os.path.normcase(str(path))
        if any(key == p or key.startswith(p.rstrip(os.sep) + os.sep) for p in protected):
            return True

    pending, largest = deque([root]), []
    read_count = matched = errors = 0
    deadline = time.monotonic() + seconds
    capped = False
    while pending and not capped:
        if time.monotonic() >= deadline:
            capped = True
            break
        folder = pending.popleft()
        try:
            if folder.resolve(strict=True) != folder or any((folder / n).exists() for n in PROJECT_MARKERS) or excluded(folder):
                continue
            with os.scandir(folder) as entries:
                for entry in entries:
                    if read_count >= 150000 or time.monotonic() >= deadline:
                        capped = True
                        break
                    read_count += 1
                    if entry.name.startswith("."):
                        continue
                    path = Path(entry.path)
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        errors += 1
                        continue
                    if getattr(info, "st_file_attributes", 0) & SKIP_ATTRIBUTES or excluded(path):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        if entry.name.casefold() not in SKIP_DIRS:
                            pending.append(path)
                        continue
                    suffix = path.suffix.casefold()
                    minimum = package_min if suffix in SMALLER else other_min
                    if not stat.S_ISREG(info.st_mode) or info.st_size < minimum:
                        continue
                    matched += 1
                    row = (info.st_size, str(path), info.st_mtime_ns, suffix)
                    if len(largest) < limit:
                        heapq.heappush(largest, row)
                    else:
                        heapq.heappushpop(largest, row)
        except OSError:
            errors += 1

    items = []
    for size, raw, mtime_ns, suffix in sorted(largest, reverse=True):
        path = Path(raw)
        try:
            if path.resolve(strict=True) != path or excluded(path):
                continue
            current = path.stat()
            if current.st_size != size or current.st_mtime_ns != mtime_ns:
                continue
        except OSError:
            errors += 1
            continue
        tier, reason = "keep", "其他大文件，仅供定位和核对用途"
        if suffix in PACKAGES:
            tier, reason = "optional", "安装包，请确认重装或回退时是否仍需要"
        elif suffix in ARCHIVES:
            tier, reason = "optional", "压缩归档或镜像，请确认内容、用途和备份"
        elif suffix == ".exe":
            reason = "可执行文件，请核对是安装包还是软件本体"
        elif suffix in COMPONENTS:
            reason = "可能是安装所需的补丁或组件，先保留"
        mtime = mtime_ns / 1e9
        items.append({
            "id": "v" + uuid.uuid4().hex, "path": raw, "volume": str(root),
            "name": path.name, "kind": "large-file", "mode": "whole",
            "sizeBytes": size, "tier": tier, "defaultTier": tier, "reason": reason,
            "impactHint": reason, "mtimeAtScan": mtime, "lastUsed": mtime,
            "regenerable": False, "scanLimited": False, "appsRunning": [],
        })
    return {"path": str(root), "scannedAt": time.time(), "partial": capped or bool(errors),
            "truncated": matched > limit, "readEntries": read_count, "items": items}


def save_volume_scan(run_dir, volume, result):
    letter = Path(volume).drive[0].upper()
    destination = Path(run_dir) / f"volume-{letter}.json"
    temporary = destination.with_suffix("." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, destination)


def with_volume_scans(run_dir, review):
    items = list(review["items"])
    seen = {os.path.normcase(item["path"]) for item in items}
    scans = {}
    for file in sorted(Path(run_dir).glob("volume-?.json")):
        root = file.stem[-1].upper() + ":\\"
        try:
            scan = json.loads(file.read_text(encoding="utf-8"))
            extra = scan.pop("items")
            if scan["path"].casefold() != root.casefold() or not isinstance(extra, list):
                raise ValueError("unexpected scan data")
            for item in extra:
                if Path(item["path"]).anchor.casefold() != root.casefold():
                    raise ValueError("unexpected candidate volume")
                key = os.path.normcase(item["path"])
                if key not in seen:
                    items.append(item)
                    seen.add(key)
            scans[root] = scan
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            scans[root] = {"error": "快扫记录无法读取，请重新扫描"}
    return dict(review, items=items, volumeScans=scans)
