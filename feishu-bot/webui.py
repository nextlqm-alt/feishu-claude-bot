"""本地监控面板——Python 标准库 HTTP Server + SSE 推送"""

import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from queue import Queue

import log

# SSE 订阅者队列: 每个订阅者收到新事件推送
_subscribers: list[Queue] = []

_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Feishu-Claude 监控</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font:13px/1.5 'JetBrains Mono','SF Mono',monospace;background:#1a1b26;color:#a9b1d6;padding:16px}
h1{color:#7dcfff;font-size:16px;margin-bottom:12px}
.event{padding:4px 8px;border-left:3px solid transparent;margin:2px 0;white-space:pre-wrap;word-break:break-all}
.event:hover{background:#24283b}
.type-👤{border-left-color:#9ece6a;color:#9ece6a}
.type-💭{border-left-color:#565f89;color:#565f89;font-style:italic}
.type-🔧{border-left-color:#e0af68;color:#e0af68}
.type-✅{border-left-color:#73daca;color:#73daca}
.type-❌{border-left-color:#f7768e;color:#f7768e}
.type-🤖{border-left-color:#7dcfff;color:#7dcfff}
.meta{color:#565f89;font-size:11px}
#count{color:#e0af68}
</style></head><body>
<h1>🔍 Feishu ↔ Claude Code <span id="count"></span></h1>
<div id="events"></div>
<script>
const es = document.getElementById('events');
const evt = new EventSource('/stream');
let count = 0;
evt.onmessage = (e) => {
    const data = JSON.parse(e.data);
    for (const ev of data) {
        count++;
        const div = document.createElement('div');
        div.className = 'event type-' + ev.type;
        div.innerHTML = `<span class="meta">${ev.time} [${ev.chat}] ${ev.type}</span> ${esc(ev.content)}`;
        es.prepend(div);
    }
    if (es.children.length > 200) {
        while (es.children.length > 200) es.lastChild.remove();
    }
    document.getElementById('count').textContent = `(${count} 条)`;
};
function esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._html()
        elif self.path == "/stream":
            self._sse()
        elif self.path == "/log.json":
            self._json()
        else:
            self.send_error(404)

    def _html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_HTML.encode())

    def _json(self):
        data = json.dumps(list(log.events), ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q: Queue = Queue()
        _subscribers.append(q)
        last_idx = len(log.events)

        try:
            while True:
                # 检查新事件
                current = list(log.events)[last_idx:]
                if current:
                    data = json.dumps(current, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode())
                    self.wfile.flush()
                    last_idx = len(log.events)

                # 等待推送或超时
                try:
                    q.get(timeout=2)
                except:
                    pass  # 超时，重新检查
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            _subscribers.remove(q)

    def log_message(self, *args):
        pass  # 静默 HTTP 日志


def _notify():
    """通知所有 SSE 订阅者有新事件"""
    for q in _subscribers:
        try:
            q.put_nowait(True)
        except:
            pass


# Monkey-patch log.add 以触发 SSE 通知
_orig_add = log.add


def _add_with_notify(chat_id, event_type, content, detail=None):
    _orig_add(chat_id, event_type, content, detail)
    _notify()


log.add = _add_with_notify


def start(port: int = 8080):
    """在后台线程启动 Web 服务器"""
    server = HTTPServer(("0.0.0.0", port), Handler)

    def _run():
        print(f"  本地监控 → http://localhost:{port}")
        server.serve_forever()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return server
