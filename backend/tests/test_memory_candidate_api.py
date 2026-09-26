"""Tests for M13 memory candidate extraction and comparison APIs."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from memory_engine.api.deps import get_request_context
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.main import app
from memory_engine.schemas.memory_candidate import (
    MemoryCandidateCompareRequest,
    MemoryCandidateExtractRequest,
)
from memory_engine.integrations.oss_document_loader import LoadedDocument
from memory_engine.core.exceptions import ValidationError
from memory_engine.services import memory_candidate


async def _mock_get_db():
    yield AsyncMock()


async def _mock_context() -> RequestContext:
    return RequestContext(
        tenant_id=1,
        org_id=2,
        user_id=3,
        permissions={"data:read"},
    )


@pytest.fixture(autouse=True)
def dependencies() -> None:
    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[get_request_context] = _mock_context
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_request_context, None)


@pytest.mark.asyncio
async def test_extract_candidates_returns_camel_case_without_writing() -> None:
    completion = json.dumps(
        {
            "candidates": [
                {
                    "category": "identity",
                    "label": "关于我",
                    "content": "用户是 Acme 的产品负责人。",
                    "confidence": 0.95,
                    "sensitivity": "normal",
                    "source_spans": [],
                }
            ],
            "rejected": [],
            "warnings": [],
        },
        ensure_ascii=False,
    )
    with (
        patch.object(
            memory_candidate.llm_client,
            "chat_completion",
            new_callable=AsyncMock,
            return_value=(completion, 10, 20),
        ),
        patch.object(
            memory_candidate.billing_service,
            "emit_llm_completion",
            new_callable=AsyncMock,
            return_value="event-1",
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/memory/candidates/extract",
                json={
                    "requestId": "req_test",
                    "userId": "user-1",
                    "scene": "memory_add",
                    "source": {"type": "manual_text", "text": "我在 Acme 做产品。"},
                    "language": "zh-CN",
                },
            )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["requestId"] == "req_test"
    assert data["candidates"][0]["candidateId"] == "cand_test_1"
    assert data["candidates"][0]["category"] == "identity"
    assert "user_id" not in data


@pytest.mark.asyncio
async def test_extract_request_validation_logs_safe_error_details(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="memory_engine.main")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/memory/candidates/extract",
            json={"userId": "user-1", "source": {"type": "manual_text", "text": ""}},
        )

    assert response.status_code == 422
    assert "Memory candidate request validation failed" in caplog.text
    assert "body.source" in caplog.text


@pytest.mark.asyncio
async def test_extract_domain_validation_logs_reason(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="memory_engine.main")
    with patch.object(
        memory_candidate.oss_document_loader,
        "load_document_text",
        new_callable=AsyncMock,
        side_effect=ValidationError("OSS_DOWNLOAD_FAILED: upstream returned HTTP 403"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/memory/candidates/extract",
                json={
                    "userId": "user-1",
                    "source": {
                        "type": "import_file",
                        "ossUrl": "https://bucket.oss-cn-shanghai.aliyuncs.com/private.pdf",
                    },
                },
            )

    assert response.status_code == 422
    assert "Memory candidate request rejected" in caplog.text
    assert "OSS_DOWNLOAD_FAILED: upstream returned HTTP 403" in caplog.text
    assert "private.pdf" not in caplog.text


@pytest.mark.asyncio
async def test_extract_candidates_reads_oss_document_without_sending_url_to_llm() -> None:
    completion = json.dumps(
        {
            "candidates": [
                {
                    "category": "identity",
                    "label": "关于我",
                    "content": "用户负责企业产品。",
                }
            ],
            "rejected": [],
            "warnings": [],
        },
        ensure_ascii=False,
    )
    signed_url = "https://bucket.oss-cn-shanghai.aliyuncs.com/memory.md?Expires=1"
    with (
        patch.object(
            memory_candidate.oss_document_loader,
            "load_document_text",
            new_callable=AsyncMock,
            return_value=LoadedDocument(text="用户负责企业产品。", warnings=[]),
        ) as loader,
        patch.object(
            memory_candidate.llm_client,
            "chat_completion",
            new_callable=AsyncMock,
            return_value=(completion, 10, 20),
        ) as llm,
        patch.object(
            memory_candidate.billing_service,
            "emit_llm_completion",
            new_callable=AsyncMock,
            return_value="event-1",
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/memory/candidates/extract",
                json={
                    "requestId": "req_oss",
                    "userId": "user-1",
                    "source": {
                        "type": "manual_text",
                        "ossUrl": signed_url,
                        "text": "这段文本不应被使用。",
                    },
                },
            )

    assert response.status_code == 200
    loader.assert_awaited_once_with(signed_url)
    prompt = llm.await_args.args[0]
    assert "用户负责企业产品。" in prompt
    assert "这段文本不应被使用。" not in prompt
    assert signed_url not in prompt
    assert '"type": "import_file"' in prompt


@pytest.mark.asyncio
async def test_extract_converts_quoted_source_spans_to_offsets() -> None:
    source_text = "我在 Acme 做产品。"
    completion = json.dumps(
        {
            "candidates": [
                {
                    "category": "identity",
                    "label": "关于我",
                    "content": "用户在 Acme 从事产品工作。",
                    "source_spans": [source_text, "模型虚构的原文"],
                }
            ]
        },
        ensure_ascii=False,
    )
    with (
        patch.object(
            memory_candidate.llm_client,
            "chat_completion",
            new_callable=AsyncMock,
            return_value=(completion, 10, 20),
        ),
        patch.object(
            memory_candidate.billing_service,
            "emit_llm_completion",
            new_callable=AsyncMock,
            return_value="event-1",
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/memory/candidates/extract",
                json={
                    "userId": "user-1",
                    "source": {"type": "manual_text", "text": source_text},
                },
            )

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["sourceSpans"] == [
        {"start": 0, "end": len(source_text)}
    ]
    assert data["warnings"] == [
        "Converted 1 quoted source spans at candidate index 0",
        "Dropped 1 invalid source spans at candidate index 0",
    ]


def test_extract_source_requires_at_least_one_input_and_accepts_both() -> None:
    common = {"userId": "user-1", "source": {"type": "import_file"}}
    with pytest.raises(ValueError, match="text or ossUrl"):
        MemoryCandidateExtractRequest.model_validate(common)

    common["source"] = {
        "type": "import_file",
        "text": "正文",
        "ossUrl": "https://bucket.oss-cn-shanghai.aliyuncs.com/memory.txt",
    }
    body = MemoryCandidateExtractRequest.model_validate(common)
    assert body.source.text == "正文"
    assert body.source.oss_url is not None

    common["source"] = {
        "type": "import_file",
        "text": "",
        "ossUrl": "https://bucket.oss-cn-shanghai.aliyuncs.com/memory.txt",
    }
    body = MemoryCandidateExtractRequest.model_validate(common)
    assert body.source.text == ""
    assert body.source.oss_url is not None


@pytest.mark.asyncio
async def test_extract_candidates_uses_text_when_oss_url_is_blank() -> None:
    completion = '{"candidates":[],"rejected":[],"warnings":[]}'
    with (
        patch.object(
            memory_candidate.oss_document_loader,
            "load_document_text",
            new_callable=AsyncMock,
        ) as loader,
        patch.object(
            memory_candidate.llm_client,
            "chat_completion",
            new_callable=AsyncMock,
            return_value=(completion, 1, 1),
        ) as llm,
        patch.object(
            memory_candidate.billing_service,
            "emit_llm_completion",
            new_callable=AsyncMock,
            return_value="event-1",
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/memory/candidates/extract",
                json={
                    "userId": "user-1",
                    "source": {
                        "type": "manual_text",
                        "ossUrl": "   ",
                        "text": "使用文本内容。",
                    },
                },
            )
    assert response.status_code == 200
    loader.assert_not_awaited()
    assert "使用文本内容。" in llm.await_args.args[0]


@pytest.mark.asyncio
async def test_compare_exact_match_skips_llm() -> None:
    body = MemoryCandidateCompareRequest.model_validate(
        {
            "requestId": "req_compare",
            "userId": "user-1",
            "candidate": {
                "candidateId": "cand_1",
                "category": "projects",
                "label": "项目",
                "content": "Q3 完成企业版定价试点。",
            },
        }
    )
    claims = [
        {
            "claim_id": "mem-1",
            "revision": 2,
            "dimension": "projects",
            "text": " Q3 完成企业版定价试点。 ",
        }
    ]
    with (
        patch.object(
            memory_candidate.memory_claim_store,
            "list_current_claims",
            new_callable=AsyncMock,
            return_value=claims,
        ),
        patch.object(
            memory_candidate.llm_client, "chat_completion", new_callable=AsyncMock
        ) as llm,
    ):
        result = await memory_candidate.compare_candidate(
            SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
        )
    assert result.result == "DUPLICATE"
    assert result.matched_item_ids == ["mem-1"]
    llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_compare_endpoint_returns_new_when_user_has_no_claims() -> None:
    with (
        patch.object(
            memory_candidate.memory_claim_store,
            "list_current_claims",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(
            memory_candidate.llm_client, "chat_completion", new_callable=AsyncMock
        ) as llm,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/memory/candidates/compare",
                json={
                    "requestId": "req_new",
                    "userId": "user-1",
                    "candidate": {
                        "candidateId": "cand_1",
                        "category": "projects",
                        "label": "项目",
                        "content": "Q3 完成企业版定价试点。",
                    },
                },
            )
    assert response.status_code == 200
    assert response.json()["data"]["result"] == "NEW"
    llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_compare_merge_uses_only_existing_item_ids() -> None:
    body = MemoryCandidateCompareRequest.model_validate(
        {
            "requestId": "req_merge",
            "userId": "user-1",
            "candidate": {
                "candidateId": "cand_1",
                "category": "projects",
                "label": "项目",
                "content": "Q3 完成企业版定价试点。",
            },
        }
    )
    completion = json.dumps(
        {
            "result": "MERGE",
            "confidence": 0.91,
            "matched_item_ids": ["mem-1"],
            "reason_code": "SAME_GOAL",
            "display_reason": "同一目标，可补充季度信息",
            "merge_preview": {
                "content": "Q3 推进企业版定价试点，并在十月前完成。",
                "base_item_id": "mem-1",
            },
        },
        ensure_ascii=False,
    )
    claims = [
        {
            "claim_id": "mem-1",
            "revision": 3,
            "dimension": "projects",
            "text": "十月前完成企业版定价试点。",
        }
    ]
    with (
        patch.object(
            memory_candidate.memory_claim_store,
            "list_current_claims",
            new_callable=AsyncMock,
            return_value=claims,
        ),
        patch.object(
            memory_candidate.llm_client,
            "chat_completion",
            new_callable=AsyncMock,
            return_value=(completion, 10, 20),
        ),
        patch.object(
            memory_candidate.billing_service,
            "emit_llm_completion",
            new_callable=AsyncMock,
            return_value="event-1",
        ),
    ):
        result = await memory_candidate.compare_candidate(
            SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
        )
    assert result.result == "MERGE"
    assert result.merge_preview is not None
    assert result.merge_preview.base_item_id == "mem-1"
    assert result.merge_preview.base_version == 3


@pytest.mark.asyncio
async def test_extract_skips_invalid_category_from_model() -> None:
    completion = '{"candidates":[{"category":"other","label":"其他","content":"x"}]}'
    request = {
        "requestId": "req_bad",
        "userId": "user-1",
        "source": {"type": "manual_text", "text": "some input"},
    }
    with (
        patch.object(
            memory_candidate.llm_client,
            "chat_completion",
            new_callable=AsyncMock,
            return_value=(completion, 1, 1),
        ),
        patch.object(
            memory_candidate.billing_service,
            "emit_llm_completion",
            new_callable=AsyncMock,
            return_value="event-1",
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/memory/candidates/extract", json=request
            )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["candidates"] == []
    assert data["rejected"] == [
        {"content": "x", "reason": "INVALID_CANDIDATE_FORMAT"}
    ]
    assert data["warnings"] == ["Skipped invalid candidate at index 0"]
