package com.cfr.flipperrelay;

import android.hardware.usb.*;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.TimeUnit;

/** Android USB-host CDC ACM. No root, serial driver, or USB-debugging required. */
final class UsbTransport implements Transport {
    private final UsbManager manager;
    private final UsbDevice device;
    private final Listener listener;
    private volatile UsbDeviceConnection connection;
    private UsbInterface control, dataInterface;
    private UsbEndpoint input, output;
    private volatile boolean closed;
    private Thread reader;
    private byte[] pending = new byte[0];
    UsbTransport(UsbManager manager, UsbDevice device, Listener listener) {
        this.manager = manager; this.device = device; this.listener = listener;
    }
    static boolean isFlipper(UsbDevice d) {
        if (d.getVendorId() != 0x0483 || d.getProductId() != 0x5740) return false;
        for (int i = 0; i < d.getInterfaceCount(); i++)
            if (d.getInterface(i).getInterfaceClass() == UsbConstants.USB_CLASS_CDC_DATA) return true;
        return false;
    }
    @Override public void open() throws Exception {
        if (closed || !manager.hasPermission(device)) throw new IOException("USB permission missing; start relay from the app");
        for (int i = 0; i < device.getInterfaceCount(); i++) {
            UsbInterface f = device.getInterface(i);
            if (f.getInterfaceClass() == UsbConstants.USB_CLASS_COMM) control = f;
            if (f.getInterfaceClass() == UsbConstants.USB_CLASS_CDC_DATA) dataInterface = f;
        }
        if (control == null || dataInterface == null) throw new IOException("Flipper must be in normal USB CDC mode");
        for (int i = 0; i < dataInterface.getEndpointCount(); i++) {
            UsbEndpoint e = dataInterface.getEndpoint(i);
            if (e.getType() == UsbConstants.USB_ENDPOINT_XFER_BULK) {
                if (e.getDirection() == UsbConstants.USB_DIR_IN) input = e; else output = e;
            }
        }
        if (input == null || output == null) throw new IOException("USB CDC endpoints missing");
        connection = manager.openDevice(device);
        if (connection == null) throw new IOException("Cannot open USB device");
        if (!connection.claimInterface(control, true) || !connection.claimInterface(dataInterface, true))
            throw new IOException("USB interface is busy");
        byte[] coding = ByteBuffer.allocate(7).order(ByteOrder.LITTLE_ENDIAN).putInt(230400).put((byte)0).put((byte)0).put((byte)8).array();
        if (connection.controlTransfer(0x21, 0x20, 0, control.getId(), coding, coding.length, 2000) != 7)
            throw new IOException("Cannot configure USB CDC");
        setLines(0); // Reset any previous CLI/RPC session before opening this one.
        Thread.sleep(200);
        setLines(3); // DTR + RTS
        awaitMarker(">: ".getBytes(StandardCharsets.US_ASCII), 8000);
        write("start_rpc_session\r".getBytes(StandardCharsets.US_ASCII));
        awaitMarker(new byte[]{10}, 5000); // Consume CLI echo before forwarding protobuf bytes.
        if (pending.length > 0) { listener.bytes(pending); pending = new byte[0]; }
        reader = new Thread(() -> {
            byte[] buffer = new byte[4096];
            while (!closed) {
                int n = connection.bulkTransfer(input, buffer, buffer.length, 1000);
                if (n > 0 && !closed) listener.bytes(Arrays.copyOf(buffer, n));
                else if (!closed && !manager.getDeviceList().containsKey(device.getDeviceName())) {
                    listener.failed("USB cable disconnected"); break;
                }
            }
        }, "flipper-usb-read");
        reader.start();
    }
    private void setLines(int value) throws IOException {
        if (connection.controlTransfer(0x21, 0x22, value, control.getId(), null, 0, 2000) < 0)
            throw new IOException("USB control-line request failed");
    }
    private void awaitMarker(byte[] marker, int timeoutMs) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMs);
        int matched = 0;
        while (!closed && System.nanoTime() < deadline) {
            byte[] buffer = pending.length > 0 ? pending : new byte[4096];
            int n = pending.length > 0 ? pending.length : connection.bulkTransfer(input, buffer, buffer.length, 250);
            pending = new byte[0];
            for (int i = 0; i < n; i++) {
                matched = buffer[i] == marker[matched] ? matched + 1 : (buffer[i] == marker[0] ? 1 : 0);
                if (matched == marker.length) {
                    pending = Arrays.copyOfRange(buffer, i + 1, n);
                    return;
                }
            }
        }
        throw new IOException("Flipper USB RPC handshake timed out; reconnect the cable and close other Flipper apps");
    }
    @Override public synchronized void write(byte[] bytes) throws Exception {
        int offset = 0;
        while (!closed && offset < bytes.length) {
            int n = connection.bulkTransfer(output, bytes, offset, Math.min(4096, bytes.length - offset), 3000);
            if (n <= 0) throw new IOException("USB write failed");
            offset += n;
        }
        if (closed) throw new IOException("USB stopped");
    }
    @Override public void close() {
        closed = true;
        UsbDeviceConnection c = connection;
        if (c != null) {
            if (reader != null && reader != Thread.currentThread()) {
                try { reader.join(1500); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            }
            try { if (control != null) setLines(0); } catch (Exception ignored) {}
            if (dataInterface != null) c.releaseInterface(dataInterface);
            if (control != null) c.releaseInterface(control);
            c.close();
        }
    }
}
