"""Download text documents from controlled OSS URLs for candidate extraction."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from memory_engine.config import get_settings
from memory_engine.core.exceptions import ValidationError

_MAX_TEXT_CHARS = 200_000
_MAX_PDF_PAGES = 500
_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
_TEXT_CONTENT_TYPES = {"text/markdown", "text/plain"}


@dataclass(frozen=True)
class LoadedDocument:
    text: str
    warnings: list[str]


def _extra_allowed_hosts() -> list[str]:
    raw = get_settings().memory_candidate_oss_allowed_hosts
    return [value.strip().lower().lstrip(".") for value in raw.split(",") if value.strip()]


def _host_allowed(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    aliyun_oss = host.endswith(".aliyuncs.com") and (
        host.startswith("oss-") or ".oss-" in host
    )
    if aliyun_oss:
        return True
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in _extra_allowed_hosts())


def _validate_url(url: str) -> str:
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValidationError("INVALID_OSS_URL: only HTTPS OSS URLs are supported")
    if parsed.username or parsed.password or not _host_allowed(parsed.hostname):
        raise ValidationError("INVALID_OSS_URL: OSS hostname is not allowed")
    return value


async def _download(url: str) -> tuple[bytes, str]:
    settings = get_settings()
    max_bytes = settings.memory_candidate_oss_max_bytes
    try:
        async with httpx.AsyncClient(
            timeout=settings.memory_candidate_oss_timeout_seconds,
            follow_redirects=False,
        ) as client:
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    raise ValidationError("OSS_REDIRECT_NOT_ALLOWED: use the final signed OSS URL")
                if response.status_code >= 400:
                    raise ValidationError(
                        f"OSS_DOWNLOAD_FAILED: upstream returned HTTP {response.status_code}"
                    )
                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit() and int(content_length) > max_bytes:
                    raise ValidationError("OSS_FILE_TOO_LARGE: document exceeds download limit")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValidationError("OSS_FILE_TOO_LARGE: document exceeds download limit")
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get("content-type", "")
    except ValidationError:
        raise
    except httpx.HTTPError as exc:
        raise ValidationError("OSS_DOWNLOAD_FAILED: unable to read OSS document") from exc


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError("DOCUMENT_DECODE_FAILED: text must be UTF-8 or GB18030")


def _extract_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise ValidationError("DOCUMENT_ENCRYPTED: encrypted PDF is not supported")
        if len(reader.pages) > _MAX_PDF_PAGES:
            raise ValidationError("DOCUMENT_TOO_MANY_PAGES: PDF exceeds 500 pages")
        parts: list[str] = []
        text_length = 0
        for page in reader.pages:
            page_text = (page.extract_text() or "").strip()
            text_length += len(page_text)
            if text_length > _MAX_TEXT_CHARS:
                raise ValidationError(
                    "DOCUMENT_TEXT_TOO_LARGE: extracted text exceeds 200000 characters"
                )
            parts.append(page_text)
        return "\n\n".join(parts)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("DOCUMENT_PARSE_FAILED: unable to parse PDF") from exc


async def load_document_text(oss_url: str) -> LoadedDocument:
    """Return normalized text from one signed OSS URL without exposing the URL downstream."""
    url = _validate_url(oss_url)
    content, raw_content_type = await _download(url)
    content_type = raw_content_type.split(";", 1)[0].strip().lower()
    suffix = PurePosixPath(urlparse(url).path).suffix.lower()

    if suffix == ".pdf" or content_type == "application/pdf":
        text = await asyncio.to_thread(_extract_pdf, content)
    elif suffix in _TEXT_SUFFIXES or content_type in _TEXT_CONTENT_TYPES:
        text = _decode_text(content)
    else:
        raise ValidationError("UNSUPPORTED_DOCUMENT_TYPE: only Markdown, PDF, and TXT are supported")

    text = text.strip()
    if not text:
        raise ValidationError(
            "DOCUMENT_TEXT_EMPTY: document has no extractable text; OCR may be required"
        )
    if len(text) > _MAX_TEXT_CHARS:
        raise ValidationError("DOCUMENT_TEXT_TOO_LARGE: extracted text exceeds 200000 characters")
    return LoadedDocument(text=text, warnings=[])
