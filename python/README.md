# Python クライアント（PC 側）

PC から Pepper を制御する 2 系統のクライアント。
- **`pepper.py`** … Pepper タブレット上の Android アプリ（`PepperPractice/`、TCP 2003）へ文字列コマンド送信。
  対応: `say` / `stop-say` / `go` / `rotate` / `look` / `snap` / `nod` / `tilt` / `anim`。
- **`naoqi_lowlevel.py`** … ロボット頭部 NAOqi に直結し、ALMotion で関節角・基底移動などを直接制御。

## セットアップ
リポジトリのルートで:
```bash
python3 -m venv venv
source venv/bin/activate            # Windows は venv\Scripts\activate
pip install -r python/requirements.txt
cp python/.env.example python/.env  # 接続先は python/.env に書く（コミットされない）
```
`python/.env`（git 管理外）に接続先を設定:
```
PEPPER_IPS=192.168.x.x   # Pepper タブレットのIP（複数台はカンマ区切り）。実機が無い間は 127.0.0.1
PEPPER_PORT=2003
```
> 秘匿ルール: 実 IP / パスワードは **`python/.env` だけ** に書く。ソースには直書きしない。

## Pepper 実機なしでのローカル確認
付属のモックサーバで送受信・画像デコードを検証できる:
```bash
python python/selftest_local.py     # 自動テスト（RESULT: ALL PASS）
# 対話的に:
python python/mock_pepper.py        # ターミナルA（127.0.0.1:2003 で待受）
PEPPER_IPS=127.0.0.1 python python/pepper.py   # ターミナルB
```

## 実機（QiSDK アプリ経由）
1. Pepper と PC を同一 Wi-Fi に。タブレットの IP を `python/.env` に設定。
2. `adb connect <タブレットIP>` → Android Studio から Run でアプリをデプロイ。
3. `python python/pepper.py`、または `Pepper_action` を import して各メソッドを呼ぶ。
   - `go`/`rotate` は地図作成＆ローカライズ済みが前提（`MainActivity.MAP_SETUP_MODE`）。NAOqi 版により不可な個体あり。
   - `nod`/`tilt` は `.qianim` を `res/raw/` に置くと実アニメで動く（未所持時はスタブ）。

## 低レベル NAOqi 直結（ALMotion で関節を角度制御）
QiSDK では関節角の直接指定ができないが、NAOqi 2.9 でも内部の `ALMotion` は使えるため、`naoqi_lowlevel.py`
で Python から直結して腕・首・基底移動などを制御できる（本リポジトリの環境で動作確認済み）。

> ⚠️ **接続先 IP に注意**: NAOqi（ALMotion）は**ロボット頭部**で動く。`pepper.py` が使う胸部タブレットの IP
> （`PEPPER_IPS`）とは**別物**。`PEPPER_NAOQI_IP` には `ssh nao@<このIP>` で入れる方を書く。

前提: ロボットの user/password（2.9 は認証＋TLS 必須）。`python/.env` に:
```
PEPPER_NAOQI_IP=192.168.x.x   # ロボット頭部のIP（タブレットの PEPPER_IPS とは別）
PEPPER_NAOQI_PORT=9559        # 標準。スクリプトは 9559/9503 を順に試す
PEPPER_USER=nao
PEPPER_PASSWORD=（実パスワード）
```
手順:
```bash
pip install -r python/requirements-naoqi.txt   # qi(libqi-python)
python python/naoqi_lowlevel.py services        # 接続確認＆ALMotionの有無
python python/naoqi_lowlevel.py say "こんにちは"  # 発話
python python/naoqi_lowlevel.py limits          # 全関節の可動範囲(rad+deg)
python python/naoqi_lowlevel.py angles "RShoulderPitch=0.5,RElbowRoll=1.0" --speed 0.2
python python/naoqi_lowlevel.py arm             # デモ: 右腕を上げる
python python/naoqi_lowlevel.py posture StandInit   # 姿勢（postures で一覧）
python python/naoqi_lowlevel.py hand open R     # 右手を開く
python python/naoqi_lowlevel.py move 0.2 0 0    # 基底移動（周囲確認のうえ）
python python/naoqi_lowlevel.py move 1 0 0 --max 1 --speed 0.2   # 0.5m 超・速度指定つき
python python/naoqi_lowlevel.py rest            # 力を抜く
python python/naoqi_lowlevel.py enable-life     # 自律機能を戻す
```
Pepper の関節名（`angles`/`limits` で使用）: `HeadYaw` `HeadPitch` / 各腕 `?ShoulderPitch` `?ShoulderRoll`
`?ElbowYaw` `?ElbowRoll` `?WristYaw` `?Hand`（?=L/R） / `HipRoll` `HipPitch` `KneePitch`。安全範囲は `limits` で確認。

### 基底移動（`move`）の距離と速度
`move x y theta` の x/y はメートル（正=前/左）、theta は既定でラジアン（`--deg` で度、正=左回り）。
いずれも**現在位置・向きからの相対値**。

| オプション | 意味 | 既定 | 範囲 |
|---|---|---|---|
| `--max` | x/y の上限[m]。超えた値はクランプ | 0.5 | 0〜3.0 |
| `--speed` | 並進の最高速度 `MaxVelXY`[m/s] | 未指定（ロボット既定 0.35） | 0.1〜0.55 |

`--speed` の目安（参考: 人の通常歩行は 1.1〜1.4 m/s ≒ 時速 4〜5 km）:

| 値[m/s] | 時速 | 2m 進む時間の目安 | 感覚 |
|---|---|---|---|
| 0.1（最小） | 約 0.36 km/h | 約 20 秒 | じわじわ。様子見に |
| 0.2 | 約 0.72 km/h | 約 10 秒 | ゆっくり。初回の試走におすすめ |
| 0.35（既定） | 約 1.3 km/h | 約 6 秒 | 普段の Pepper |
| 0.55（最大） | 約 2.0 km/h | 約 4 秒 | 速め。止まるまでの距離も伸びる |

- 時間は加減速を除いた目安。加速度の既定は 0.3 m/s² で、0.55 m/s に達するまで約 1.8 秒・約 0.5m かかる
  （短い距離では最高速度まで届かない）。
- 衝突保護（ExternalCollisionProtection）が有効なら、障害物に近づくと速度設定に関係なく減速・停止する。
  ただしガラス・細い脚・黒く低い物などは見逃すことがあるので過信しない。`move` は実行前に保護状態を、
  実行後に実際の移動量を表示する（手前で止まったら「障害物検知の可能性」と出る）。
- 範囲・既定値は NAOqi ドキュメント記載の Pepper 向けの値。実機での挙動は要確認。

- 接続が `disconnected`/`Connection refused` で安定しない場合は qi のバージョン/スキーム/認証を見直す
  （libqi-python の 2.9 接続には既知の不安定さあり）。最終手段は `ssh nao@<頭部IP>` でロボットに入り、
  ローカルの `qicli`（例 `qicli call ALMotion.wakeUp`）/python で叩く（ローカルは TLS/認証不要なことが多い）。
- **動かす前に周囲の安全を確認**。速度は控えめ(0.2)から。

## ファイル
| ファイル | 役割 | コミット |
|---|---|---|
| `pepper.py` | QiSDK ブリッジ用クライアント（`Pepper_action`/`decode_image`） | する |
| `requirements.txt` | ブリッジ用依存（Pillow, python-dotenv） | する |
| `naoqi_lowlevel.py` | 低レベル NAOqi 直結（ALMotion 制御） | する |
| `requirements-naoqi.txt` | 低レベル用依存（qi/libqi-python） | する |
| `mock_pepper.py` / `selftest_local.py` | 実機なし検証用モック＆自動テスト | する |
| `.env.example` | 接続先テンプレート | する |
| `.env` / `output/` | 実値（IP/パスワード）/ snap 保存先 | **しない**（gitignore） |
