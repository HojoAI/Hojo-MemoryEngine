package com.memoryengine;

/** Missing or invalid {@code MEMORY_ENGINE_*} environment configuration (aligned with Python). */
public class MemoryEngineConfigError extends RuntimeException {

  public MemoryEngineConfigError(String message) {
    super(message);
  }
}
