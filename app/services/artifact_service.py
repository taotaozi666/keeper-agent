"""有界完整结果保存、CSV/XLSX 导出和会话归属校验。仅用于本地单用户。"""

import asyncio
import csv
import io
import json
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact
from app.models.conversation import ConversationDeletion, utcnow


def public_file(item):
    return {
        "id": item.id,
        "name": item.name,
        "format": item.kind,
        "size": item.size,
        "row_count": item.row_count,
        "expires_at": item.expires_at.isoformat() + "Z",
    }


def export_bytes(rows, fmt):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    if not columns:
        columns = ["查询结果（0行）"]

    def cell(value):
        if value is None:
            return ""
        return (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list))
            else str(value)
        )

    if fmt == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)

        # 字段名也可能来自外部数据；防止表格软件将文本解释为公式。
        def safe(value):
            text = cell(value)
            return (
                "'" + text
                if isinstance(value, str)
                and text.lstrip().startswith(("=", "+", "-", "@"))
                else text
            )

        writer.writerow([safe(c) for c in columns])
        writer.writerows([safe(row.get(c)) for c in columns] for row in rows)
        return output.getvalue().encode("utf-8-sig")
    if fmt != "xlsx":
        raise ValueError("仅支持 xlsx 或 csv")
    # 使用 OOXML 标准库生成工作簿；文本使用 inlineStr，绝不生成公式单元格。
    output = io.BytesIO()
    sheet = [
        '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    ]
    for values in [columns, *[[row.get(c) for c in columns] for row in rows]]:
        sheet.append("<row>")
        for value in values:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sheet.append(f"<c><v>{value}</v></c>")
            else:
                text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cell(value))
                if len(text) > 32767:
                    raise ValueError("单元格超过 Excel 文本上限，请改用 CSV")
                sheet.append(
                    f'<c t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'
                )
        sheet.append("</row>")
    sheet.append("</sheetData></worksheet>")
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="查询结果" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", "".join(sheet))
    return output.getvalue()


class ArtifactService:
    MAX_ROWS = 10000
    MAX_BYTES = 10 * 1024 * 1024

    def __init__(self, engine, root=None):
        self.engine = engine
        self.root = (
            Path(root)
            if root
            else Path(__file__).resolve().parents[2] / "data" / "artifacts"
        )

    async def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(
                lambda sync: Artifact.__table__.create(sync, checkfirst=True)
            )

    def path(self, item):
        from uuid import UUID

        return self.root / f"{UUID(item.id)}.{item.kind}"

    async def save(self, cid, turn_id, kind, payload, rows, query, source_id=None):
        if len(payload) > self.MAX_BYTES:
            raise ValueError("文件超过 10 MiB 上限，请缩小查询范围")
        item = Artifact(
            id=str(uuid4()),
            conversation_id=cid,
            turn_id=turn_id,
            source_id=source_id,
            kind=kind,
            name=f"查询结果-{utcnow():%Y%m%d-%H%M%S}.{kind}",
            query=query,
            size=len(payload),
            row_count=rows,
            expires_at=utcnow() + timedelta(hours=24),
        )
        await asyncio.to_thread(self.path(item).write_bytes, payload)
        try:
            async with AsyncSession(self.engine, expire_on_commit=False) as session:
                session.add(item)
                await session.commit()
        except BaseException:
            self.path(item).unlink(missing_ok=True)
            raise
        return item

    async def save_result(self, cid, turn_id, rows, query):
        await self.cleanup_expired()
        if len(rows) > self.MAX_ROWS:
            raise ValueError("结果超过 10000 行，无法完整保存导出，请缩小查询范围")
        payload = json.dumps(
            rows, ensure_ascii=False, default=str, allow_nan=False
        ).encode("utf-8")
        return await self.save(cid, turn_id, "json", payload, len(rows), query)

    async def cleanup_expired(self):
        async with AsyncSession(self.engine) as session:
            items = (
                await session.scalars(
                    select(Artifact).where(Artifact.expires_at <= utcnow()).limit(200)
                )
            ).all()
            for item in items:
                try:
                    await asyncio.to_thread(self.path(item).unlink, missing_ok=True)
                except OSError:
                    continue
                await session.delete(item)
            await session.commit()

    async def recent_results(self, cid):
        async with AsyncSession(self.engine) as session:
            items = (
                await session.scalars(
                    select(Artifact)
                    .where(
                        Artifact.conversation_id == cid,
                        Artifact.kind == "json",
                        Artifact.expires_at > utcnow(),
                    )
                    .order_by(Artifact.created_at.desc(), Artifact.id.desc())
                    .limit(8)
                )
            ).all()
            return [
                {"query_result_id": i.id, "query": i.query, "row_count": i.row_count}
                for i in items
            ]

    async def get(self, cid, file_id):
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            item = await session.get(Artifact, file_id)
            if (
                not item
                or item.conversation_id != cid
                or await session.get(ConversationDeletion, cid)
            ):
                raise FileNotFoundError("文件不存在或不属于当前会话")
            if item.expires_at <= utcnow():
                raise TimeoutError("文件已过期，请重新查询或导出")
            if not self.path(item).is_file():
                raise FileNotFoundError("文件已丢失，请重新查询")
            return item

    async def export(self, cid, turn_id, result_id, fmt):
        item = await self.get(cid, result_id)
        if item.kind != "json":
            raise ValueError("必须提供查询结果 ID")
        rows = json.loads(
            await asyncio.to_thread(self.path(item).read_text, encoding="utf-8")
        )
        payload = await asyncio.to_thread(export_bytes, rows, fmt)
        return await self.save(
            cid, turn_id, fmt, payload, len(rows), item.query, item.id
        )
