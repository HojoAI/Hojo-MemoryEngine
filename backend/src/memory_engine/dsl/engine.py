"""Minimal DSL engine: compose schema/data steps for Temporal orchestration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DslStep(BaseModel):
    """Single orchestration step."""

    op: str = Field(..., description="schema.get|schema.create|data.parse|data.retrieve|...")
    params: dict[str, Any] = Field(default_factory=dict)


class DslPipeline(BaseModel):
    """Ordered pipeline of steps."""

    name: str = "default"
    steps: list[DslStep]


class DslEngine:
    """Execute DSL steps against in-process service layer (used by Temporal activity)."""

    async def run_step(
        self,
        session: Any,
        ctx: Any,
        step: DslStep,
    ) -> Any:
        op = step.op
        p = step.params

        if op == "schema.get":
            from memory_engine.services import memory_field as mf
            from memory_engine.schemas.common import SearchMode

            row = await mf.search_by_mode(
                session, ctx, p["name"], SearchMode(p.get("mode", "EXACT"))
            )
            return row

        if op == "schema.create":
            from memory_engine.services import memory_field as mf
            from memory_engine.schemas.memory_field import MemoryFieldCreate

            return await mf.create(session, ctx, MemoryFieldCreate(**p))

        if op == "data.create":
            from memory_engine.services import memory_data as md
            from memory_engine.schemas.memory_field import MemoryDataCreate

            return await md.create(session, ctx, MemoryDataCreate(**p))

        if op == "noop":
            return p

        raise ValueError(f"unknown dsl op: {op}")

    async def run_pipeline(self, session: Any, ctx: Any, pipeline: DslPipeline) -> list[Any]:
        results: list[Any] = []
        for step in pipeline.steps:
            results.append(await self.run_step(session, ctx, step))
        return results
