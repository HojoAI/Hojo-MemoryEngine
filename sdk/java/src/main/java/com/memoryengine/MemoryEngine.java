package com.memoryengine;

import com.fasterxml.jackson.databind.JsonNode;
import com.memoryengine.internal.HttpTransport;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

/**
 * MemoryEngine Java SDK entry point.
 *
 * <pre>{@code
 * MemoryEngine mos = MemoryEngine.fromEnvironment();
 * var schema = mos.schema().getOrCreate("用户年龄", SearchEnum.SEMANTIC, null);
 * var data = mos.data().parse(schema.name(), new ParseInput("我25岁"), WriteRule.OVERWRITE);
 * }</pre>
 */
public final class MemoryEngine {

  private final MemoryEngineConfig config;
  private final HttpTransport http;
  private final Schema schema;
  private final Data data;

  public MemoryEngine(MemoryEngineConfig config) {
    this.config = config;
    this.http = new HttpTransport(config);
    this.schema = new Schema(http);
    this.data = new Data(http);
  }

  public static MemoryEngine fromEnvironment() {
    return new MemoryEngine(MemoryEngineConfig.fromEnvironment());
  }

  public static MemoryEngine create(String baseUrl, String apiKey, long tenantId) {
    return new MemoryEngine(
        MemoryEngineConfig.builder().baseUrl(baseUrl).apiKey(apiKey).tenantId(tenantId).build());
  }

  public MemoryEngineConfig config() {
    return config;
  }

  public Schema schema() {
    return schema;
  }

  public Data data() {
    return data;
  }

  public HttpTransport http() {
    return http;
  }

  /** Health check ({@code GET /health}). */
  public String health() throws IOException, InterruptedException {
    HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
    HttpRequest req =
        HttpRequest.newBuilder()
            .uri(URI.create(config.healthUrl()))
            .GET()
            .timeout(Duration.ofSeconds(10))
            .build();
    HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
    return resp.body();
  }

  /** Raw GET under /api/v1. */
  public JsonNode get(String path) throws IOException, InterruptedException {
    return http.get(path, Map.of(), Duration.ofSeconds(30));
  }
}
