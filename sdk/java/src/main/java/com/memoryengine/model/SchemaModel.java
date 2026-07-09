package com.memoryengine.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/** Memory field (schema) summary. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record SchemaModel(String name, Long id) {}
