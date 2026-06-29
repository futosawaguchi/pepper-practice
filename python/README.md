# Python クライアント（PC 側）

Pepper 本体上の Android アプリ（`PepperPractice/`、TCP ポート 2003）へ文字列コマンドを送るクライアント。
対応コマンド: `say` / `stop-say` / `go` / `rotate` / `look` / `snap` / `nod` / `tilt` / `anim`。

## セットアップ

リポジトリのルートで実行:

```bash
python3 -m venv venv
source venv/bin/activate          # Windows は venv\Scripts\activate
pip install -r python/requirements.txt
cp python/.env.example python/.env # 実機のIPは後で python/.env に書く
```

`python/.env`（gitignore 済・**コミットされない**）に接続先を書く:

```
PEPPER_IPS=192.168.x.x   # 実機Pepperの実IP（複数台はカンマ区切り）。実機が無い間は 127.0.0.1
PEPPER_PORT=2003
```

> 秘匿ルール: 実 IP は **`python/.env` だけ**に書く。`pepper.py` などソースには直書きしない。

## Pepper 実機なしでのローカル確認

実機が無くても、付属のモックサーバで送受信・画像デコードを検証できる。

```bash
# 自動テスト（おすすめ）: モック起動 → 全コマンド送信 → 画像デコードまで検証
python python/selftest_local.py        # → RESULT: ALL PASS

# 対話的に試す場合: 別ターミナルでモックを起動してから pepper.py を実行
python python/mock_pepper.py           # ターミナルA: 127.0.0.1:2003 で待ち受け
PEPPER_IPS=127.0.0.1 python python/pepper.py   # ターミナルB
```

## 実機が来たら

1. Pepper と PC を同じ Wi-Fi に接続し、Pepper の IP を確認 → `python/.env` に設定。
2. `adb connect <PepperのIP>` → Android Studio から Run でアプリをデプロイ。
3. `python python/pepper.py`（または `Pepper_action` を import して各メソッドを呼ぶ）で動作確認。
   - 移動系（`go` / `rotate`）は地図作成＆ローカライズ済みが前提（`MainActivity.MAP_SETUP_MODE` 参照）。
   - `nod` / `tilt` は `.qianim` 入手後に app 側スタブを戻すと実アニメで動く。

## 低レベル NAOqi 直結（関節を角度で動かす・上級/実験的）

QiSDK アプリ経由では関節角の直接指定ができない。NAOqi 2.9 でも内部の `ALMotion` は生きているので、
`naoqi_lowlevel.py` で Python から直結して腕・首などをラジアン指定で動かせる（**非公式・自己責任**）。

前提: ロボットの **user/password が必要**（2.9 は認証＋TLS 必須）。

> ⚠️ **接続先 IP に注意**: NAOqi（ALMotion）は**ロボット頭部**で動く。`pepper.py` が使う胸部 Android
> タブレットの IP（`PEPPER_IPS`）とは**別物**。`PEPPER_NAOQI_IP` には `ssh nao@<このIP>` で入れる方を書く。

`python/.env` に設定（コミット禁止）:
```
PEPPER_NAOQI_IP=192.168.x.x   # ロボット頭部のIP（タブレットの PEPPER_IPS とは別）
PEPPER_NAOQI_PORT=9559        # 標準。スクリプトは 9559/9503 を試す
PEPPER_USER=nao
PEPPER_PASSWORD=（実パスワード）
```
リモート接続が `disconnected`/`Connection refused` で安定しない場合は、**`ssh nao@<ロボット頭部IP>` で
ロボットに入り、ローカルの `qicli`（例: `qicli call ALMotion.wakeUp`）や python で ALMotion を叩く**方が
確実（ローカル接続は TLS/認証不要なことが多い）。
手順:
```bash
pip install -r python/requirements-naoqi.txt           # qi(libqi-python)
python python/naoqi_lowlevel.py services               # 接続確認＆ALMotionの有無
python python/naoqi_lowlevel.py arm                    # デモ: 右腕を少し上げる
python python/naoqi_lowlevel.py angles "RShoulderPitch=0.5,RElbowRoll=1.0" --speed 0.2
python python/naoqi_lowlevel.py rest                   # 力を抜く
python python/naoqi_lowlevel.py enable-life            # 自律機能を戻す
```
- 接続が `disconnected` 等で失敗する場合は qi のバージョン/スキーム/認証情報を見直す（libqi-python issue #22）。
  ダメなら Docker(linux)+qi か ROS2 `naoqi_driver2` を検討。
- **動かす前に周囲の安全を確認**。速度は控えめ(0.2)推奨。

## ファイル

| ファイル | 役割 | コミット |
|---|---|---|
| `pepper.py` | QiSDKブリッジ用クライアント（`Pepper_action` / `decode_image`） | する |
| `requirements.txt` | TCPブリッジ用依存（Pillow, python-dotenv） | する |
| `naoqi_lowlevel.py` | 低レベル NAOqi 直結（ALMotion で関節制御） | する |
| `requirements-naoqi.txt` | 低レベル用依存（qi/libqi-python） | する |
| `.env.example` | 接続先テンプレート | する |
| `.env` | 実際の接続先（実IP・**実パスワード**） | **しない**（gitignore） |
| `mock_pepper.py` | 実機なし検証用モック TCP サーバ | する |
| `selftest_local.py` | 自動ローカルテスト | する |
| `output/` | `snap` の保存先 | **しない**（gitignore） |
