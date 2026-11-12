"""AI 判断：读 candidates.json，给每项定档（首要清理 / 需你决定 / 不清理）并写一句中文说明 → review.json。
AI 引擎可以是 Claude Code、Codex、WorkBuddy、DeepSeek Harness 或 Pi（见 engines.py），都只读、不能执行删除；AI 不可用时按知识库规则兜底。"""
import json
import re
import sys
import time
from pathlib import Path

import engines
from common import APP_DIR, human, load_config, save_config

PROMPT_FILE = APP_DIR / "rules" / ("ai-rules.win.md" if sys.platform == "win32" else "ai-rules.md")   # 提示词按系统分开，和 registry 一样


def _brief(items):
    now = time.time()
    out = []
    for it in items:
        days = int((now - it["lastUsed"]) / 86400) if it.get("lastUsed") else None
        out.append({"id": it["id"], "path": it["path"].replace(str(Path.home()), "~"), "size": human(it["sizeBytes"]),
                    "kind": it["kind"], "knownName": it.get("name"), "defaultTier": it["defaultTier"],
                    "regenerable": it["regenerable"], "hint": it.get("impactHint", ""),
                    "appsRunning": it.get("appsRunning", []), "protected": it.get("protected", False),
                    "daysSinceUsed": days})
    return out


def fallback(it):
    tier = "keep" if it.get("protected") else it["defaultTier"]
    kind_title = {"large-file": "大文件", "large-dir": "大文件夹", "app-cache": "应用缓存"}.get(it["kind"], "")
    reason = it.get("impactHint") or ("用户文件，请确认不再需要后再删除" if it["kind"] in ("large-file", "large-dir") else "")
    if it.get("protected"):
        reason = "在保护名单内，不会清理"
    return {"tier": tier, "title": it.get("name") or kind_title, "reason": reason, "category": kind_title or "缓存"}


def classify(candidates, log=print):
    cfg = load_config()
    items = candidates["items"]
    result = {it["id"]: fallback(it) for it in items}
    summary, source = "", "rules"
    engine = cfg.get("aiEngine")
    if items and engine in engines.NAMES:
        prompt = PROMPT_FILE.read_text(encoding="utf-8") + "\n\n## 候选清单\n```json\n" + \
            json.dumps(_brief(items), ensure_ascii=False) + "\n```\n"
        log(f"{engines.NAMES[engine]} 正在判断每一项能不能清理…")
        try:
            text, model = engines.ask(cfg, prompt, log=log)
            if model != (cfg.get(f"{engine}Model") or ""):      # 换过模型就记住，下次直接用
                fresh = load_config()
                fresh[f"{engine}Model"] = model
                save_config(fresh)
            m = re.search(r"\{.*\}", text, re.S)
            data = json.loads(m.group(0)) if m else {}
            for row in data.get("items", []):
                rid = row.get("id")
                if rid not in result:
                    continue
                it = next(x for x in items if x["id"] == rid)
                tier = row.get("tier")
                if tier not in ("primary", "optional", "keep"):
                    continue
                if it.get("protected"):
                    tier = "keep"                       # 保护名单永远优先于 AI
                if tier == "primary" and it["kind"] in ("large-file", "large-dir"):
                    tier = "optional"                   # 用户文件永远不进"首要清理"
                result[rid] = {"tier": tier, "title": row.get("title") or result[rid]["title"],
                               "reason": row.get("reason") or result[rid]["reason"],
                               "category": row.get("category") or result[rid]["category"]}
            summary = data.get("summary", "")
            source = "ai" if data.get("items") else "rules"
            if source == "rules":
                log("AI 没有返回可用结果，改用规则判断。")
        except (engines.AIError, json.JSONDecodeError, StopIteration) as e:
            log(f"AI 判断不可用（{str(e)[:200] or type(e).__name__}），改用规则判断。")
    review = dict(candidates)
    review["items"] = [dict(it, **result[it["id"]]) for it in items]
    review["summary"] = summary
    review["judgedBy"] = source
    review["engine"] = engines.NAMES.get(engine, "") if source == "ai" else ""
    review["generatedAt"] = time.time()
    return review


if __name__ == "__main__":
    import sys
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name("review.json")
    rv = classify(json.loads(src.read_text(encoding="utf-8")))
    out.write_text(json.dumps(rv, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"判断来源：{rv['judgedBy']} → {out}")
