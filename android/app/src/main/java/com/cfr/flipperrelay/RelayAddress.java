package com.cfr.flipperrelay;

import java.net.URI;

/** Cleartext is only permitted to literal Tailscale addresses; DNS requires TLS. */
public final class RelayAddress {
    public static String validate(String value) {
        URI u = URI.create(value.trim());
        String host = u.getHost();
        if (host == null || u.getUserInfo() != null || u.getFragment() != null || u.getQuery() != null
                || !"/phone".equals(u.getPath())) throw new IllegalArgumentException("Use the server's /phone URL");
        boolean tailnet = false;
        if (host.matches("100\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}")) {
            String[] p = host.split("\\.");
            tailnet = Integer.parseInt(p[1]) >= 64 && Integer.parseInt(p[1]) <= 127
                    && Integer.parseInt(p[2]) <= 255 && Integer.parseInt(p[3]) <= 255;
        }
        String v6 = host.replace("[", "").replace("]", "").toLowerCase(java.util.Locale.ROOT);
        tailnet |= v6.startsWith("fd7a:115c:a1e0:");
        if (!"wss".equals(u.getScheme()) && !("ws".equals(u.getScheme()) && tailnet))
            throw new IllegalArgumentException("Use ws:// with a Tailscale IP, or wss:// with a valid TLS certificate");
        return u.toString();
    }
}
