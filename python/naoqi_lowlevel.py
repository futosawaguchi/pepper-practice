"""NAOqi 2.9 へ Python から直接つないで ALMotion で関節を角度（ラジアン）制御する低レベルツール。

QiSDK アプリ（pepper.py の TCP ブリッジ）とは別系統。QiSDK では関節角の直接指定ができないため、
内部で動いている NAOqi の ALMotion サービスへ libqi(qi) で直結する。
※ 非公式・自己責任。2.9 は user/password＋TLS（ポート9503）必須。接続が不安定な既知問題あり。

準備:
  pip install -r python/requirements-naoqi.txt        # qi(libqi-python)
  cp python/.env.example python/.env                  # PEPPER_IPS / PEPPER_USER / PEPPER_PASSWORD を実値に

使い方:
  python python/naoqi_lowlevel.py services            # 接続確認＆サービス一覧（ALMotion があるか）
  python python/naoqi_lowlevel.py arm                 # デモ: 右腕を少し上げる
  python python/naoqi_lowlevel.py angles "RShoulderPitch=0.5,RElbowRoll=1.0" --speed 0.2
  python python/naoqi_lowlevel.py rest                # 力を抜く（rest）
  python python/naoqi_lowlevel.py enable-life         # 自律機能を戻す（solitary）

注意: 周囲に人や物が無いことを確認してから動かすこと。速度は控えめ(0.2)。
"""
import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# 重要: NAOqi（ALMotion）はロボット「頭部」で動く。胸部 Android タブレット（PEPPER_IPS）とは別IP。
#   タブレット = QiSDKアプリ側のIP / ロボット頭部 = ssh nao@<このIP> で入れる方（実値は python/.env に）
# PEPPER_NAOQI_IP を優先。未設定なら PEPPER_IPS[0] にフォールバック（多くの場合これは誤り＝タブレット）。
_tablet_ips = [ip.strip() for ip in os.environ.get("PEPPER_IPS", "127.0.0.1").split(",") if ip.strip()]
IP = os.environ.get("PEPPER_NAOQI_IP", "").strip() or (_tablet_ips[0] if _tablet_ips else "127.0.0.1")
PORT = int(os.environ.get("PEPPER_NAOQI_PORT", "9559"))
USER = os.environ.get("PEPPER_USER", "nao")
PASSWORD = os.environ.get("PEPPER_PASSWORD", "")


def _candidate_urls():
    """接続候補。標準ポート 9559 と 2.9 のTLS用 9503、各々 tcps→tcp の順で試す。"""
    ports = []
    for p in (PORT, 9559, 9503):
        if p not in ports:
            ports.append(p)
    urls = []
    for p in ports:
        urls.append(f"tcps://{IP}:{p}")
        urls.append(f"tcp://{IP}:{p}")
    return urls


def _make_factory(user, password):
    """libqi が要求する Authenticator/AuthenticatorFactory（user+token を返す）。"""
    class Authenticator:
        def initialAuthData(self):
            return {"user": user, "token": password}

    class AuthenticatorFactory:
        def newAuthenticator(self):
            return Authenticator()

    return AuthenticatorFactory()


def connect():
    """NAOqi 2.9 に認証付きで接続して qi.Session を返す。tcps:// を優先し tcp:// にフォールバック。"""
    try:
        import qi
    except ImportError:
        sys.exit("qi が未導入です。`pip install -r python/requirements-naoqi.txt` を実行してください。")

    if not PASSWORD:
        print("警告: PEPPER_PASSWORD が空です。python/.env に実パスワードを設定してください。", file=sys.stderr)
    if not os.environ.get("PEPPER_NAOQI_IP"):
        print("注意: PEPPER_NAOQI_IP 未設定。NAOqi はロボット頭部のIP（タブレット PEPPER_IPS とは別）です。"
              f" 今は {IP} に接続しようとしています。", file=sys.stderr)

    last_err = None
    for url in _candidate_urls():
        try:
            session = qi.Session()
            session.setClientAuthenticatorFactory(_make_factory(USER, PASSWORD))
            session.connect(url)
            print(f"接続成功: {url} (user={USER})")
            return session
        except Exception as e:  # noqa: BLE001 接続失敗の種類は多様なので握って次を試す
            last_err = e
            print(f"接続失敗: {url} -> {e}")
    sys.exit(
        "NAOqi に接続できませんでした。確認:\n"
        "  - PEPPER_NAOQI_IP が『ロボット頭部』のIPか（ssh nao@<このIP> で入れる方。タブレットの PEPPER_IPS とは別）\n"
        "  - python/.env の PEPPER_USER / PEPPER_PASSWORD が正しいか\n"
        "  - ロボットと同じ Wi-Fi にいるか、ポート 9559/9503 に到達できるか\n"
        "  - qi のバージョン（>=3.1.5 推奨）。2.9 のリモート接続は既知の不安定さあり（libqi-python issue #22）\n"
        "  - リモートがダメなら ssh でロボットに入り、ローカルの qicli / python で ALMotion を叩く方が確実\n"
        f"  最後のエラー: {last_err}"
    )


def _prepare_motion(session, disable_life=True):
    """動かす前準備: 自律機能を止めて wakeUp（関節にスティフネスを入れる）。"""
    motion = session.service("ALMotion")
    if disable_life:
        try:
            life = session.service("ALAutonomousLife")
            if life.getState() != "disabled":
                life.setState("disabled")
                time.sleep(1.0)
        except Exception as e:  # noqa: BLE001
            print(f"注意: ALAutonomousLife を無効化できませんでした: {e}")
    motion.wakeUp()
    return motion


def _service_name(s):
    # libqi-python のバージョンにより services() は dict のリスト or オブジェクトのリスト
    if isinstance(s, dict):
        return s.get("name") or s.get("serviceName") or str(s)
    n = getattr(s, "name", None)
    return n() if callable(n) else (n or str(s))


def cmd_services(args):
    session = connect()
    names = sorted(_service_name(s) for s in session.services())
    print(f"サービス数: {len(names)}")
    for n in names:
        print("  " + n)
    print("\nALMotion: " + ("あり ✓" if "ALMotion" in names else "なし ✗"))


def cmd_arm(args):
    session = connect()
    motion = _prepare_motion(session, disable_life=not args.keep_life)
    # 右腕を少し上げるデモ（すべてラジアン）。値は安全のため控えめ。
    names = ["RShoulderPitch", "RElbowRoll"]
    angles = [0.5, 1.0]
    print(f"setAngles {names} = {angles} (speed={args.speed})")
    motion.setAngles(names, angles, args.speed)
    time.sleep(3.0)
    print("rest() で力を抜きます。")
    motion.rest()


def cmd_angles(args):
    pairs = []
    for tok in args.spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        name, _, val = tok.partition("=")
        pairs.append((name.strip(), float(val)))
    if not pairs:
        sys.exit('指定が空です。例: "RShoulderPitch=0.5,RElbowRoll=1.0"')
    session = connect()
    motion = _prepare_motion(session, disable_life=not args.keep_life)
    names = [p[0] for p in pairs]
    angles = [p[1] for p in pairs]
    print(f"setAngles {names} = {angles} (speed={args.speed})")
    motion.setAngles(names, angles, args.speed)


def cmd_rest(args):
    session = connect()
    session.service("ALMotion").rest()
    print("rest 完了。")


def cmd_enable_life(args):
    session = connect()
    session.service("ALAutonomousLife").setState("solitary")
    print("ALAutonomousLife = solitary に戻しました。")


def main():
    p = argparse.ArgumentParser(description="NAOqi 2.9 低レベル関節制御（ALMotion）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("services", help="接続確認＆サービス一覧").set_defaults(func=cmd_services)

    pa = sub.add_parser("arm", help="デモ: 右腕を少し上げる")
    pa.add_argument("--speed", type=float, default=0.2)
    pa.add_argument("--keep-life", action="store_true", help="自律機能を止めない")
    pa.set_defaults(func=cmd_arm)

    pg = sub.add_parser("angles", help='任意関節を setAngles。例 "RShoulderPitch=0.5,RElbowRoll=1.0"')
    pg.add_argument("spec")
    pg.add_argument("--speed", type=float, default=0.2)
    pg.add_argument("--keep-life", action="store_true", help="自律機能を止めない")
    pg.set_defaults(func=cmd_angles)

    sub.add_parser("rest", help="力を抜く(rest)").set_defaults(func=cmd_rest)
    sub.add_parser("enable-life", help="自律機能を solitary に戻す").set_defaults(func=cmd_enable_life)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
