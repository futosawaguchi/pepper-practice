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
  python python/naoqi_lowlevel.py say "こんにちは"      # 発話（ALTextToSpeech）
  python python/naoqi_lowlevel.py postures            # 利用可能な姿勢名
  python python/naoqi_lowlevel.py posture StandInit   # 姿勢へ遷移
  python python/naoqi_lowlevel.py hand open R         # 右手を開く（close で閉じる）
  python python/naoqi_lowlevel.py limits              # 全関節の可動範囲(rad+deg)をMarkdown表で出力
  python python/naoqi_lowlevel.py limits HeadYaw      # 特定関節だけ
  python python/naoqi_lowlevel.py move 0.2 0 0        # 基底移動 moveTo(x,y,theta)（周囲確認のうえ）
  python python/naoqi_lowlevel.py move 0.2 0 45 --deg # theta を度で指定（既定はラジアン）
  python python/naoqi_lowlevel.py move 2 0 0 --max 2  # 0.5m 超を進む（衝突保護の状態を表示し、実移動量を計測）
  python python/naoqi_lowlevel.py move 1 0 0 --max 1 --speed 0.2  # 最高速度[m/s]を指定（0.1〜0.55）
  python python/naoqi_lowlevel.py rotate 90 --stand   # その場回転（診断つき。--vel/--force も）
  python python/naoqi_lowlevel.py rest                # 力を抜く（rest）
  python python/naoqi_lowlevel.py enable-life         # 自律機能を戻す（solitary）

任意のサービスを使いたい場合は対話 python で:
  from naoqi_lowlevel import connect
  s = connect(); s.service("ALLeds").randomEyes(2.0)

注意: 周囲に人や物が無いことを確認してから動かすこと。速度は控えめ(0.2)。
"""
import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MOVE_HARD_MAX = 3.0  # move の --max で許す x/y の絶対上限[m]
MOVE_SPEED_RANGE = (0.1, 0.55)  # move の --speed（MaxVelXY[m/s]）の範囲。Pepper の既定は 0.35

# 重要: NAOqi（ALMotion）はロボット「頭部」で動く。胸部 Android タブレット（PEPPER_IPS）とは別IP。
#   タブレット = QiSDKアプリ側のIP / ロボット頭部 = ssh nao@<このIP> で入れる方（実値は python/.env に）
# PEPPER_NAOQI_IP を優先。未設定なら PEPPER_IPS[0] にフォールバック（多くの場合これは誤り＝タブレット）。
_tablet_ips = [ip.strip() for ip in os.environ.get("PEPPER_IPS", "127.0.0.1").split(",") if ip.strip()]
IP = os.environ.get("PEPPER_NAOQI_IP", "").strip() or (_tablet_ips[0] if _tablet_ips else "127.0.0.1")
PORT = int(os.environ.get("PEPPER_NAOQI_PORT", "9559"))
USER = os.environ.get("PEPPER_USER", "nao")
PASSWORD = os.environ.get("PEPPER_PASSWORD", "")

# Pepper の標準関節（limits の全関節表示・参考用）
PEPPER_JOINTS = [
    "HeadYaw", "HeadPitch",
    "LShoulderPitch", "LShoulderRoll", "LElbowYaw", "LElbowRoll", "LWristYaw", "LHand",
    "RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll", "RWristYaw", "RHand",
    "HipRoll", "HipPitch", "KneePitch",
]


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


# --- 基底移動/回転の診断ヘルパー（rotate が使う） ---
def _robot_pose(motion):
    """世界座標での現在姿勢 [x, y, theta(rad)]。取得できなければ None。"""
    try:
        p = motion.getRobotPosition(True)
        return [float(p[0]), float(p[1]), float(p[2])]
    except Exception:  # noqa: BLE001
        return None


def _ang_diff(a, b):
    """角度差 a-b を [-pi, pi] に正規化（実回転量の計測用）。"""
    import math
    return math.atan2(math.sin(a - b), math.cos(a - b))


def _get_move_protection(motion):
    """基底の衝突保護/セキュリティ距離の現在値を取得（表示・復元用）。取得失敗は None。"""
    info = {"ext_move": None, "ortho": None, "tang": None}
    try:
        info["ext_move"] = motion.getExternalCollisionProtectionEnabled("Move")
    except Exception:  # noqa: BLE001
        pass
    try:
        info["ortho"] = motion.getOrthogonalSecurityDistance()
        info["tang"] = motion.getTangentialSecurityDistance()
    except Exception:  # noqa: BLE001
        pass
    return info


def _report_protection(motion):
    info = _get_move_protection(motion)
    print(f"基底保護: ExternalCollisionProtection('Move')={info['ext_move']} / "
          f"security(ortho={info['ortho']}, tang={info['tang']})")


def _relax_base_protection(motion):
    """基底の衝突保護とセキュリティ距離を一時的に緩める。元に戻す関数を返す。
    安全機能を下げるので、周囲を空けたうえで使うこと。"""
    prev = _get_move_protection(motion)
    try:
        motion.setExternalCollisionProtectionEnabled("Move", False)
    except Exception as e:  # noqa: BLE001
        print(f"注意: ExternalCollisionProtection('Move') を無効化できませんでした: {e}")
    try:
        motion.setTangentialSecurityDistance(0.05)
        motion.setOrthogonalSecurityDistance(0.10)
    except Exception as e:  # noqa: BLE001
        print(f"注意: security distance を変更できませんでした: {e}")

    def restore():
        try:
            if prev["ext_move"] is not None:
                motion.setExternalCollisionProtectionEnabled("Move", prev["ext_move"])
        except Exception:  # noqa: BLE001
            pass
        try:
            if prev["ortho"] is not None:
                motion.setOrthogonalSecurityDistance(prev["ortho"])
            if prev["tang"] is not None:
                motion.setTangentialSecurityDistance(prev["tang"])
        except Exception:  # noqa: BLE001
            pass

    return restore


def cmd_rotate(args):
    """その場回転。既定は moveTo(0,0,theta)。回らない個体/状況向けに診断と対策つき:
      - robotIsWakeUp / moveInit / moveIsActive を表示し「命令が受理されたか」を切り分け。
      - 回転前後の実 theta を計測し「本当に回ったか」を表示。
      - --stand: 回転前に StandInit（腕を畳む）。腕が広がっていると基底回転が拒否されやすい。
      - 180°超の指定は 170° 以下に分割して実行（moveTo/計測とも ±180° で折り返すため）。
      - --vel  : moveToward(速度指令)で目標角まで閉ループ回転（moveTo が効かない時）。
      - --force: 基底の衝突保護を一時OFF（※Pepperの"Move"は保護リフレックスで無効化不可な場合あり）。
    """
    import math
    theta = args.angle if args.rad else math.radians(args.angle)
    ctheta = max(-2 * math.pi, min(2 * math.pi, theta))   # 安全のため ±360° にクランプ
    if ctheta != theta:
        print(f"安全のためクランプしました -> {math.degrees(ctheta):.1f}°")
        theta = ctheta
    print(f"その場で回転（目標 {math.degrees(theta):+.1f}° / {theta:+.3f} rad、正=左回り）。"
          "周囲に人や物が無いか確認してください。3秒後に開始…")
    time.sleep(3.0)
    session = connect()
    motion = _prepare_motion(session, disable_life=not args.keep_life)
    try:
        print(f"robotIsWakeUp={motion.robotIsWakeUp()}")
    except Exception:  # noqa: BLE001
        pass
    _report_protection(motion)

    if args.stand:
        try:
            print("StandInit へ（腕を畳んで基底回転を許可されやすくする）…")
            session.service("ALRobotPosture").goToPosture("StandInit", 0.5)
        except Exception as e:  # noqa: BLE001
            print(f"注意: goToPosture(StandInit) に失敗: {e}")

    restore = None
    if args.force:
        print(" --force: 基底の衝突保護を一時OFFにします（終了時に自動で戻します）。")
        restore = _relax_base_protection(motion)

    try:
        try:
            motion.moveInit()
            print("moveInit 完了")
        except Exception as e:  # noqa: BLE001
            print(f"注意: moveInit に失敗: {e}")
        p0 = _robot_pose(motion)
        th0 = p0[2] if p0 else None

        # 実測の積算回転量[rad]。_ang_diff は ±180° に正規化されるため、始点と終点だけを比べると
        # 1周(360°)が 0° に見えてしまう。区間ごとに測って足すことで 180° 超でも正しく出す。
        total = 0.0
        measured = False

        if args.vel:
            # 速度指令で目標角まで回す（moveTo が効かない個体向け）。正規化角速度(-1..1)。
            wz = 0.5 if theta >= 0 else -0.5
            print(f"moveToward(0, 0, {wz}) で目標角まで回転…")
            motion.moveToward(0.0, 0.0, wz)
            time.sleep(0.4)
            try:
                print(f"moveIsActive={motion.moveIsActive()}（Falseなら命令が拒否＝安全リフレックス）")
            except Exception:  # noqa: BLE001
                pass
            th_last = th0
            t_start = time.time()
            while time.time() - t_start < 25.0:
                pc = _robot_pose(motion)
                if pc is None or th_last is None:
                    time.sleep(min(25.0, abs(theta) / 0.35))   # 姿勢計測不可→角速度概算で時間停止
                    break
                total += _ang_diff(pc[2], th_last)             # 前回サンプルとの差を積算
                th_last = pc[2]
                measured = True
                if abs(total) >= abs(theta) - math.radians(3):
                    break
                time.sleep(0.05)
            motion.stopMove()
        else:
            # moveTo の theta も ±π に正規化される個体があり、360° 指定が 0° 扱いになりうる。
            # 170° 以下に分割して順に実行し、各区間の実測を積算する。
            step_max = math.radians(170.0)
            n = max(1, int(math.ceil(abs(theta) / step_max)))
            step = theta / n
            if n > 1:
                print(f"目標 {math.degrees(theta):+.1f}° を {n} 回に分割"
                      f"（各 {math.degrees(step):+.1f}°）して実行します。")
            for i in range(n):
                pa = _robot_pose(motion)
                label = f"  [{i + 1}/{n}]" if n > 1 else ""
                print(f"moveTo(0, 0, {step:.3f}){label}")
                motion.moveTo(0.0, 0.0, step)
                pb = _robot_pose(motion)
                if pa and pb:
                    total += _ang_diff(pb[2], pa[2])
                    measured = True

        if measured:
            print(f"実際の回転: {math.degrees(total):+.1f}°（目標 {math.degrees(theta):+.1f}°）")
            if abs(total) < math.radians(5) and abs(theta) > math.radians(10):
                print("ほとんど回っていません。")
        else:
            print("回転指令を送信しました（getRobotPosition 不可のため実回転量は未計測）。")
    finally:
        if restore is not None:
            restore()
            print("基底保護を元に戻しました。")
    print("回転完了。")


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


def cmd_say(args):
    session = connect()
    session.service("ALTextToSpeech").say(args.text)
    print(f"say: {args.text}")


def cmd_postures(args):
    session = connect()
    names = session.service("ALRobotPosture").getPostureList()
    print("利用可能な姿勢:")
    for n in names:
        print("  " + n)


def cmd_posture(args):
    session = connect()
    _prepare_motion(session, disable_life=not args.keep_life)
    print(f"goToPosture({args.name}, {args.speed})")
    ok = session.service("ALRobotPosture").goToPosture(args.name, args.speed)
    print("完了" if ok else "到達できず（姿勢名は postures で確認）")


def cmd_hand(args):
    name = ("R" if args.side.upper().startswith("R") else "L") + "Hand"
    session = connect()
    motion = _prepare_motion(session, disable_life=not args.keep_life)
    if args.action == "open":
        motion.openHand(name)
    else:
        motion.closeHand(name)
    print(f"{args.action} {name}")


def cmd_limits(args):
    import math
    session = connect()
    motion = session.service("ALMotion")
    joints = [args.joint] if (args.joint and args.joint.lower() != "all") else PEPPER_JOINTS
    # getLimits(joint) -> [[minAngle, maxAngle, maxVelocity, maxTorque]]（ラジアン）
    print("| 関節 | min(rad) | max(rad) | min(deg) | max(deg) | maxVel(rad/s) |")
    print("|---|---|---|---|---|---|")
    for j in joints:
        try:
            row = motion.getLimits(j)[0]
            mn, mx, vel = float(row[0]), float(row[1]), float(row[2])
            print(f"| {j} | {mn:.4f} | {mx:.4f} | {math.degrees(mn):.1f} | {math.degrees(mx):.1f} | {vel:.3f} |")
        except Exception as e:  # noqa: BLE001
            print(f"| {j} | 取得失敗: {e} | | | | |")


def cmd_move(args):
    """基底移動 moveTo(x, y, theta)。theta は既定でラジアン（--deg で度指定）。
    rotate と同じく moveTo の前に moveInit() を呼ぶ（省くと指令が黙って無視されることがある）。
    x/y の上限は既定 ±0.5m、--max で最大 MOVE_HARD_MAX まで広げられる。
    --speed で並進の最高速度 MaxVelXY[m/s] を指定（未指定ならロボット既定の 0.35）。
    障害物での停止は衝突保護（ExternalCollisionProtection）頼みなので、実移動量を計測して表示する。
    その場回転だけなら度で書けて診断もある rotate を使うほうがよい。"""
    import math
    lim = max(0.0, min(MOVE_HARD_MAX, args.max))
    if lim != args.max:
        print(f"--max は 0〜{MOVE_HARD_MAX}m に制限されます -> {lim}m")
    raw_theta = math.radians(args.theta) if args.deg else args.theta
    if not args.deg and abs(args.theta) > 2 * math.pi:
        print(f"ヒント: theta={args.theta} はラジアンとして解釈されます"
              f"（度で指定したいなら --deg。その場回転だけなら rotate を推奨）。")
    x = max(-lim, min(lim, args.x))
    y = max(-lim, min(lim, args.y))
    theta = max(-math.pi / 2, min(math.pi / 2, raw_theta))
    if (x, y, theta) != (args.x, args.y, raw_theta):
        print(f"安全のためクランプしました -> x={x}, y={y}, "
              f"theta={theta:.4f} rad ({math.degrees(theta):+.1f}°)")
    config = []
    if args.speed is not None:
        lo, hi = MOVE_SPEED_RANGE
        speed = max(lo, min(hi, args.speed))
        if speed != args.speed:
            print(f"--speed は {lo}〜{hi} m/s に制限されます -> {speed}")
        config.append(["MaxVelXY", speed])
    speed_txt = f"{config[0][1]}m/s" if config else "既定"
    print(f"★ 基底移動します（x={x}m, y={y}m, theta={math.degrees(theta):+.1f}°, "
          f"速度={speed_txt}）。周囲に人や物が無いか確認してください。3秒後に開始…")
    time.sleep(3.0)
    session = connect()
    motion = _prepare_motion(session, disable_life=not args.keep_life)
    _report_protection(motion)
    if _get_move_protection(motion)["ext_move"] is False:
        print("警告: 衝突保護が無効です。障害物があっても止まりません。")
    try:
        motion.moveInit()          # rotate と同じ準備。省くと moveTo が無視されることがある
        print("moveInit 完了")
    except Exception as e:  # noqa: BLE001
        print(f"注意: moveInit に失敗: {e}")
    start = _robot_pose(motion)
    if config:
        print(f"moveTo({x}, {y}, {theta:.4f}, {config})")
        motion.moveTo(x, y, theta, config)
    else:
        print(f"moveTo({x}, {y}, {theta:.4f})")
        motion.moveTo(x, y, theta)
    end = _robot_pose(motion)
    if start and end:
        # moveTo は障害物で途中停止しても例外にならないので、オドメトリで実移動量を確認する
        dist = math.hypot(end[0] - start[0], end[1] - start[1])
        want = math.hypot(x, y)
        print(f"実際の移動: {dist:.2f}m（目標 {want:.2f}m）"
              f"、回転 {math.degrees(_ang_diff(end[2], start[2])):+.1f}°")
        if want > 0 and dist < want - 0.1:
            print("目標より手前で止まりました（障害物検知の可能性）。")
    print("移動完了。")


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

    ps = sub.add_parser("say", help="発話（ALTextToSpeech）")
    ps.add_argument("text")
    ps.set_defaults(func=cmd_say)

    sub.add_parser("postures", help="利用可能な姿勢名を表示").set_defaults(func=cmd_postures)

    pp = sub.add_parser("posture", help='姿勢へ遷移。例 "StandInit"')
    pp.add_argument("name")
    pp.add_argument("--speed", type=float, default=0.5)
    pp.add_argument("--keep-life", action="store_true", help="自律機能を止めない")
    pp.set_defaults(func=cmd_posture)

    ph = sub.add_parser("hand", help="手を開閉。例: hand open R")
    ph.add_argument("action", choices=["open", "close"])
    ph.add_argument("side", choices=["L", "R", "l", "r"])
    ph.add_argument("--keep-life", action="store_true", help="自律機能を止めない")
    ph.set_defaults(func=cmd_hand)

    pl = sub.add_parser("limits", help="可動範囲(rad+deg)。引数なしで全関節をMarkdown表で出力。例: limits HeadYaw")
    pl.add_argument("joint", nargs="?", default=None)
    pl.set_defaults(func=cmd_limits)

    pm = sub.add_parser("move", help="基底移動 moveTo(x,y,theta)。例: move 0.2 0 0 / move 0.2 0 45 --deg")
    pm.add_argument("x", type=float, help="前後[m]。正=前。±--max にクランプ")
    pm.add_argument("y", type=float, help="左右[m]。正=左。±--max にクランプ")
    pm.add_argument("theta", type=float,
                    help="回転。既定はラジアン（--deg で度）。正=左回り。±90° にクランプ")
    pm.add_argument("--deg", action="store_true", help="theta を度として解釈（例: move 0 0 45 --deg）")
    pm.add_argument("--max", type=float, default=0.5,
                    help=f"x/y の上限[m]（既定 0.5、最大 {MOVE_HARD_MAX}）。例: move 2 0 0 --max 2")
    pm.add_argument("--speed", type=float, default=None,
                    help=f"並進の最高速度[m/s]（{MOVE_SPEED_RANGE[0]}〜{MOVE_SPEED_RANGE[1]}、未指定=既定0.35）")
    pm.add_argument("--keep-life", action="store_true", help="自律機能を止めない")
    pm.set_defaults(func=cmd_move)

    pr = sub.add_parser("rotate", help="その場回転（診断つき）。例: rotate 90 --stand")
    pr.add_argument("angle", type=float, help="回転角。既定は度。正=左回り(CCW)、負=右回り")
    pr.add_argument("--rad", action="store_true", help="angle をラジアンとして解釈")
    pr.add_argument("--force", action="store_true",
                    help="基底の衝突保護/security距離を一時OFF（終了時に自動復元）。周囲を空けて")
    pr.add_argument("--vel", action="store_true",
                    help="moveTo で回らない個体向け: moveToward(速度指令)で目標角まで回す")
    pr.add_argument("--stand", action="store_true",
                    help="回転前に StandInit（腕を畳む）。腕が広がっていると基底回転が拒否されやすい")
    pr.add_argument("--keep-life", action="store_true", help="自律機能を止めない")
    pr.set_defaults(func=cmd_rotate)

    sub.add_parser("rest", help="力を抜く(rest)").set_defaults(func=cmd_rest)
    sub.add_parser("enable-life", help="自律機能を solitary に戻す").set_defaults(func=cmd_enable_life)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
