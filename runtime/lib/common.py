"""purrge 公共工具：路径、配置、磁盘空间、目录大小。"""
import fnmatch
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

VERSION = "0.3.3"
OFFICIAL = "GitHub RabbittuX/purrge"     # 唯一官方来源

HOME = Path.home()
DG_HOME = Path(os.environ.get("PURRGE_HOME", HOME / ".purrge"))
APP_DIR = Path(__file__).resolve().parent.parent          # runtime/
import sys  # noqa: E402
RULES = APP_DIR / "rules" / ("registry.win.json" if sys.platform == "win32" else "registry.json")
WEB_DIR = APP_DIR / "web"
CONFIG = DG_HOME / "config.json"
RUNS = DG_HOME / "runs"

DEFAULT_CONFIG = {
    "thresholdGB": 15,          # 剩余空间低于这个值就提醒
    "intervalMinutes": 30,      # 后台检查频率
    "cooldownHours": 6,         # 提醒过一次后，多久内不再打扰
    "optionalAction": "trash",  # "需你决定"的项目：trash=移到废纸篓（可找回）delete=直接删除
    "protect": [],              # 额外的保护路径（永不清理）
    "aiEngine": "",             # claude / codex，安装时选择；留空 = 只用规则判断
    "claudePath": "",           # 安装时自动探测
    "codexPath": "",
    "claudeModel": "",          # 留空用默认模型
    "codexModel": "",
    "workbuddyPath": "",
    "deepseekPath": "",
    "workbuddyModel": "",       # 留空用 CodeBuddy 默认模型
    "deepseekModel": "",           # 留空用默认模型；不可用时自动换成账号能用的模型
    "language": "zh",
}


def expand(p):
    out = Path(os.path.expandvars(os.path.expanduser(p)))
    if sys.platform == "win32" and "~" in str(out) and out.exists():   # %TEMP% 常是 C:\Users\ABCDEF~1 这种 8.3 短名，换成完整路径给人看
        out = Path(os.path.realpath(out))
    return out


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG.is_file():
        try:
            cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    if not cfg.get("aiEngine") and cfg.get("claudePath"):     # 0.1 版只有 Claude
        cfg["aiEngine"] = "claude"
    if cfg.get("aiModel") and not cfg.get("claudeModel"):
        cfg["claudeModel"] = cfg["aiModel"]
    cfg.pop("aiModel", None)
    return cfg


def save_config(cfg):
    DG_HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_rules():
    return json.loads(RULES.read_text(encoding="utf-8"))


from plat import data_volume, disk_status, du_bytes, running_processes  # noqa: E402,F401  系统相关实现见 plat/


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit in ("GB", "TB") else f"{n:.0f}{unit}"
        n /= 1024


def _resolved(raw):
    p = expand(raw)
    try:
        return p.resolve()
    except OSError:
        return p


def _exempt(path, rules):
    """规则库 protectExempt 里明确写出的缓存目录（* 只匹配一级目录），可以穿过宽泛的保护目录。"""
    for raw in rules.get("protectExempt", []):
        parts = expand(raw).parts
        n = next((i for i, s in enumerate(parts) if any(c in s for c in "*?[")), len(parts))
        pat = _resolved(str(Path(*parts[:n]))).parts + parts[n:]
        if len(path.parts) >= len(pat) and all(
                fnmatch.fnmatch(a, b) if i >= len(pat) - len(parts[n:]) else os.path.normcase(a) == os.path.normcase(b)
                for i, (a, b) in enumerate(zip(path.parts, pat))):
            return True
    return False


def is_protected(path, cfg, rules):
    path = Path(path).resolve()
    for raw in cfg.get("protect", []):           # 用户自己加的保护永远优先
        prot = _resolved(raw)
        if path == prot or prot in path.parents or path in prot.parents:
            return True
    exempt = _exempt(path, rules)
    for raw in rules.get("protected", []):
        prot = _resolved(raw)
        if path == prot or path in prot.parents:
            return True
        if prot in path.parents and not exempt:  # 豁免只放行「上层整体保护」，自身或里面受保护的照旧
            return True
    return False


def new_run_dir():
    d = RUNS / time.strftime("%Y%m%d-%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    # 只保留最近 10 次
    runs = sorted(p for p in RUNS.iterdir() if p.is_dir())
    for old in runs[:-10]:
        shutil.rmtree(old, ignore_errors=True)
    return d


def latest_run():
    if not RUNS.is_dir():
        return None
    runs = sorted(p for p in RUNS.iterdir() if p.is_dir())
    return runs[-1] if runs else None
