# pepper-practice

SoftBank Pepper を操作する練習用プロジェクト。Pepper のタブレット上で動く **Android アプリ（QiSDK）** と、
PC 側から制御する **Python クライアント** で構成しています。

## 構成
- **`PepperPractice/`** … Android アプリ（Java / QiSDK）。Pepper 胸部タブレット上で動き、TCP サーバ
  （ポート 2003）として待ち受け、受け取った文字列コマンドを QiSDK で実行します
  （`say` / `look` / `snap` / `nod` / `tilt` / `anim`、地図があれば `go` / `rotate`）。
- **`python/`** … PC 側クライアント（2 系統）
  - `pepper.py` … 上記 Android アプリ（TCP ブリッジ）へコマンドを送る高レベル制御。
  - `naoqi_lowlevel.py` … ロボット頭部の NAOqi に libqi で直結し、ALMotion で関節角・基底移動などを直接制御。

## アーキテクチャ
```
PC (python/)
  ├─ pepper.py ───────── TCP:2003 ─────────▶ Pepper タブレット (Android / QiSDK アプリ) ─▶ ロボット動作
  └─ naoqi_lowlevel.py ─ libqi(TLS):9503 ──▶ Pepper 頭部 (NAOqi / ALMotion)
```
PC とロボットは同一 Wi-Fi 上の TCP で通信します。

## 必要環境
- Pepper（QiSDK＝NAOqi 2.9 系、Android タブレット搭載モデル）
- Android Studio（AGP 7.4 / JDK 17 でビルド確認済み）
- Python 3.12（`python/` 用）

## クイックスタート
1. **Android アプリ**: `PepperPractice/` を Android Studio で開いてビルド →
   `adb connect <タブレットIP>` の上、実機へ Run。
2. **Python クライアント**: 詳細は [python/README.md](python/README.md)。
   venv 作成 → `python/.env` に接続先を設定 → 実行。

## 設定・秘匿情報
- Pepper の IP やアカウント等の環境依存値は **`python/.env`（git 管理外）** に置き、コミットしません。
  テンプレートは [python/.env.example](python/.env.example)。

## 実装メモ（知見）
- QiSDK の探索/地図/`GoTo` はロボットの NAOqi バージョンによっては使えないことがあります
  （`go`/`rotate` が動かない個体あり）。
- その場合でも、**低レベル NAOqi（`naoqi_lowlevel.py` / ALMotion）経由なら関節制御・基底移動ができます**
  （本リポジトリの環境で動作確認済み）。

## 関節の可動範囲（この環境での実測値）
`python python/naoqi_lowlevel.py limits` で取得した、本リポジトリの Pepper（NAOqi 2.9.1.122）の各関節の
可動範囲です（角度はラジアン、度は参考換算）。左右で肩ロール/肘ロールの符号が反転する点に注意。

| 関節 | min(rad) | max(rad) | min(deg) | max(deg) | maxVel(rad/s) |
|---|---|---|---|---|---|
| HeadYaw | -2.0857 | 2.0857 | -119.5 | 119.5 | 7.340 |
| HeadPitch | -0.7069 | 0.4451 | -40.5 | 25.5 | 9.228 |
| LShoulderPitch | -2.0857 | 2.0857 | -119.5 | 119.5 | 7.340 |
| LShoulderRoll | 0.0087 | 1.5621 | 0.5 | 89.5 | 9.228 |
| LElbowYaw | -2.0857 | 2.0857 | -119.5 | 119.5 | 7.340 |
| LElbowRoll | -1.5621 | -0.0087 | -89.5 | -0.5 | 9.228 |
| LWristYaw | -1.8239 | 1.8239 | -104.5 | 104.5 | 17.383 |
| LHand | 0.0200 | 0.9800 | 1.1 | 56.1 | 12.560 |
| RShoulderPitch | -2.0857 | 2.0857 | -119.5 | 119.5 | 7.340 |
| RShoulderRoll | -1.5621 | -0.0087 | -89.5 | -0.5 | 9.228 |
| RElbowYaw | -2.0857 | 2.0857 | -119.5 | 119.5 | 7.340 |
| RElbowRoll | 0.0087 | 1.5621 | 0.5 | 89.5 | 9.228 |
| RWristYaw | -1.8239 | 1.8239 | -104.5 | 104.5 | 17.383 |
| RHand | 0.0200 | 0.9800 | 1.1 | 56.1 | 12.560 |
| HipRoll | -0.5149 | 0.5149 | -29.5 | 29.5 | 2.270 |
| HipPitch | -1.0385 | 1.0385 | -59.5 | 59.5 | 2.933 |
| KneePitch | -0.5149 | 0.5149 | -29.5 | 29.5 | 2.933 |

## ライセンス
MIT License（[LICENSE](LICENSE)）。

## 注意
学習・練習用のプロジェクトです。実機を動かす際は周囲の安全を確認してください。
