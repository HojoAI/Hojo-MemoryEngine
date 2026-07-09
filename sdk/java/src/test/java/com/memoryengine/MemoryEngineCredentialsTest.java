package com.memoryengine;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

class MemoryEngineCredentialsTest {

  @AfterEach
  void tearDown() {
    MemoryEngineCredentials.clearSessionCache();
  }

  @Test
  void derivePrefixFromSecret() {
    String key = "mos_Ufzwx1kKITli" + "extra_secret_part";
    assertEquals("mos_Ufzwx1kKITli", MemoryEngineCredentials.derivePrefixFromSecret(key));
  }

  @Test
  void resolveKeyPrefixFromSecretOnly() {
    MemoryEngineConfig cfg =
        MemoryEngineConfig.builder()
            .apiKey("mos_Ufzwx1kKITliabcdefghij")
            .apiKeyPrefix(null)
            .build();
    assertEquals("mos_Ufzwx1kKITli", MemoryEngineCredentials.resolveKeyPrefix(cfg));
  }

  @Test
  void requireApiKeySecretMissing() {
    MemoryEngineConfig cfg = MemoryEngineConfig.builder().apiKey("").build();
    assertThrows(MemoryEngineConfigError.class, () -> MemoryEngineCredentials.requireApiKeySecret(cfg));
  }
}
