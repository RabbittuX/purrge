"""本地审查服务：只监听 127.0.0.1，带一次性口令；清理完成或闲置 30 分钟自动关闭。"""
import json
import os
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import plat
from clean import clean
from common import WEB_DIR, disk_status, load_config, save_config
from volume_scan import fixed_volumes, save_volume_scan, scan_volume, with_volume_scans

IDLE_LIMIT = 30 * 60
WORDS = {"访达": plat.FILE_MANAGER, "废纸篓": "回收站" if plat.NAME == "Windows" else "废纸篓"}


def localize(text):
    """macOS 原样返回；Windows 把「访达 / 废纸篓」换成「资源管理器 / 回收站」。"""
    for a, b in WORDS.items():
        if a != b:
            text = text.replace(a, b)
    return text


def serve(run_dir, open_browser=True, log=print):
    run_dir = Path(run_dir)
    review = json.loads((run_dir / "review.json").read_text(encoding="utf-8"))
    token = secrets.token_urlsafe(16)
    state = {"last": time.time(), "done": False, "busy": False}
    scan_lock = threading.Lock()
    def current_review():
        return with_volume_scans(run_dir, review)
    page = localize((WEB_DIR / "review.html").read_text(encoding="utf-8"))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _authed(self):
            return self.headers.get("X-DG-Token") == token or f"token={token}" in self.path

        def do_GET(self):
            state["last"] = time.time()
            if urlsplit(self.path).path == "/":
                return self._send(200, page.encode(), "text/html")
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            if urlsplit(self.path).path == "/api/review":
                free, total = disk_status()
                data = {"review": current_review(), "config": load_config(), "freeBytes": free, "totalBytes": total, "volumes": fixed_volumes()}
                try:
                    import update
                    if update.available():
                        data["update"] = update.available()
                except Exception:
                    pass
                return self._send(200, data)
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            state["last"] = time.time()
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/scan-volume":
                volume = body.get("volume")
                allowed = next((v for v in fixed_volumes() if isinstance(volume, str) and volume.casefold() == v.casefold()), None)
                if plat.NAME != "Windows" or not allowed:
                    return self._send(400, {"error": "请选择当前可读的本地固定盘"})
                with scan_lock:
                    if state["done"] or state["busy"]:
                        return self._send(409, {"error": "当前审查已结束或正在处理，请重新扫描"})
                    state["busy"] = True
                try:
                    result = scan_volume(allowed, load_config())
                    save_volume_scan(run_dir, allowed, result)
                    free, total = disk_status()
                    return self._send(200, {"review": current_review(), "volumes": fixed_volumes(),
                                            "freeBytes": free, "totalBytes": total})
                except OSError as e:
                    return self._send(500, {"error": "无法完成本地扫描：" + str(e)[:160]})
                finally:
                    state["busy"] = False
            if self.path == "/api/clean":
                ids = [str(i) for i in body.get("ids", [])]
                try:
                    out = clean(current_review(), ids, log=log)
                except Exception as e:   # 兜底：哪怕整批崩了也要回 JSON，不能只回 500 让前端一直转圈（#6）
                    log(f"clean failed: {e!r}")
                    return self._send(200, {"results": [], "freedBytes": 0, "error": f"清理失败：{e}"})
                for r in out["results"]:
                    r["message"] = localize(r.get("message", ""))
                (run_dir / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
                state["done"] = True
                return self._send(200, out)
            if self.path == "/api/config":
                cfg = load_config()
                for k in ("thresholdGB", "intervalMinutes", "cooldownHours", "optionalAction"):
                    if k in body:
                        cfg[k] = body[k]
                old_interval = load_config().get("intervalMinutes")
                save_config(cfg)
                if cfg.get("intervalMinutes") != old_interval:   # 检查频率要重新注册后台任务才生效
                    from dg import install_monitor
                    install_monitor(cfg)
                return self._send(200, {"ok": True, "config": cfg})
            if self.path == "/api/reveal":          # 在访达中打开（只允许本次清单里的项目，只看不改）
                it = next((x for x in current_review()["items"] if x["id"] == str(body.get("id"))), None)
                if not it or not os.path.exists(it["path"]):
                    return self._send(200, {"ok": False})
                folder = os.path.isdir(it["path"]) and not plat.is_package(it["path"])
                plat.reveal(it["path"], folder)
                return self._send(200, {"ok": True, "opened": "folder" if folder else "file"})
            if self.path == "/api/close":
                state["done"] = True
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{httpd.server_port}/?token={token}"
    (run_dir / "review-url.txt").write_text(url)

    def watchdog():
        while True:
            time.sleep(5)
            idle = time.time() - state["last"]
            if idle > IDLE_LIMIT or (state["done"] and idle > 120):
                httpd.shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()
    log(f"审查页面：{url}")
    if open_browser:
        webbrowser.open(url)
    httpd.serve_forever()
    return run_dir / "result.json"
