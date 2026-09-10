package com.cfr.flipperrelay;

import android.annotation.SuppressLint;
import android.bluetooth.*;
import android.content.Context;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/** UUIDs and big-endian buffer credits follow the upstream Flipper Android bridge. */
@SuppressLint("MissingPermission")
final class BleTransport implements Transport {
    static final UUID SERVICE = UUID.fromString("8fe5b3d5-2e7f-4a98-2a48-7acc60fe0000");
    private static final UUID RX = UUID.fromString("19ed82ae-ed21-4c9d-4145-228e61fe0000");
    private static final UUID TX = UUID.fromString("19ed82ae-ed21-4c9d-4145-228e62fe0000");
    private static final UUID FLOW = UUID.fromString("19ed82ae-ed21-4c9d-4145-228e63fe0000");
    private static final UUID CCC = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private record Event(String kind, int status) {}
    private final Context context;
    private final String address;
    private final Listener listener;
    private final LinkedBlockingQueue<Event> events = new LinkedBlockingQueue<>();
    private final Object creditLock = new Object();
    private volatile BluetoothGatt gatt;
    private volatile boolean closed;
    private volatile int mtu = 23;
    private int credits;
    private BluetoothGattCharacteristic tx;
    BleTransport(Context context, String address, Listener listener) {
        this.context = context; this.address = address; this.listener = listener;
    }
    private final BluetoothGattCallback callback = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt g, int status, int state) {
            if (closed) return;
            if (status == BluetoothGatt.GATT_SUCCESS && state == BluetoothProfile.STATE_CONNECTED)
                events.offer(new Event("connect", status));
            else if (state == BluetoothProfile.STATE_DISCONNECTED || status != 0) {
                events.offer(new Event("disconnect", status));
                listener.failed("BLE disconnected (status " + status + ")");
                synchronized (creditLock) { creditLock.notifyAll(); }
            }
        }
        @Override public void onServicesDiscovered(BluetoothGatt g, int status) { events.offer(new Event("services", status)); }
        @Override public void onMtuChanged(BluetoothGatt g, int value, int status) {
            if (status == 0) mtu = value;
            events.offer(new Event("mtu", 0)); // The default MTU remains usable if negotiation fails.
        }
        @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int status) { events.offer(new Event("subscribe", status)); }
        @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int status) { events.offer(new Event("write", status)); }
        @Override public void onCharacteristicRead(BluetoothGatt g, BluetoothGattCharacteristic c, int status) {
            if (status == 0 && c.getUuid().equals(FLOW)) updateCredits(c.getValue());
            events.offer(new Event("read", status));
        }
        @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
            byte[] data = c.getValue();
            if (closed || data == null) return;
            if (c.getUuid().equals(FLOW)) updateCredits(data);
            else if (c.getUuid().equals(RX)) listener.bytes(Arrays.copyOf(data, data.length));
        }
    };
    private void updateCredits(byte[] value) {
        if (value == null || value.length != 4) { listener.failed("Invalid BLE flow-control value"); return; }
        int n = ByteBuffer.wrap(value).getInt();
        if (n < 0 || n > 65536) { listener.failed("Invalid BLE buffer size"); return; }
        synchronized (creditLock) { credits = n; creditLock.notifyAll(); }
    }
    private void await(String kind, int seconds) throws Exception {
        Event event = events.poll(seconds, TimeUnit.SECONDS);
        if (closed || event == null) throw new IOException("BLE " + kind + " timed out or stopped");
        if (!kind.equals(event.kind) || event.status != 0)
            throw new IOException("BLE " + kind + " failed: " + event.kind + "/" + event.status);
    }
    @Override public void open() throws Exception {
        BluetoothAdapter adapter = context.getSystemService(BluetoothManager.class).getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new IOException("Enable Bluetooth on the phone");
        BluetoothDevice device = adapter.getRemoteDevice(address);
        if (device.getBondState() != BluetoothDevice.BOND_BONDED) {
            if (device.getBondState() != BluetoothDevice.BOND_BONDING && !device.createBond())
                throw new IOException("Could not start pairing");
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60);
            while (!closed && device.getBondState() != BluetoothDevice.BOND_BONDED && System.nanoTime() < deadline)
                Thread.sleep(200);
            if (closed || device.getBondState() != BluetoothDevice.BOND_BONDED)
                throw new IOException("Pairing not completed; confirm the code on phone and Flipper");
        }
        if (closed) throw new IOException("Stopped");
        gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE);
        if (gatt == null) throw new IOException("Could not open BLE");
        await("connect", 20);
        if (gatt.requestMtu(247)) await("mtu", 10);
        if (!gatt.discoverServices()) throw new IOException("Cannot discover BLE services");
        await("services", 15);
        BluetoothGattService service = gatt.getService(SERVICE);
        if (service == null) throw new IOException("Flipper RPC BLE service is missing");
        BluetoothGattCharacteristic rx = service.getCharacteristic(RX);
        tx = service.getCharacteristic(TX);
        BluetoothGattCharacteristic flow = service.getCharacteristic(FLOW);
        if (rx == null || tx == null || flow == null) throw new IOException("Flipper serial characteristics are missing");
        subscribe(rx); subscribe(flow);
        if (!gatt.readCharacteristic(flow)) throw new IOException("Cannot read BLE buffer size");
        await("read", 10);
    }
    private void subscribe(BluetoothGattCharacteristic c) throws Exception {
        if (!gatt.setCharacteristicNotification(c, true)) throw new IOException("Cannot enable BLE notifications");
        BluetoothGattDescriptor descriptor = c.getDescriptor(CCC);
        if (descriptor == null) throw new IOException("BLE CCC descriptor missing");
        descriptor.setValue((c.getProperties() & BluetoothGattCharacteristic.PROPERTY_NOTIFY) != 0
                ? BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE : BluetoothGattDescriptor.ENABLE_INDICATION_VALUE);
        if (!gatt.writeDescriptor(descriptor)) throw new IOException("Cannot subscribe to BLE notifications");
        await("subscribe", 10);
    }
    @Override public void write(byte[] data) throws Exception {
        int offset = 0;
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20);
        while (offset < data.length) {
            if (closed) throw new IOException("BLE stopped");
            int count;
            synchronized (creditLock) {
                while (credits == 0 && !closed) {
                    long remaining = deadline - System.nanoTime();
                    if (remaining <= 0) throw new IOException("BLE flow control timed out");
                    TimeUnit.NANOSECONDS.timedWait(creditLock, remaining);
                }
                if (closed) throw new IOException("BLE stopped");
                count = Math.min(Math.min(mtu - 3, 244), Math.min(credits, data.length - offset));
                credits -= count;
            }
            tx.setWriteType((tx.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE) != 0
                    ? BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT : BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE);
            tx.setValue(Arrays.copyOfRange(data, offset, offset + count));
            if (!gatt.writeCharacteristic(tx)) throw new IOException("BLE write rejected");
            await("write", 10);
            offset += count;
        }
    }
    @Override public void close() {
        closed = true;
        synchronized (creditLock) { creditLock.notifyAll(); }
        events.offer(new Event("closed", -1));
        BluetoothGatt g = gatt;
        if (g != null) { try { g.disconnect(); g.close(); } catch (SecurityException ignored) {} }
    }
}
