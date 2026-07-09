package com.memoryengine.changelog;

import com.fasterxml.jackson.databind.JsonNode;
import com.memoryengine.MemoryEngineException;
import com.memoryengine.internal.HttpTransport;
import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/** Background long-poll watcher for schema changelog (SDK hot-reload). */
public final class SchemaChangelogWatcher {

  private final HttpTransport http;
  private final Consumer<JsonNode> onEvent;
  private final long pollIntervalMs;
  private final AtomicBoolean running = new AtomicBoolean(false);
  private Thread thread;
  private String cursor = "0-0";

  public SchemaChangelogWatcher(
      HttpTransport http, Consumer<JsonNode> onEvent, long pollIntervalMs) {
    this.http = http;
    this.onEvent = onEvent;
    this.pollIntervalMs = pollIntervalMs;
  }

  public void start() {
    if (!running.compareAndSet(false, true)) {
      return;
    }
    thread =
        new Thread(
            () -> {
              while (running.get()) {
                try {
                  pollOnce();
                } catch (Exception ignored) {
                  // backoff on network errors
                }
                try {
                  Thread.sleep(pollIntervalMs);
                } catch (InterruptedException e) {
                  Thread.currentThread().interrupt();
                  break;
                }
              }
            },
            "memory-engine-changelog");
    thread.setDaemon(true);
    thread.start();
  }

  public void stop() {
    running.set(false);
    if (thread != null) {
      thread.interrupt();
      thread = null;
    }
  }

  private void pollOnce() throws IOException, InterruptedException {
    JsonNode root =
        http.get(
            "/schema/changelog/poll",
            Map.of(
                "cursor", cursor,
                "block_ms", String.valueOf(Math.min(pollIntervalMs, 30000))),
            Duration.ofSeconds(35));
    JsonNode data = http.dataNode(root);
    if (data == null) {
      return;
    }
    if (data.hasNonNull("cursor")) {
      cursor = data.get("cursor").asText(cursor);
    }
    JsonNode events = data.get("events");
    if (events == null || !events.isArray()) {
      return;
    }
    for (JsonNode event : events) {
      try {
        onEvent.accept(event);
      } catch (Exception ignored) {
        // aligned with Python: log and continue (do not stop watcher)
      }
    }
  }
}
