package com.cfr.flipperrelay;

interface Transport extends AutoCloseable {
    interface Listener { void bytes(byte[] data); void failed(String message); }
    void open() throws Exception;
    void write(byte[] data) throws Exception;
    void close();
}
