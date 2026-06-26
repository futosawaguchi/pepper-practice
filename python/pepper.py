import os
import socket
from concurrent.futures import ThreadPoolExecutor
import base64
from PIL import Image
import time
import threading
from dotenv import load_dotenv

# Pepper の IP はソースに直書きせず、python/.env（gitignore 済）から読む。
# 既存の環境変数があればそちらを優先（override=False）。実機が無い間は 127.0.0.1（モックサーバ）。
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
pepper_ips = [ip.strip() for ip in os.environ.get("PEPPER_IPS", "127.0.0.1").split(",") if ip.strip()]
pepper_port = int(os.environ.get("PEPPER_PORT", "2003"))
ENABLE_ASYNC = True  # False で同期動作に戻す
_speech_lock = threading.Lock()  # 発話は全端末で一本化する
_speech_executor = None


def _get_speech_executor():
    """Provide a shared single-worker executor for all speak commands."""
    global _speech_executor
    if _speech_executor is None:
        _speech_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="pepper-speech"
        )
    return _speech_executor


def receive_response(sock):
    """Receive response text, handling large payloads such as Base64 snapshots."""
    chunks = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b'\n' in chunk:
            break
    return b"".join(chunks).decode('utf-8').strip()


def send_message(message, dev):
    """ Android アプリにメッセージを送信する関数 """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            client_socket.connect((pepper_ips[dev], pepper_port))
            print(f"接続成功: {pepper_ips[dev]}:{pepper_port}")
            # メッセージを送信
            client_socket.sendall(message.encode('utf-8') + b'\n')
            print(f"送信: {message}")
            # 応答を受信
            response = receive_response(client_socket)
            if message.startswith("snap"):
                return decode_image(response, "./output/snap.png", show=True)
            else:
                print(f"受信: {response}")
    except Exception as e:
        print(f"エラー: {e}")


class Pepper_action:
    def __init__(self, dev, enable_async=None):
        """Wrap Pepper socket commands, optionally dispatching them via a single worker."""
        self.dev = dev
        if enable_async is None:
            enable_async = ENABLE_ASYNC
        self._async_enabled = bool(enable_async)
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"pepper-{dev}"
        ) if self._async_enabled else None

    def _dispatch(self, message):
        if self._executor:
            return self._executor.submit(send_message, message, self.dev)
        send_message(message, self.dev)
        return None

    def _send_speak(self, message):
        # 発話は他の端末と順番待ちで直列化する
        with _speech_lock:
            return send_message(message, self.dev)

    def _dispatch_speak(self, message):
        speech_executor = _get_speech_executor()
        future = speech_executor.submit(self._send_speak, message)
        if self._async_enabled:
            return future
        return future.result()

    def speak(self, content, tone=50, spd=100):
        # tone: 0~100
        # spd: 50~200
        return self._dispatch_speak(f"say:{tone}:{spd}:{content}")

    def go(self, dis):
        return self._dispatch(f"go:{dis}")

    def rotate(self, deg):
        return self._dispatch(f"rotate:{deg}")

    def look(self, direction, full_body=False):
        if direction == -1:
            print("Look right")
            cmd = "look:fullBody:right" if full_body else "look:onlyHead:right"
        elif direction == 1:
            print("Look left")
            cmd = "look:fullBody:left" if full_body else "look:onlyHead:left"
        else:
            print("Look center")
            cmd = "look:fullBody:center"
        return self._dispatch(cmd)

    def snap(self):  # 1280x960
        return self._dispatch("snap")

    def nod(self):
        return self._dispatch("nod")

    def tilt(self):
        return self._dispatch("tilt")

    def shutdown(self, wait=True):
        if self._executor:
            self._executor.shutdown(wait=wait)


def decode_image(image_base64, output_path, show=False):
    """ Base64 エンコードされた画像データをデコードして保存する関数 """
    try:
        if ":" in image_base64:
            _, image_base64 = image_base64.split(":", 1)
        # Remove whitespace and fix missing padding
        image_base64 = "".join(image_base64.split())
        padding = (-len(image_base64)) % 4
        if padding:
            image_base64 += "=" * padding
        # Base64 デコード
        image_data = base64.b64decode(image_base64)
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        # バイナリデータをファイルに書き込む
        with open(output_path, 'wb') as file:
            file.write(image_data)
        print(f"画像が保存されました: {output_path}")
        if show:
            # 画像を表示
            image = Image.open(output_path)
            image.show()
    except Exception as e:
        print(f"エラー: {e}")


if __name__ == "__main__":
    # テスト用コード: 二体を想定し、発話中に相手へ look 指示を送る例
    p1 = Pepper_action(dev=0, enable_async=ENABLE_ASYNC)
    try:
        p1.speak("こんにちは、私はペパこです。今から頷くぜ", tone=70, spd=100)
    finally:
        p1.shutdown()
