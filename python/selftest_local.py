"""Pepper 実機なしのローカル動作確認（自動テスト）。

モック TCP サーバ（mock_pepper.py）を立て、pepper.py の Pepper_action / decode_image を
end-to-end で検証する:
  1. 各コマンドが正しい文字列で送信されること（モックの received と照合）。
  2. snap の往復＋画像デコード（Base64 → 保存 → Pillow で開ける）こと。

実行:  python python/selftest_local.py   （venv 有効化後）
"""
import os
import socket as _socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

_failures = []


def check(name, cond):
    print(("  OK   " if cond else "  FAIL ") + name)
    if not cond:
        _failures.append(name)


def _free_port():
    s = _socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    # pepper.py はモジュール読込時に IP/PORT を読むので、import より前に環境変数を設定する。
    port = _free_port()
    os.environ["PEPPER_IPS"] = "127.0.0.1"
    os.environ["PEPPER_PORT"] = str(port)

    sys.path.insert(0, HERE)
    import mock_pepper
    import pepper  # noqa: E402（環境変数設定後に import する必要がある）
    from PIL import Image

    # 画像ビューア（Image.show）はテスト中に開かないよう無効化
    pepper.Image.Image.show = lambda *a, **k: None

    server, _ = mock_pepper.serve_in_thread(host="127.0.0.1", port=port)
    print(f"mock server: 127.0.0.1:{port}\n")

    snap_path = os.path.join(os.getcwd(), "output", "snap.png")
    if os.path.exists(snap_path):
        os.remove(snap_path)

    # --- 同期モードでコマンドを実行（呼び出し順 = 送信順） ---
    p = pepper.Pepper_action(dev=0, enable_async=False)
    p.speak("こんにちは", tone=70, spd=100)
    p.speak("hi")               # 既定 tone=50, spd=100
    p.go(0.3)
    p.rotate(90)
    p.look(-1)                  # onlyHead:right
    p.look(1, full_body=True)   # fullBody:left
    p.look(0)                   # fullBody:center
    p.nod()
    p.tilt()
    p.snap()                    # snap → image-jpeg-base64 → decode_image
    p.shutdown()

    expected = [
        "say:70:100:こんにちは",
        "say:50:100:hi",
        "go:0.3",
        "rotate:90",
        "look:onlyHead:right",
        "look:fullBody:left",
        "look:fullBody:center",
        "nod",
        "tilt",
        "snap",
    ]

    print("[1] コマンド送信内容の検証")
    received = list(server.received)
    check(f"送信コマンド列が期待どおり ({len(expected)}件)", received == expected)
    if received != expected:
        print("    expected:", expected)
        print("    received:", received)

    print("\n[2] snap の画像デコード検証")
    check("output/snap.png が生成された", os.path.exists(snap_path))
    if os.path.exists(snap_path):
        try:
            with Image.open(snap_path) as im:
                im.verify()
            check("保存画像を Pillow で開ける", True)
        except Exception as e:
            check(f"保存画像を Pillow で開ける（{e}）", False)

    print("\n[3] decode_image 単体（パディング補正つき）")
    import base64
    import io
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    tmp = os.path.join(os.getcwd(), "output", "_unit.png")
    pepper.decode_image("image-jpeg-base64:" + b64, tmp, show=False)
    check("decode_image が出力ファイルを作成", os.path.exists(tmp))

    server.shutdown()

    print("\n==============================")
    if _failures:
        print(f"RESULT: FAIL ({len(_failures)} 件)")
        for f in _failures:
            print("  - " + f)
        sys.exit(1)
    print("RESULT: ALL PASS")


if __name__ == "__main__":
    main()
