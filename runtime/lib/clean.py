"""执行清理：只处理用户在审查页勾选、且在本次 review.json 里的项目。删除前逐项复核。"""
import os
import shutil
import time
from pathlib import Path

import plat
from common import HOME, disk_status, du_bytes, is_protected, load_config, load_rules


def _rm(path, errors):
    def onerror(func, p, exc):
        errors.append(p)
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, onerror=onerror)
    else:
        try:
            os.remove(path)
        except OSError:
            errors.append(path)


def _to_trash(path):
    return plat.to_trash(path, HOME)


def clean(review, ids, log=print):
    cfg, rules = load_config(), load_rules()
    by_id = {it["id"]: it for it in review["items"]}
    free_before, _ = disk_status()
    results = []
    for cid in ids:
        it = by_id.get(cid)
        res = {"id": cid, "path": it["path"] if it else None, "status": "skipped", "message": "", "freedBytes": 0}
        results.append(res)
        if not it:
            res["message"] = "不在本次审查清单里"
            continue
        path = it["path"]
        if it.get("tier") == "keep" or is_protected(path, cfg, rules):
            res["message"] = "在保护名单内，已跳过"
            continue
        if not os.path.exists(path):
            res["status"], res["message"] = "gone", "已经不存在"
            continue
        if it["kind"] in ("large-file", "large-dir") and it.get("mtimeAtScan"):
            try:
                if abs(os.stat(path).st_mtime - it["mtimeAtScan"]) > 2:
                    res["message"] = "扫描之后被修改过，为安全起见跳过，请重新扫描"
                    continue
            except OSError:
                pass
        before, _ = du_bytes(path)
        errors = []
        try:
            if it.get("tier") == "optional" and cfg.get("optionalAction", "trash") == "trash" and it.get("ruleId") != "user-trash":
                dest = _to_trash(path)
                res["status"], res["message"] = "trashed", f"已移到废纸篓（{dest.name}），清空废纸篓后才会真正释放空间"
            elif it.get("mode") == "contents":
                for child in os.scandir(path):
                    _rm(child.path, errors)
                res["status"] = "deleted"
            else:
                _rm(path, errors)
                res["status"] = "deleted"
        except Exception as e:      # 单项失败也不能中断整批（#6：AttributeError 曾绕过 except OSError）
            res["status"], res["message"] = "failed", f"失败：{getattr(e, 'strerror', None) or e}"
            continue
        after, _ = du_bytes(path) if os.path.exists(path) else (0, False)
        if res["status"] == "trashed":
            res["trashedBytes"] = before          # 在废纸篓里，清空后才释放
        else:
            res["freedBytes"] = max(0, before - after)
        if errors:
            res["status"] = "partial" if res["freedBytes"] else "failed"
            res["message"] = f"有 {len(errors)} 个文件受系统保护或正在使用，未能删除（其余已清理）"
        log(f"{res['status']:8s} {path}")
    free_after, _ = disk_status()
    return {"results": results, "freeBefore": free_before, "freeAfter": free_after,
            "freedBytes": max(0, free_after - free_before), "finishedAt": time.time()}
