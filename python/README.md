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

## ファイル

| ファイル | 役割 | コミット |
|---|---|---|
| `pepper.py` | クライアント本体（`Pepper_action` / `decode_image`） | する |
| `requirements.txt` | 依存（Pillow, python-dotenv） | する |
| `.env.example` | 接続先テンプレート | する |
| `.env` | 実際の接続先（実IP） | **しない**（gitignore） |
| `mock_pepper.py` | 実機なし検証用モック TCP サーバ | する |
| `selftest_local.py` | 自動ローカルテスト | する |
| `output/` | `snap` の保存先 | **しない**（gitignore） |
