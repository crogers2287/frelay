package com.cfr.flipperrelay;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.hardware.usb.*;
import android.os.*;
import org.json.JSONObject;
import java.io.IOException;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import okhttp3.*;
import okio.ByteString;

public final class RelayService extends Service {
    private static final String CHANNEL = "flipper-relay";
    public static volatile String status = "Stopped";
    public static volatile boolean active;
    private volatile boolean running;
    private volatile Transport transport;
    private volatile WebSocket socket;
    private Thread worker;
    private PowerManager.WakeLock wakeLock;
    private final OkHttpClient client = new OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS)
            .connectTimeout(10, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS).build();
    @Override public IBinder onBind(Intent intent) { return null; }
    private Notification notification(String message) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, RelayService.class).setAction("STOP"), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .setContentTitle("Flipper Relay").setContentText(message).setContentIntent(open).setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "Stop", stop).build()).build();
    }
    private void update(String message) {
        status = message;
        if (running) getSystemService(NotificationManager.class).notify(42, notification(message));
    }
    @android.annotation.SuppressLint("WakelockTimeout")
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || "STOP".equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        if (running) return START_NOT_STICKY;
        getSystemService(NotificationManager.class).createNotificationChannel(
                new NotificationChannel(CHANNEL, "Flipper connection", NotificationManager.IMPORTANCE_LOW));
        startForeground(42, notification("Connecting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
        running = true; active = true;
        wakeLock = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "FlipperRelay:active");
        wakeLock.acquire(); // User-started foreground relay; released in onDestroy.
        worker = new Thread(this::runRelay, "flipper-relay"); worker.start();
        return START_NOT_STICKY;
    }
    private void runRelay() {
        SharedPreferences prefs = getSharedPreferences("relay", MODE_PRIVATE);
        int failures = 0;
        while (running) {
            AtomicBoolean healthy = new AtomicBoolean(true);
            AtomicBoolean ready = new AtomicBoolean(false);
            LinkedBlockingQueue<byte[]> writes = new LinkedBlockingQueue<>(64);
            CountDownLatch connected = new CountDownLatch(1);
            final WebSocket[] sessionSocket = new WebSocket[1];
            try {
                String url = RelayAddress.validate(prefs.getString("url", ""));
                String token = prefs.getString("token", "");
                if (token.length() < 32) throw new IOException("Enter the phone token from server setup");
                update("Connecting to server");
                WebSocket ws = client.newWebSocket(new Request.Builder().url(url).header("Authorization", "Bearer " + token).build(), new WebSocketListener() {
                    @Override public void onOpen(WebSocket ws, Response response) { connected.countDown(); }
                    @Override public void onMessage(WebSocket ws, ByteString bytes) {
                        if (!ready.get() || bytes.size() > 65536 || !writes.offer(bytes.toByteArray())) {
                            healthy.set(false); ws.cancel();
                        }
                    }
                    @Override public void onMessage(WebSocket ws, String text) {
                        // No remote configuration or shell execution; this channel carries RPC bytes only.
                        healthy.set(false); ws.close(1003, "Binary messages required");
                    }
                    @Override public void onFailure(WebSocket ws, Throwable t, Response r) {
                        healthy.set(false); connected.countDown();
                    }
                    @Override public void onClosing(WebSocket ws, int code, String reason) {
                        healthy.set(false); ws.close(code, null);
                    }
                    @Override public void onClosed(WebSocket ws, int code, String reason) { healthy.set(false); }
                });
                socket = ws; sessionSocket[0] = ws;
                if (!connected.await(12, TimeUnit.SECONDS) || !healthy.get()) throw new IOException("Server unavailable or phone token rejected");
                Transport.Listener listener = new Transport.Listener() {
                    public void bytes(byte[] data) {
                        WebSocket s = sessionSocket[0];
                        if (!healthy.get()) return;
                        if (s.queueSize() > 1024 * 1024 || !s.send(ByteString.of(data))) {
                            healthy.set(false); s.cancel();
                        }
                    }
                    public void failed(String message) { if (healthy.getAndSet(false)) update(message); }
                };
                String mode = prefs.getString("mode", "BLE");
                if ("USB".equals(mode)) {
                    UsbManager manager = getSystemService(UsbManager.class);
                    UsbDevice device = manager.getDeviceList().get(prefs.getString("usb", ""));
                    if (device == null) throw new IOException("Connect the selected Flipper by USB-C and press Start");
                    transport = new UsbTransport(manager, device, listener);
                } else {
                    transport = new BleTransport(this, prefs.getString("ble", ""), listener);
                }
                update("Connecting to Flipper via " + mode);
                transport.open();
                if (!running || !healthy.get()) throw new IOException("Connection interrupted");
                ready.set(true);
                if (!ws.send(new JSONObject().put("type", "ready").put("protocol", 1).put("transport", mode).toString()))
                    throw new IOException("Server disconnected");
                update("Connected via " + mode); failures = 0;
                while (running && healthy.get()) {
                    byte[] next = writes.poll(500, TimeUnit.MILLISECONDS);
                    if (next != null) {
                        transport.write(next);
                        if (!ws.send("{\"type\":\"written\"}")) throw new IOException("Server disconnected");
                    }
                }
            } catch (Exception e) {
                if (running) update(e instanceof IllegalArgumentException ? "Check server URL and device selection" : e.getMessage() == null ? "Connection failed" : e.getMessage());
            } finally {
                healthy.set(false); ready.set(false); writes.clear();
                Transport t = transport; transport = null; if (t != null) t.close();
                WebSocket s = socket; socket = null; if (s != null) s.cancel();
            }
            if (running) {
                failures++;
                try { Thread.sleep(Math.min(15000, 2000L * failures)); } catch (InterruptedException e) { break; }
            }
        }
    }
    @Override public void onDestroy() {
        running = false; active = false; status = "Stopped";
        if (worker != null) worker.interrupt();
        WebSocket s = socket; if (s != null) s.cancel();
        stopForeground(STOP_FOREGROUND_REMOVE);
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        client.dispatcher().executorService().shutdown();
        client.connectionPool().evictAll();
        super.onDestroy();
    }
}
