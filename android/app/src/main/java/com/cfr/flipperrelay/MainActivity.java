package com.cfr.flipperrelay;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.*;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.hardware.usb.*;
import android.os.*;
import android.text.InputType;
import android.view.View;
import android.widget.*;
import androidx.core.content.ContextCompat;
import java.util.*;

@SuppressLint("MissingPermission")
public final class MainActivity extends Activity {
    private static final String USB_PERMISSION = "com.cfr.flipperrelay.USB_PERMISSION";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final LinkedHashMap<String, String> devices = new LinkedHashMap<>();
    private EditText url, token;
    private Spinner mode, device;
    private TextView status;
    private BluetoothLeScanner scanner;
    private boolean receiverRegistered;
    private final Runnable statusTick = new Runnable() {
        public void run() { status.setText(RelayService.status); handler.postDelayed(this, 1000); }
    };
    private final ScanCallback scanCallback = new ScanCallback() {
        @Override public void onScanResult(int type, ScanResult result) {
            BluetoothDevice d = result.getDevice();
            String name = d.getName();
            boolean flipper = name != null && name.toLowerCase(Locale.ROOT).contains("flipper");
            if (result.getScanRecord() != null && result.getScanRecord().getServiceUuids() != null)
                flipper |= result.getScanRecord().getServiceUuids().contains(new ParcelUuid(BleTransport.SERVICE));
            if (flipper) runOnUiThread(() -> { devices.put(d.getAddress(), (name == null ? "Flipper" : name) + " • " + d.getAddress()); refreshSpinner(); });
        }
        @Override public void onScanFailed(int error) { runOnUiThread(() -> show("BLE scan failed: " + error)); }
    };
    private final BroadcastReceiver usbReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) {
            if (USB_PERMISSION.equals(i.getAction())) {
                // Recheck UsbManager instead of trusting broadcast extras.
                UsbDevice d = getSystemService(UsbManager.class).getDeviceList().get(getSharedPreferences("relay", 0).getString("usb", ""));
                if (d != null && getSystemService(UsbManager.class).hasPermission(d)) launchRelay();
                else show("USB permission was not granted");
            }
        }
    };
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(24 * getResources().getDisplayMetrics().density); layout.setPadding(pad, pad, pad, pad);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.addView(layout); setContentView(scroll);
        // Account for Android 15 edge-to-edge system bars and the keyboard.
        scroll.setOnApplyWindowInsetsListener((v, insets) -> {
            android.graphics.Insets bars = insets.getInsets(android.view.WindowInsets.Type.systemBars() | android.view.WindowInsets.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom); return insets;
        });
        TextView title = label(layout, "Flipper Relay"); title.setTextSize(28); title.setTextColor(Color.rgb(210, 80, 0));
        label(layout, "Connect your agent through this phone. Keep Tailscale connected on the phone and server.");
        SharedPreferences p = getSharedPreferences("relay", 0);
        label(layout, "Server URL"); url = new EditText(this); url.setSingleLine(); url.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        url.setHint("ws://100.x.x.x:9434/phone"); url.setText(p.getString("url", "")); layout.addView(url);
        label(layout, "Phone token"); token = new EditText(this); token.setSingleLine(); token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        token.setText(p.getString("token", "")); layout.addView(token);
        label(layout, "Connection to Flipper"); mode = new Spinner(this);
        mode.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new String[]{"BLE", "USB"})); layout.addView(mode);
        mode.setSelection("USB".equals(p.getString("mode", "BLE")) ? 1 : 0);
        label(layout, "Flipper device"); device = new Spinner(this); layout.addView(device);
        button(layout, "Find devices", this::findDevices);
        button(layout, "Start relay", this::startRelay);
        button(layout, "Stop relay", () -> stopService(new Intent(this, RelayService.class)));
        status = label(layout, RelayService.status); status.setTextSize(18);
        label(layout, "BLE: enable Bluetooth on Flipper and confirm pairing when prompted. Close other Flipper connections.\n\nUSB: use a data-capable USB-C cable and approve USB access. Reconnect and press Start after changing cables or connection mode.");
        mode.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) { stopScan(); devices.clear(); refreshSpinner(); }
            public void onNothingSelected(AdapterView<?> parent) {}
        });
        ContextCompat.registerReceiver(this, usbReceiver, new IntentFilter(USB_PERMISSION), ContextCompat.RECEIVER_NOT_EXPORTED);
        receiverRegistered = true;
    }
    private TextView label(LinearLayout l, String text) { TextView t = new TextView(this); t.setText(text); t.setTextSize(16); t.setPadding(0, 16, 0, 8); l.addView(t); return t; }
    private void button(LinearLayout l, String text, Runnable action) { Button b = new Button(this); b.setText(text); b.setOnClickListener(v -> action.run()); l.addView(b); }
    private void show(String text) { new AlertDialog.Builder(this).setMessage(text).setPositiveButton("OK", null).show(); }
    private boolean blePermissions() {
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT}, 7); return false;
        }
        return true;
    }
    private void findDevices() {
        devices.clear(); stopScan();
        if (mode.getSelectedItem().equals("USB")) {
            for (UsbDevice d : getSystemService(UsbManager.class).getDeviceList().values())
                if (UsbTransport.isFlipper(d)) devices.put(d.getDeviceName(), "Flipper USB • " + d.getDeviceName());
            refreshSpinner(); if (devices.isEmpty()) show("No Flipper USB CDC device found. Check the data cable and normal Flipper firmware mode.");
            return;
        }
        if (!blePermissions()) return;
        BluetoothAdapter adapter = getSystemService(BluetoothManager.class).getAdapter();
        if (adapter == null || !adapter.isEnabled()) { show("Enable Bluetooth first"); return; }
        for (BluetoothDevice d : adapter.getBondedDevices())
            if (d.getName() != null && d.getName().toLowerCase(Locale.ROOT).contains("flipper")) devices.put(d.getAddress(), d.getName() + " • " + d.getAddress());
        refreshSpinner(); scanner = adapter.getBluetoothLeScanner();
        scanner.startScan(scanCallback); handler.postDelayed(this::stopScan, 12000);
    }
    private void refreshSpinner() {
        int old = device.getSelectedItemPosition();
        device.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new ArrayList<>(devices.values())));
        if (old >= 0 && old < devices.size()) device.setSelection(old);
    }
    private void stopScan() { if (scanner != null) { try { scanner.stopScan(scanCallback); } catch (SecurityException ignored) {} scanner = null; } }
    private void startRelay() {
        if (RelayService.active) { show("Stop the current relay before changing its connection"); return; }
        try { RelayAddress.validate(url.getText().toString()); } catch (Exception e) { show(e.getMessage()); return; }
        if (token.getText().toString().trim().length() < 32) { show("Paste the phone token generated by server setup"); return; }
        if (device.getSelectedItemPosition() < 0 || devices.isEmpty()) { show("Find and select your Flipper first"); return; }
        String selected = new ArrayList<>(devices.keySet()).get(device.getSelectedItemPosition());
        String transport = mode.getSelectedItem().toString();
        if ("BLE".equals(transport) && !blePermissions()) return;
        getSharedPreferences("relay", 0).edit().putString("url", url.getText().toString().trim()).putString("token", token.getText().toString().trim())
                .putString("mode", transport).putString("BLE".equals(transport) ? "ble" : "usb", selected).apply();
        if ("USB".equals(transport)) {
            UsbManager manager = getSystemService(UsbManager.class); UsbDevice d = manager.getDeviceList().get(selected);
            if (d == null) { show("USB device disconnected"); return; }
            if (!manager.hasPermission(d)) {
                manager.requestPermission(d, PendingIntent.getBroadcast(this, 3, new Intent(USB_PERMISSION).setPackage(getPackageName()), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
                return;
            }
        }
        launchRelay();
    }
    private void launchRelay() {
        stopScan();
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 8);
        startForegroundService(new Intent(this, RelayService.class));
    }
    @Override protected void onResume() { super.onResume(); handler.post(statusTick); }
    @Override protected void onPause() { handler.removeCallbacks(statusTick); stopScan(); super.onPause(); }
    @Override protected void onDestroy() { handler.removeCallbacksAndMessages(null); if (receiverRegistered) unregisterReceiver(usbReceiver); super.onDestroy(); }
}
