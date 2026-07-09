package com.memoryengine.model;

import com.fasterxml.jackson.annotation.JsonInclude;

/** LLM endpoint configuration. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record LLM(String baseUrl, String apiKey, String modelName) {}
