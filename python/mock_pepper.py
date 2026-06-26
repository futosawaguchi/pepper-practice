"""Pepper 実機が無いときに pepper.py をローカル検証するためのモック TCP サーバ。

MainActivity（app 側）の TCP プロトコルを最小限だけ模倣する:
  - ポート 2003、改行(\n)区切り、1コマンド = 1応答（1接続）。
  - 受け取ったコマンド文字列に応じて、MainActivity と同じ ACK 文字列を1行返す。

使い方:
  単体起動 :  python python/mock_pepper.py        # 127.0.0.1:2003 で待ち受け
  テスト   :  selftest_local.py から serve_in_thread() で起動して使う
"""
import base64
import io
import socketserver
import threading

# snap 応答用の小さな有効 JPEG（Pillow で生成して base64 化、初回のみ作成）
_tiny_jpeg_b64_cache = None


def _tiny_jpeg_b64():
    global _tiny_jpeg_b64_cache
    if _tiny_jpeg_b64_cache is None:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (0, 128, 255)).save(buf, format="JPEG")
        _tiny_jpeg_b64_cache = base64.b64encode(buf.getvalue()).decode("ascii")
    return _tiny_jpeg_b64_cache


def default_respond(line):
    """MainActivity.handleClient と同じ分岐で ACK を返す。"""
    if line.startswith("say:"):
        return "Finished speaking"
    if line == "stop-say":
        return "say-stopping"
    if line.startswith("go:") or line.startswith("goto:"):
        return "finished"
    if line.startswith("rotate:"):
        return "finished"
    if line.startswith("look:"):
        return "Finished looking"
    if line.startswith("snap"):
        return "image-jpeg-base64:" + _tiny_jpeg_b64()
    if line == "nod":
        return "gesture-ok:nod"
    if line.startswith("tilt"):
        return "gesture-ok:tilt:"
    if line.startswith("anim:"):
        return "gesture-ok:" + line[len("anim:"):].strip()
    return "unknown-command"


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        # pepper.py は1接続につき1行送って閉じるが、複数行にも一応対応
        for raw in self.rfile:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            with self.server.lock:
                self.server.received.append(line)
            resp = self.server.respond(line)
            self.wfile.write((resp + "\n").encode("utf-8"))
            self.wfile.flush()


class MockPepperServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host="127.0.0.1", port=2003, respond=None):
        super().__init__((host, port), _Handler)
        self.received = []          # 受信したコマンド文字列（テストで検証）
        self.lock = threading.Lock()
        self.respond = respond or default_respond


def serve_in_thread(host="127.0.0.1", port=2003, respond=None):
    """サーバを別スレッドで起動して (server, thread) を返す。"""
    server = MockPepperServer(host, port, respond)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


if __name__ == "__main__":
    server, _ = serve_in_thread()
    print(f"Mock Pepper server listening on {server.server_address} (Ctrl+C で停止)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nbye")
        server.shutdown()
