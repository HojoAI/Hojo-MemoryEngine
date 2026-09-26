"""Tests for controlled OSS document loading."""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from pypdf import PdfWriter

from memory_engine.core.exceptions import ValidationError
from memory_engine.integrations import oss_document_loader


@pytest.mark.asyncio
async def test_loads_utf8_text_from_aliyun_oss() -> None:
    with patch.object(
        oss_document_loader,
        "_download",
        new_callable=AsyncMock,
        return_value=("记忆正文".encode(), "text/plain; charset=utf-8"),
    ):
        document = await oss_document_loader.load_document_text(
            "https://bucket.oss-cn-shanghai.aliyuncs.com/memory.txt?Expires=1"
        )
    assert document.text == "记忆正文"


@pytest.mark.asyncio
async def test_rejects_non_oss_host_before_download() -> None:
    with patch.object(
        oss_document_loader, "_download", new_callable=AsyncMock
    ) as download:
        with pytest.raises(ValidationError, match="hostname is not allowed"):
            await oss_document_loader.load_document_text("https://127.0.0.1/private.txt")
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_unsupported_document_type() -> None:
    with patch.object(
        oss_document_loader,
        "_download",
        new_callable=AsyncMock,
        return_value=(b"binary", "application/octet-stream"),
    ):
        with pytest.raises(ValidationError, match="only Markdown, PDF, and TXT"):
            await oss_document_loader.load_document_text(
                "https://bucket.oss-cn-shanghai.aliyuncs.com/memory.docx"
            )


@pytest.mark.asyncio
async def test_rejects_encrypted_pdf() -> None:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    writer.write(output)
    with patch.object(
        oss_document_loader,
        "_download",
        new_callable=AsyncMock,
        return_value=(output.getvalue(), "application/pdf"),
    ):
        with pytest.raises(ValidationError, match="encrypted PDF"):
            await oss_document_loader.load_document_text(
                "https://bucket.oss-cn-shanghai.aliyuncs.com/memory.pdf"
            )
