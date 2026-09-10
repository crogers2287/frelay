package com.cfr.flipperrelay;

import org.junit.Test;
import static org.junit.Assert.*;

public class RelayAddressTest {
    @Test public void acceptsTailnetAndTls() {
        assertEquals("ws://100.64.0.1:8787/phone", RelayAddress.validate("ws://100.64.0.1:8787/phone"));
        assertEquals("wss://fred.example.ts.net/phone", RelayAddress.validate("wss://fred.example.ts.net/phone"));
        RelayAddress.validate("ws://[fd7a:115c:a1e0::1]:8787/phone");
    }
    @Test public void rejectsCleartextOutsideTailnetAndEmbeddedCredentials() {
        for (String s : new String[]{"ws://192.168.1.5:8787/phone", "ws://100.128.0.1/phone", "ws://100.64.300.1/phone",
                "ws://100.63.0.1/phone", "ws://100.64.1.1.attacker.example/phone", "ws://fred/phone", "https://fred/phone",
                "wss://token@fred/phone", "wss://fred/phone?token=abc", "ws://100.64.1.1/wrong"}) {
            assertThrows(s, IllegalArgumentException.class, () -> RelayAddress.validate(s));
        }
    }
}
