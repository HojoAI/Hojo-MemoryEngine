package com.memoryengine;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class MemoryEngineConfigTest {

  @Test
  void normalizesBaseUrlToApiV1() {
    MemoryEngineConfig cfg =
        MemoryEngineConfig.builder().baseUrl("http://127.0.0.1:6030").apiKey("k").build();
    assertEquals("http://127.0.0.1:6030/api/v1", cfg.getBaseUrl());
    assertEquals("http://127.0.0.1:6030/health", cfg.healthUrl());
  }

  @Test
  void keepsFullApiV1Path() {
    MemoryEngineConfig cfg =
        MemoryEngineConfig.builder()
            .baseUrl("http://127.0.0.1:9080/api/v1")
            .apiKey("k")
            .tenantId(1)
            .orgId(0)
            .build();
    assertTrue(cfg.getBaseUrl().endsWith("/api/v1"));
  }
}
