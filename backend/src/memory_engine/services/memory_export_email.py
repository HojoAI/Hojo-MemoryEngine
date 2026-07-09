"""Export user memory data to email (H5)."""

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.user_api_errors import UserApiError
from memory_engine.integrations.email_sender import send_email
from memory_engine.schemas.memory_field import (
    MemoryDataOut,
    UserMemoryExportEmailResult,
)
from memory_engine.services import memory_data as data_service

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_export_email(email: str) -> str:
    """Validate and normalize recipient email."""
    addr = email.strip()
    if not addr or not _EMAIL_RE.match(addr):
        raise UserApiError("ILLEGAL_ARGUMENT", "邮箱格式不合法")
    return addr


async def fetch_memory_items_for_export(
    session: AsyncSession,
    ctx: RequestContext,
    memory_user_id: str,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[MemoryDataOut], int]:
    """Load memory rows using the same rules as ``list-all`` (may paginate internally)."""
    settings = get_settings()
    max_items = settings.memory_export_email_max_items

    if limit is not None:
        page = await data_service.list_all_for_user(
            session,
            ctx,
            memory_user_id,
            offset=offset,
            limit=min(limit, 1000),
        )
        return list(page.items), page.total

    items: list[MemoryDataOut] = []
    total = 0
    page_offset = offset
    page_size = 200
    while len(items) < max_items:
        page = await data_service.list_all_for_user(
            session,
            ctx,
            memory_user_id,
            offset=page_offset,
            limit=page_size,
        )
        total = page.total
        if not page.items:
            break
        items.extend(page.items)
        page_offset += len(page.items)
        if page_offset >= total or len(page.items) < page_size:
            break
    if len(items) > max_items:
        items = items[:max_items]
    return items, total


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def build_memory_export_bodies(
    *,
    memory_user_id: str,
    items: list[MemoryDataOut],
    total: int,
) -> tuple[str, str]:
    """Plain text and HTML bodies for the export email."""
    lines = [
        "您好，",
        "",
        "以下是您请求导出的记忆数据：",
        f"分区 ID：{memory_user_id}",
        f"本次导出条数：{len(items)}（库内未删总计：{total}）",
        "",
        "—— 记忆条目 ——",
        "",
    ]
    for idx, row in enumerate(items, start=1):
        lines.append(f"{idx}. {row.memory_field_name}")
        lines.append(f"   {_format_value(row.value)}")
        lines.append("")

    if not items:
        lines.append("（当前无未删除的记忆数据）")

    text = "\n".join(lines)

    rows_html = "".join(
        (
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{_html_escape(row.memory_field_name)}</td>"
            f"<td><pre style='margin:0;white-space:pre-wrap'>"
            f"{_html_escape(_format_value(row.value))}</pre></td>"
            "</tr>"
        )
        for idx, row in enumerate(items, start=1)
    )
    html = f"""<!DOCTYPE html>
<html><body>
<p>您好，</p>
<p>以下是您请求导出的记忆数据（分区 <code>{_html_escape(memory_user_id)}</code>）。</p>
<p>本次导出 <strong>{len(items)}</strong> 条（未删总计 {total}）。</p>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse">
<thead><tr><th>#</th><th>字段</th><th>值</th></tr></thead>
<tbody>
{rows_html or "<tr><td colspan='3'>（无数据）</td></tr>"}
</tbody>
</table>
</body></html>"""
    return text, html


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


async def export_memory_data_to_email(
    session: AsyncSession,
    ctx: RequestContext,
    memory_user_id: str,
    email: str,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> UserMemoryExportEmailResult:
    """Query memory data (list-all semantics) and email it to the user."""
    recipient = normalize_export_email(email)
    items, total = await fetch_memory_items_for_export(
        session,
        ctx,
        memory_user_id,
        offset=offset,
        limit=limit,
    )
    text, html = build_memory_export_bodies(
        memory_user_id=memory_user_id,
        items=items,
        total=total,
    )
    subject = "您的 Memory Engine 记忆数据导出"
    await send_email(
        to_addr=recipient,
        subject=subject,
        body_text=text,
        body_html=html,
    )
    return UserMemoryExportEmailResult(
        email=recipient,
        memory_user_id=memory_user_id,
        item_count=len(items),
        total=total,
        offset=offset,
        limit=limit if limit is not None else len(items),
    )
