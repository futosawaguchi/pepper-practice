package com.example.pepperpractice;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import com.aldebaran.qi.Future;
import com.aldebaran.qi.sdk.QiContext;
import com.aldebaran.qi.sdk.QiSDK;
import com.aldebaran.qi.sdk.RobotLifecycleCallbacks;
import com.aldebaran.qi.sdk.builder.GoToBuilder;
import com.aldebaran.qi.sdk.builder.LocalizeAndMapBuilder;
import com.aldebaran.qi.sdk.builder.LocalizeBuilder;
import com.aldebaran.qi.sdk.builder.LookAtBuilder;
import com.aldebaran.qi.sdk.builder.SayBuilder;
import com.aldebaran.qi.sdk.builder.TransformBuilder;
import com.aldebaran.qi.sdk.design.activity.RobotActivity;
import com.aldebaran.qi.sdk.object.actuation.Actuation;
import com.aldebaran.qi.sdk.object.actuation.ExplorationMap;
import com.aldebaran.qi.sdk.builder.ExplorationMapBuilder;
import com.aldebaran.qi.sdk.object.actuation.FreeFrame;
import com.aldebaran.qi.sdk.object.actuation.Frame;
import com.aldebaran.qi.sdk.object.actuation.GoTo;
import com.aldebaran.qi.sdk.object.actuation.Localize;
import com.aldebaran.qi.sdk.object.actuation.LocalizeAndMap;
import com.aldebaran.qi.sdk.object.actuation.LocalizationStatus;
import com.aldebaran.qi.sdk.object.actuation.LookAt;
import com.aldebaran.qi.sdk.object.actuation.LookAtMovementPolicy;
import com.aldebaran.qi.sdk.object.actuation.Mapping;
import com.aldebaran.qi.sdk.object.conversation.Say;
import com.aldebaran.qi.sdk.object.geometry.Transform;
import com.aldebaran.qi.sdk.object.geometry.Vector3;
import com.aldebaran.qi.sdk.object.geometry.Quaternion;
import com.aldebaran.qi.sdk.object.actuation.OrientationPolicy;
import com.aldebaran.qi.sdk.object.geometry.TransformTime;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import com.aldebaran.qi.AnyObject;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import com.aldebaran.qi.sdk.builder.TakePictureBuilder;
import com.aldebaran.qi.sdk.object.camera.Camera;
import com.aldebaran.qi.sdk.object.image.TimestampedImageHandle;
import com.aldebaran.qi.sdk.object.image.EncodedImageHandle;
import com.aldebaran.qi.sdk.object.image.EncodedImage;
import android.util.Base64;
import java.nio.ByteBuffer;
import com.aldebaran.qi.sdk.object.actuation.Animation;
import com.aldebaran.qi.sdk.object.actuation.Animate;
import com.aldebaran.qi.sdk.builder.AnimationBuilder;
import com.aldebaran.qi.sdk.builder.AnimateBuilder;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkRequest;
import android.net.NetworkCapabilities;
import android.content.Context;

//地図作成時にMAP_SETUP_MODEをtrueにしてビルド
//実際に動かすときにはfalseで実行
//app/main/src/robotsdk.xmlを追加
public class MainActivity extends RobotActivity implements RobotLifecycleCallbacks {
    // ====== 設定 ======
    private static final int PORT = 2003;
    // 初回は true で地図作成→保存。本番運用は false（地図読込→Localize→GoTo）。
    private static final boolean MAP_SETUP_MODE = false;
    // 地図保存ファイル
    private static final String MAP_FILE = "pepper_map.txt";
    // ====== 状態 ======
    private volatile boolean isLocalized = false;
    private GoTo goTo;
    private LookAt lookAt;
    private Future<Void> lookAtFuture;
    // クラス内フィールド
    private Future<com.aldebaran.qi.sdk.object.camera.TakePicture> takePictureFuture;
    private AnyObject leds;
    private ConnectivityManager connectivityManager;
    private ConnectivityManager.NetworkCallback networkCallback;
    // QiContext を外でも使いたい場合用
    private QiContext currentQiContext;

    // ====== ライフサイクル ======
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        QiSDK.register(this, this);
        connectivityManager =
                (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
    }

    @Override
    protected void onDestroy() {
        // ネットワークコールバック解除（登録していれば）
        if (connectivityManager != null && networkCallback != null) {
            try {
                connectivityManager.unregisterNetworkCallback(networkCallback);
            } catch (Exception ignored) {}
            networkCallback = null;
        }
        // QiSDK の登録解除
        QiSDK.unregister(this, this);
        // 発話スレッドの後始末
        stopSpeaking();
        speechExec.shutdownNow();
        super.onDestroy();
    }

    private final ExecutorService speechExec =
            Executors.newSingleThreadExecutor(r -> {
                Thread t = new Thread(r, "SpeechExec");
                t.setDaemon(true);
                return t;
            });

    // 追加: 現在のSayのFuture（必要なら中断に使う）
    private volatile com.aldebaran.qi.Future<Void> currentSayFuture;

    // 追加: 発話API（タグ付きテキストもそのまま渡せます）
    private void speak(QiContext ctx, String text) {
        speechExec.submit(() -> {
            try {
                Say say = SayBuilder.with(ctx).withText(text).build();
                // run() はブロック。Executor上なのでUIは塞ぎません
                say.run();
            } catch (Throwable t) {
                Log.e("Speech", "say failed", t);
            }
        });
    }

    // 追加（任意）：今しゃべっているものを中断したいとき用
    private void stopSpeaking() {
        com.aldebaran.qi.Future<Void> f = currentSayFuture;
        if (f != null && !f.isDone()) {
            Log.i("Speech", "stopSpeaking: requestCancellation()");
            try {
                f.requestCancellation();
            } catch (Throwable e) {
                Log.e("Speech", "stopSpeaking: cancel failed", e);
            }
        } else {
            Log.i("Speech", "stopSpeaking: no currentSayFuture (null or already done)");
        }
    }

    // すべての発話はこの Executor 経由（既に宣言済みの speechExec を使用）
    private void enqueueSpeech(QiContext ctx, String text) {
        speechExec.submit(() -> {
            try {
                Say say = SayBuilder.with(ctx).withText(text).build();
                say.run(); // 完了までブロック（ここが並列にならない肝）
            } catch (Throwable t) {
                Log.e("Speech", "say failed", t);
            }
        });
    }

    // TCPコマンド "say:" 用：発話が終わってから応答を返す
    // ★ 差し替え版 speakAndRespond
    // TCPコマンド "say:" 用：発話が終わってから応答を返す
    private void speakAndRespond(QiContext ctx, String text, PrintWriter writer, boolean wait) {
        try {
            Say say = SayBuilder.with(ctx).withText(text).build();
            com.aldebaran.qi.Future<Void> f = say.async().run();
            currentSayFuture = f;
            Log.i("Speech", "speakAndRespond: future started " + f);
            // wait=false のときは「発話開始時」に ACK
            if (!wait) {
                writer.println("Finished speaking");
            }
            // 終了待ちは別スレッド
            speechExec.submit(() -> {
                boolean cancelled = false;
                try {
                    f.get();   // 正常終了 or キャンセルまで待つ
                } catch (java.util.concurrent.CancellationException e) {
                    cancelled = true;
                    Log.i("Speech", "speakAndRespond: cancelled(ex)", e);
                } catch (Throwable t) {
                    Log.e("Speech", "speakAndRespond: say failed", t);
                    // 失敗の場合も一応通知したいならここで返す
                    if (wait) {
                        writer.println("say-failed: " + t.getMessage());
                    }
                    return;  // finally にだけ行く
                } finally {
                    if (currentSayFuture == f) {
                        currentSayFuture = null;
                    }
                }
                // ★ ここで必ず 1 行返す
                if (wait) {
                    if (cancelled) {
                        writer.println("say-cancelled");   // ← キャンセル終了時のACK
                    } else {
                        writer.println("Finished speaking"); // ← 通常終了時のACK
                    }
                }
            });
        } catch (Throwable e) {
            Log.e("Speech", "speakAndRespond: build/run failed", e);
            writer.println("say-failed: " + e.getMessage());
        }
    }

    private void startNetworkMonitor(QiContext qiContext) {
        if (connectivityManager == null) return;
        // すでに登録済みなら二重登録しない
        if (networkCallback != null) return;
        NetworkRequest request = new NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)  // Wi-Fi を監視
                .build();
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override
            public void onAvailable(Network network) {
                Log.i("Net", "Wi-Fi available");
                // ネットが戻ってきたタイミングで一言
                enqueueSpeech(qiContext, "Wi-Fi に接続しました。");
            }
            @Override
            public void onLost(Network network) {
                Log.w("Net", "Wi-Fi lost");
                // Wi-Fi が切れたタイミングで一言
                enqueueSpeech(qiContext, "Wi-Fi の接続が切れたかもしれません。");
            }
        };
        connectivityManager.registerNetworkCallback(request, networkCallback);
    }

    @Override
    public void onRobotFocusGained(QiContext qiContext) {
        currentQiContext = qiContext;
        speak(qiContext, "準備完了");
        new Thread(() -> runServerLoop(qiContext), "TCP-Server").start();
        if (MAP_SETUP_MODE) {
            createAndSaveMap(qiContext, () -> Log.i("Flow","setup finished"));
        } else {
            loadMapAndLocalize(qiContext, () -> Log.i("Flow","localize started"));
        }
        takePictureFuture = TakePictureBuilder.with(qiContext).buildAsync();
        startNetworkMonitor(qiContext);
    }

    @Override
    public void onRobotFocusLost() {
        if (goTo != null) goTo.removeAllOnStartedListeners();
        if (lookAt != null) lookAt.removeAllOnStartedListeners();
        // ネットワークコールバック解除
        if (connectivityManager != null && networkCallback != null) {
            try {
                connectivityManager.unregisterNetworkCallback(networkCallback);
            } catch (Exception ignored) {}
            networkCallback = null;
        }
        currentQiContext = null;
    }

    @Override
    public void onRobotFocusRefused(String reason) {
        Log.e("Focus", "refused: " + reason);
    }

    // ====== Map I/O（文字列シリアライズの簡易版） ======
    private void saveMapString(String s) {
        try (java.io.FileWriter fw = new java.io.FileWriter(new java.io.File(getFilesDir(), MAP_FILE))) {
            fw.write(s);
            Log.i("MapIO", "map saved: " + new java.io.File(getFilesDir(), MAP_FILE).getAbsolutePath());
        } catch (Exception e) {
            Log.e("MapIO", "save failed", e);
        }
    }

    private String loadMapString() {
        java.io.File f = new java.io.File(getFilesDir(), MAP_FILE);
        if (!f.exists()) return null;
        try (java.io.BufferedReader br = new java.io.BufferedReader(new java.io.FileReader(f))) {
            StringBuilder sb = new StringBuilder();
            String line; while ((line = br.readLine()) != null) sb.append(line).append('\n');
            return sb.toString();
        } catch (Exception e) {
            Log.e("MapIO", "load failed", e);
            return null;
        }
    }

    // ====== 初回：地図作成→保存 ======
    private Future<Void> lamFuture;
    private void createAndSaveMap(final QiContext qiContext, final Runnable onDone) {
        try {
            final LocalizeAndMap lam = LocalizeAndMapBuilder.with(qiContext).build();
            lam.addOnStatusChangedListener(new LocalizeAndMap.OnStatusChangedListener() {
                @Override public void onStatusChanged(LocalizationStatus status) {
                    Log.i("LocalizeAndMap", "status=" + status);
                    if (status == LocalizationStatus.LOCALIZED) {
                        // ★ dumpMap は UI スレッド以外で
                        new Thread(new Runnable() {
                            @Override public void run() {
                                try {
                                    ExplorationMap map = lam.dumpMap();
                                    String mapStr = map.serialize();
                                    saveMapString(mapStr);
                                    Log.i("LocalizeAndMap", "map dumped & saved");
                                } catch (Throwable t) {
                                    Log.e("LocalizeAndMap", "dump/save failed", t);
                                } finally {
                                    if (lamFuture != null) lamFuture.requestCancellation();
                                    if (onDone != null) onDone.run();
                                }
                            }
                        }, "DumpMapThread").start();
                    }
                }
            });
            lamFuture = lam.async().run();
            // 走り出しに失敗したら thenConsume で検知
            lamFuture.thenConsume(f -> {
                if (f.hasError()) {
                    Log.e("LocalizeAndMap", "run error", f.getError());
                    if (onDone != null) onDone.run();
                }
            });
        } catch (Throwable e) {
            Log.e("LocalizeAndMap", "createAndSaveMap failed", e);
            if (onDone != null) onDone.run();
        }
    }

    // ====== 本番：地図読込→Localize開始 ======
    // フィールドに追加
    private Future<Void> localizeFuture;
    private volatile LocalizationStatus lastLocStatus = LocalizationStatus.NOT_STARTED;
    private void loadMapAndLocalize(final QiContext qiContext, final Runnable onReadyOrFail) {
        try {
            final String mapStr = loadMapString();
            if (mapStr == null) {
                Log.e("Localize", "no map file (run setup first)");
                if (onReadyOrFail != null) onReadyOrFail.run();
                return;
            }
            // ★ Builderを使わない復元（古いQiSDKでも可）
            final ExplorationMap map = qiContext.getMapping().makeMap(mapStr);
            final Localize localize = LocalizeBuilder.with(qiContext).withMap(map).build();
            localize.addOnStatusChangedListener(new Localize.OnStatusChangedListener() {
                @Override public void onStatusChanged(LocalizationStatus st) {
                    Log.i("Localize", "status=" + st);
                    // 変化があったときだけ発話（最小実装）
                    if (st != lastLocStatus) {
                        if (st == LocalizationStatus.SCANNING) {
                            enqueueSpeech(qiContext, "環境スキャンを開始します");
                        } else if (lastLocStatus == LocalizationStatus.SCANNING && st != LocalizationStatus.SCANNING) {
                            // SCANNING を抜けた瞬間（LOCALIZED など）
                            enqueueSpeech(qiContext, "スキャン完了");
                        }
                        // おまけ：確定／ロスト時も一言（不要なら消してOK）
                        if (st == LocalizationStatus.LOCALIZED) {
                            enqueueSpeech(qiContext, "位置を特定しました。");
                        }
                    }
                    lastLocStatus = st;                         // 次回比較用
                    isLocalized = (st == LocalizationStatus.LOCALIZED); // 既存のフラグ更新
                }
            });
            localizeFuture = localize.async().run();  // UI外でOK
            if (onReadyOrFail != null) onReadyOrFail.run();
        } catch (Throwable e) {
            Log.e("Localize", "loadMapAndLocalize failed", e);
            if (onReadyOrFail != null) onReadyOrFail.run();
        }
    }

    // その場回転（相対・度数）。正=左回り（反時計）
    private void rotate(QiContext qiContext, double deg, PrintWriter writer) {
        if (!isLocalized) { writer.println("goto-failed: not-localized"); return; }
        // 競合回避：既存のLookAtを止める
        if (lookAtFuture != null && !lookAtFuture.isDone()) lookAtFuture.requestCancellation();
        try {
            Actuation act = qiContext.getActuation();
            Mapping map = qiContext.getMapping();
            Frame robot = act.robotFrame();
            // 目標角（地図座標）
            TransformTime tt0 = map.mapFrame().computeTransform(robot);
            double yaw0   = yawFromQuaternion(tt0.getTransform().getRotation());
            double yawDst = normAngle(yaw0 + Math.toRadians(deg));
            // ロボット基準で yawDelta 方向の点を注視 → ベース回転を発生
            double yawDelta = Math.toRadians(deg);
            double x = Math.cos(yawDelta), y = Math.sin(yawDelta), z = 1.0;
            FreeFrame tgt = map.makeFreeFrame();
            tgt.update(robot, TransformBuilder.create().fromTranslation(new Vector3(x, y, z)), 0L);
            lookAt = LookAtBuilder.with(qiContext).withFrame(tgt.frame()).build();
            lookAt.setPolicy(LookAtMovementPolicy.HEAD_AND_BASE);
            lookAtFuture = lookAt.async().run();
            // 角度がしきい値内に入ったら完了
            new Thread(() -> {
                final long TIMEOUT_MS = 8000;             // 最大8秒
                final double THRESH = Math.toRadians(5.0); // 許容5°
                long start = System.currentTimeMillis();
                boolean ok = false;
                try {
                    while (System.currentTimeMillis() - start < TIMEOUT_MS) {
                        TransformTime tt = map.mapFrame().computeTransform(act.robotFrame());
                        double yawNow = yawFromQuaternion(tt.getTransform().getRotation());
                        double diff   = normAngle(yawDst - yawNow);
                        if (Math.abs(diff) <= THRESH) { ok = true; break; }
                        try { Thread.sleep(100); } catch (InterruptedException ignored) {}
                    }
                } catch (Exception e) {
                    Log.e("Rotate", "monitor error", e);
                } finally {
                    if (lookAtFuture != null && !lookAtFuture.isDone()) lookAtFuture.requestCancellation();
                    if (ok) { Log.i("Rotate", "finished (" + deg + " deg)"); writer.println("finished"); }
                    else    { Log.e("Rotate", "timeout"); writer.println("goto-failed: rotate-timeout"); }
                }
            }, "RotateMonitor").start();
        } catch (Throwable e) {
            Log.e("Rotate", "exception", e);
            writer.println("goto-failed: " + e.getMessage());
        }
    }

    // Z軸回りのヨー角 [-pi, pi)
    private static double yawFromQuaternion(Quaternion q) {
        double siny_cosp = 2.0 * (q.getW()*q.getZ() + q.getX()*q.getY());
        double cosy_cosp = 1.0 - 2.0 * (q.getY()*q.getY() + q.getZ()*q.getZ());
        return Math.atan2(siny_cosp, cosy_cosp);
    }

    private static double normAngle(double a) {
        while (a >  Math.PI) a -= 2.0*Math.PI;
        while (a <= -Math.PI) a += 2.0*Math.PI;
        return a;
    }

    // 追加：モーションは全部ここに流す（LookAt/GoTo/Animate/rotate/nod/tilt）
    private final ExecutorService motionExec =
            Executors.newSingleThreadExecutor(r -> {
                Thread t = new Thread(r, "MotionExec");
                t.setDaemon(true);
                return t;
            });

    // 追加：今動いてるアクションFutureを保持してキャンセルできるようにする
    private volatile Future<Void> currentAnimateFuture;
    private volatile Future<Void> currentGoToFuture;
    private volatile Future<Void> currentLookAtFuture;

    private void cancelActuationAll() {
        try {
            Future<Void> f;
            f = currentAnimateFuture;
            if (f != null && !f.isDone()) f.requestCancellation();
            f = currentGoToFuture;
            if (f != null && !f.isDone()) f.requestCancellation();
            f = currentLookAtFuture;
            if (f != null && !f.isDone()) f.requestCancellation();
            // 既存の lookAtFuture も使ってるなら合わせて止める
            if (lookAtFuture != null && !lookAtFuture.isDone()) lookAtFuture.requestCancellation();
        } catch (Throwable ignored) {}
    }

    private void playQianimByName(QiContext qiContext, String rawName, PrintWriter writer) {
        if (lookAtFuture != null && !lookAtFuture.isDone()) lookAtFuture.requestCancellation();
        if (rawName == null) { writer.println("gesture-failed: empty"); return; }
        String name = rawName.trim().toLowerCase(Locale.US);
        int resId = getResources().getIdentifier(name, "raw", getPackageName());
        if (resId == 0) { writer.println("gesture-no-such:" + name); return; }
        writer.println("gesture-ok:" + name);
        motionExec.submit(() -> {
            try {
                cancelActuationAll();
                Animation anim = AnimationBuilder.with(qiContext).withResources(resId).build();
                Animate animate = AnimateBuilder.with(qiContext).withAnimation(anim).build();
                Future<Void> f = animate.async().run();
                currentAnimateFuture = f;
                f.get();
            } catch (Throwable t) {
                Log.e("Gesture", "playQianim failed: " + name, t);
            } finally {
                currentAnimateFuture = null;
            }
        });
    }

    private void takePictureAndSend(QiContext qiContext, PrintWriter writer) {
        if (takePictureFuture == null) {
            writer.println("snap-failed: takePicture not ready");
            return;
        }
        // TakePicture アクションを実行 → 画像ハンドル取得
        takePictureFuture
                .andThenCompose(takePicture -> {
                    Log.i("Camera", "take picture launched");
                    return takePicture.async().run();
                })
                .andThenConsume(timestampedImageHandle -> {
                    try {
                        // TimestampedImageHandle -> EncodedImage
                        EncodedImageHandle encodedHandle = timestampedImageHandle.getImage();
                        EncodedImage encoded = encodedHandle.getValue();
                        ByteBuffer buffer = encoded.getData();
                        buffer.rewind();
                        byte[] bytes = new byte[buffer.remaining()];
                        buffer.get(bytes);
                        // Base64 にエンコードして送る（クライアント側でデコードして JPEG として保存/表示）
                        String b64 = Base64.encodeToString(bytes, Base64.NO_WRAP);
                        writer.println("image-jpeg-base64:" + b64);
                        Log.i("Camera", "picture size=" + bytes.length + " bytes");
                    } catch (Throwable t) {
                        Log.e("Camera", "takePicture failed", t);
                        writer.println("snap-failed: " + t.getMessage());
                    }
                });
    }

    // ====== 頭のジェスチャ ======
    // うなずき（はい）
    // 「はい？」的な頷き（HEAD_ONLY）。他の lookAt とは独立に動かす。
    // うなずき（yes）のアニメーション
    // TODO(.qianim未所持): R.raw.nice_reaction を参照するため一時無効化。
    //   res/raw/ に .qianim を配置後、元の AnimationBuilder/AnimateBuilder 実装に戻す。
    private void doNod(QiContext qiContext) {
        Log.w("Gesture", "doNod skipped: nice_reaction.qianim not available yet");
    }

    // 首をかしげる（「ん？」な感じ）。dir = "left" or "right"
    // TODO(.qianim未所持): R.raw.sad_reaction を参照するため一時無効化。入手後に元実装へ戻す。
    private void doTilt(QiContext qiContext) {
        Log.w("Gesture", "doTilt skipped: sad_reaction.qianim not available yet");
    }

    private static boolean isInt(String s) { return s != null && s.matches("^-?\\d+$"); }
    private static int clampInt(int v, int lo, int hi) { return (v < lo) ? lo : (v > hi ? hi : v); }

    // ====== TCPサーバ（別スレッド） ======
    private void runServerLoop(QiContext qiContext) {
        try (ServerSocket server = new ServerSocket(PORT)) {
            while (true) {
                // ★ ここですぐ新しい接続を受け取る
                Socket sc = server.accept();
                // ★ 接続ごとにスレッドを分ける
                new Thread(() -> handleClient(qiContext, sc),
                        "TCP-Client-" + sc.getInetAddress().getHostAddress())
                        .start();
            }
        } catch (IOException e) {
            Log.e("TCP", "server fatal", e);
        }
    }

    private void handleClient(QiContext qiContext, Socket sc) {
        try (Socket socket = sc;
             BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream()));
             PrintWriter writer = new PrintWriter(socket.getOutputStream(), true)) {
            Log.d("TCP", "connected");
            String line;
            while ((line = reader.readLine()) != null) {
                // ★ここに今までの if (line.startsWith("say:")) { ... }
                //    stop-say / go / rotate / nod / tilt ... の分岐を
                //    そのまま移植するイメージ
                if (line.startsWith("say:")) {
                    // "say:<vct>:<rspd>:<message>" または "say:<message>"
                    String rest = line.substring(4).trim();
                    int vct = 50;   // デフォルト
                    int rspd = 50;  // デフォルト
                    String msg;
                    String[] p = rest.split(":", 3); // 最大3パートに限定
                    if (p.length == 3 && isInt(p[0]) && isInt(p[1])) {
                        // 数値2個 + メッセージ の形式
                        vct  = clampInt(Integer.parseInt(p[0].trim()), 0, 100);   // 推奨: 0..100
                        rspd = clampInt(Integer.parseInt(p[1].trim()), 50, 200);  // 推奨: 50..200
                        msg  = p[2];
                    } else {
                        // 従来形式: 全部メッセージ
                        msg = rest;
                    }
                    String tagged = "\\vct=" + vct + "\\ \\rspd=" + rspd + "\\ " + msg + " \\rst\\";
                    Boolean wait = Boolean.TRUE; //ここでackを送るタイミングを制御，falseなら発話開始時にack送信
                    speakAndRespond(qiContext, tagged, writer, wait);
                    Log.i("Speech", "start listening");
                    continue;
                }
                // ★ ここに追加（場所は say: のすぐ後くらいがわかりやすい）
                if (line.equals("stop-say")) {
                    stopSpeaking();
                    writer.println("say-stopping");  // コマンド自体のACK
                    continue;
                }
                if (line.startsWith("go:") || line.startsWith("goto:")) {
                    if (!isLocalized) { writer.println("goto-failed: not-localized"); continue; }
                    if (lookAtFuture != null && !lookAtFuture.isDone()) lookAtFuture.requestCancellation();
                    try {
                        int colon = line.indexOf(':');
                        String payload = (colon >= 0) ? line.substring(colon + 1).trim() : "";
                        // ★ 数値だけ（±?digits[.digits]）以外は即座に無視（移動しない）
                        if (!payload.matches("^-?\\d+(\\.\\d+)?$")) {
                            writer.println("goto-ignored: use plain meters like '0.3' or '-0.2'");
                            continue;
                        }
                        double meters = Double.parseDouble(payload);
                        // 安全クランプ（±1.0 m）
                        final double MAX = 1.0;
                        if (meters >  MAX) meters =  MAX;
                        if (meters < -MAX) meters = -MAX;
                        Actuation act = qiContext.getActuation();
                        Mapping map = qiContext.getMapping();
                        Frame robot = act.robotFrame();
                        FreeFrame target = map.makeFreeFrame();
                        Transform t = TransformBuilder.create()
                                .fromTranslation(new Vector3(meters, 0.0, 0.0));
                        target.update(robot, t, 0L);
                        GoTo g = GoToBuilder.with(qiContext).withFrame(target.frame()).build();
                        g.async().run().thenConsume(f -> {
                            if (f.isSuccess()) { Log.i("GoTo", "finished (" + payload + " m)"); writer.println("finished"); }
                            else { Log.e("GoTo", "failed", f.getError()); writer.println("goto-failed: " + String.valueOf(f.getError())); }
                        });
                    } catch (Throwable e) {
                        Log.e("GoTo", "exception", e);
                        writer.println("goto-failed: " + e.getMessage());
                    }
                    continue;
                }
                // ---------- rotate:<deg>（度数のみ、数値以外は無視） ----------
                if (line.startsWith("rotate:")) {
                    String arg = line.substring("rotate:".length()).trim();
                    if (!arg.matches("^-?\\d+(\\.\\d+)?$")) {
                        writer.println("goto-ignored: use degrees like '90' or '-45'");
                        continue;
                    }
                    double deg = Double.parseDouble(arg);
                    rotate(qiContext, deg, writer);
                    continue;
                }
                if (line.startsWith("look:")) {
                    boolean onlyHeadFlag;
                    String onlyHead = line.substring(5,13);  // "onlyHead" or "fullBody"
                    onlyHeadFlag = "onlyHead".equals(onlyHead);
                    String toLook = line.substring(14);  // "right", "left", "center"
                    double x = 1, y = 0, z = 1;
                    if ("right".equals(toLook)) { y = -1; }
                    else if ("left".equals(toLook)) { y = 1; }
                    Frame robotFrame = qiContext.getActuation().robotFrame();
                    Transform transform = TransformBuilder.create().fromTranslation(new Vector3(x, y, z));
                    Mapping mapping = qiContext.getMapping();
                    FreeFrame targetFrame = mapping.makeFreeFrame();
                    targetFrame.update(robotFrame, transform, 0L);
                    if (lookAtFuture != null && !lookAtFuture.isDone()) {
                        lookAtFuture.requestCancellation();
                    }
                    lookAt = LookAtBuilder.with(qiContext)
                            .withFrame(targetFrame.frame())
                            .build();
                    lookAt.setPolicy(onlyHeadFlag ? LookAtMovementPolicy.HEAD_ONLY
                            : LookAtMovementPolicy.HEAD_AND_BASE);
                    lookAtFuture = lookAt.async().run();
                    writer.println("Finished looking");
                    continue;
                }
                if (line.startsWith("snap")) {
                    // 1枚撮って Base64 で返す
                    takePictureAndSend(qiContext, writer);
                    continue;
                }
                if (line.equals("nod")) {
                    doNod(qiContext);
                    writer.println("gesture-ok:nod");
                    continue;
                }
                if (line.startsWith("tilt")) {
                    doTilt(qiContext);
                    writer.println("gesture-ok:tilt:");
                    continue;
                }
                if (line.startsWith("anim:")) {
                    String name = line.substring("anim:".length()).trim();
                    playQianimByName(qiContext, name, writer);
                    continue;
                }
            }
        } catch (Exception e) {
            Log.e("TCP", "connection error", e);
        } finally {
            Log.i("TCP", "Resources are cleaned up.");
        }
    }
}
