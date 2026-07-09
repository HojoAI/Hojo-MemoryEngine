package com.memoryengine;

import java.time.Duration;

/** HTTP timeouts from env (aligned with Python {@code _http_timeout} / {@code _parse_timeout}). */
public final class SdkTimeouts {

  private SdkTimeouts() {}

  public static Duration httpTimeout() {
    String raw = System.getenv("MEMORY_ENGINE_HTTP_TIMEOUT");
    if (raw != null && !raw.isBlank()) {
      return Duration.ofMillis((long) (Double.parseDouble(raw.trim()) * 1000));
    }
    return Duration.ofSeconds(30);
  }

  public static Duration parseTimeout() {
    String raw = System.getenv("MEMORY_ENGINE_PARSE_TIMEOUT");
    if (raw != null && !raw.isBlank()) {
      return Duration.ofMillis((long) (Double.parseDouble(raw.trim()) * 1000));
    }
    Duration http = httpTimeout();
    Duration floor = Duration.ofSeconds(180);
    return http.compareTo(floor) >= 0 ? http : floor;
  }

  public static Duration retrieveTimeout() {
    Duration http = httpTimeout();
    Duration floor = Duration.ofSeconds(120);
    return http.compareTo(floor) >= 0 ? http : floor;
  }
}
