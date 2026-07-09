package com.memoryengine;

/** MemoryEngine API error. */
public class MemoryEngineException extends RuntimeException {

  private final int statusCode;

  public MemoryEngineException(String message) {
    super(message);
    this.statusCode = 0;
  }

  public MemoryEngineException(String message, int statusCode) {
    super(message);
    this.statusCode = statusCode;
  }

  public MemoryEngineException(String message, Throwable cause) {
    super(message, cause);
    this.statusCode = 0;
  }

  public int getStatusCode() {
    return statusCode;
  }
}
