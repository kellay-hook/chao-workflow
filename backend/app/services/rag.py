from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from docx import Document as DocxDocument
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Document, DocumentChunk, KnowledgeBase
from app.schemas import Citation, SearchHit, SearchResponse
from app.services import model_gateway, storage

try:
    import tiktoken
except Exception:  # pragma: no cover
    tiktoken = None

try:
    import jieba
except Exception:  # pragma: no cover
    jieba = None

_encoding = None


def _get_encoding():
    global _encoding
    import os
    if os.environ.get("FLOWMIND_USE_TIKTOKEN") != "1":
        return None
    if _encoding is None and tiktoken is not None:
        try:
            _encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _encoding = None
    return _encoding


def count_tokens(text_value: str) -> int:
    enc = _get_encoding()
    if enc is not None:
        return len(enc.encode(text_value))
    return max(1, len(text_value) // 3)


def chunk_text(text_value: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    text_value = re.sub(r"\n{3,}", "\n\n", text_value).strip()
    if not text_value:
        return []
    enc = _get_encoding()
    if enc is not None:
        tokens = enc.encode(text_value)
        if len(tokens) <= chunk_size:
            return [text_value]
        chunks: list[str] = []
        start = 0
        step = max(1, chunk_size - max(0, overlap))
        while start < len(tokens):
            window = tokens[start : start + chunk_size]
            chunk = enc.decode(window).strip()
            if chunk:
                chunks.append(chunk)
            if start + chunk_size >= len(tokens):
                break
            start += step
        return chunks
    size = max(200, chunk_size * 3)
    step = max(100, size - overlap * 3)
    return [text_value[i : i + size].strip() for i in range(0, len(text_value), step) if text_value[i : i + size].strip()]


def tokenize_for_search(value: str) -> str:
    if jieba is not None:
        return " ".join(token.strip() for token in jieba.cut(value) if token.strip())
    return " ".join(re.findall(r"[\w\u4e00-\u9fff]+", value.lower()))


@dataclass
class Section:
    text: str
    metadata: dict[str, Any]


def _table_to_markdown(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    cleaned = [["" if cell is None else str(cell) for cell in row] for row in rows]
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    header = cleaned[0]
    body = cleaned[1:]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def parse_document(filename: str, data: bytes) -> list[Section]:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        sections = []
        for index, page in enumerate(reader.pages):
            text_value = page.extract_text() or ""
            if text_value.strip():
                sections.append(Section(text=text_value, metadata={"page": index + 1}))
        if not sections:
            raise ValueError("该 PDF 没有可提取文本，扫描版 PDF 暂不支持 OCR。")
        return sections
    if lower.endswith(".docx"):
        doc = DocxDocument(io.BytesIO(data))
        parts: list[str] = []
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                parts.append(paragraph.text)
        for table_index, table in enumerate(doc.tables):
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            if rows:
                parts.append(f"[Table {table_index + 1}]\n" + _table_to_markdown(rows))
        return [Section(text="\n\n".join(parts), metadata={})] if parts else []
    if lower.endswith(".xlsx"):
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sections: list[Section] = []
        for sheet in workbook.worksheets:
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            rows = [row for row in rows if any(cell is not None and str(cell).strip() for cell in row)]
            if not rows:
                continue
            header, body = rows[0], rows[1:]
            for start in range(0, max(1, len(body)), 50):
                block = body[start : start + 50]
                if not block:
                    continue
                table = _table_to_markdown([header] + block)
                sections.append(
                    Section(
                        text=table,
                        metadata={
                            "sheet": sheet.title,
                            "row_start": start + 2,
                            "row_end": start + 1 + len(block),
                        },
                    )
                )
        return sections
    if lower.endswith(".csv"):
        decoded = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(decoded)))
        rows = [row for row in rows if any(str(cell).strip() for cell in row)]
        if not rows:
            return []
        header, body = rows[0], rows[1:]
        sections = []
        for start in range(0, max(1, len(body)), 50):
            block = body[start : start + 50]
            if not block:
                continue
            sections.append(
                Section(
                    text=_table_to_markdown([header] + block),
                    metadata={"row_start": start + 2, "row_end": start + 1 + len(block)},
                )
            )
        return sections
    if lower.endswith((".md", ".markdown", ".txt")):
        return [Section(text=data.decode("utf-8-sig", errors="replace"), metadata={})]
    raise ValueError(f"unsupported file type: {filename}")


async def ingest_document(session: AsyncSession, document_id: str) -> None:
    doc = await session.get(Document, document_id)
    if not doc:
        raise ValueError("document not found")
    kb = await session.get(KnowledgeBase, doc.kb_id)
    if not kb:
        raise ValueError("knowledge base not found")
    doc.status = "processing"
    doc.error = ""
    await session.flush()
    try:
        data = storage.get_bytes(doc.storage_key)
        sections = parse_document(doc.filename, data)
        if not sections:
            raise ValueError("文档中没有可提取文本，请检查文件内容。")
        pending: list[Section] = []
        for section in sections:
            for piece in chunk_text(section.text, kb.chunk_size, kb.chunk_overlap):
                pending.append(Section(text=piece, metadata=dict(section.metadata)))
        if not pending:
            raise ValueError("文档中没有可用文本，请检查文件内容或重新上传。")
        profile = await model_gateway.resolve_embedding_profile(
            session, doc.tenant_id, kb.embedding_model_profile_id
        )
        vectors: list[list[float]] = []
        embedding_tokens = 0
        for start in range(0, len(pending), 64):
            batch = pending[start : start + 64]
            batch_vectors, tokens = await model_gateway.embed(profile, [item.text for item in batch])
            vectors.extend(batch_vectors)
            embedding_tokens += tokens
        if len(vectors) != len(pending):
            raise ValueError("向量化结果数量与分块数量不一致，请重试。")
        if any(len(vector) != 1024 for vector in vectors):
            raise ValueError("Embedding 维度必须为 1024，请检查知识库绑定的 Embedding 模型。")
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        for index, (section, vector) in enumerate(zip(pending, vectors, strict=True)):
            session.add(
                DocumentChunk(
                    tenant_id=doc.tenant_id,
                    kb_id=doc.kb_id,
                    document_id=doc.id,
                    chunk_index=index,
                    text=section.text,
                    token_count=count_tokens(section.text),
                    metadata_json=section.metadata,
                    embedding=vector,
                    search_text=tokenize_for_search(section.text),
                )
            )
        doc.status = "ready"
        doc.error = ""
        await session.flush()
    except Exception as exc:
        doc.status = "failed"
        message = str(exc)
        lowered = message.lower()
        if any(token in lowered for token in ("connection", "connect", "timeout", "refused", "ollama")):
            message = (
                "解析失败：无法连接 Embedding 模型服务。请检查「设置 → 模型」中的 Embedding 配置，" 
                "或确认本地 Ollama / bge-m3 正在运行。原始错误：" + message
            )
        doc.error = message[:2000]
        await session.flush()
        raise


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)


async def _vector_search_postgres(
    session: AsyncSession, tenant_id: str, kb_ids: list[str], vector: list[float], limit: int = 30
) -> list[tuple[str, float]]:
    vector_literal = "[" + ",".join(f"{value:.8f}" for value in vector) + "]"
    result = await session.execute(
        text(
            "SELECT id, 1 - (embedding <=> CAST(:vec AS vector)) AS score "
            "FROM document_chunks WHERE tenant_id = :tenant_id AND kb_id = ANY(:kb_ids) "
            "AND embedding IS NOT NULL ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :limit"
        ),
        {"vec": vector_literal, "tenant_id": tenant_id, "kb_ids": kb_ids, "limit": limit},
    )
    return [(row[0], float(row[1] or 0)) for row in result.fetchall()]


async def _text_search_postgres(
    session: AsyncSession, tenant_id: str, kb_ids: list[str], query: str, limit: int = 30
) -> list[tuple[str, float]]:
    result = await session.execute(
        text(
            "SELECT id, ts_rank_cd(to_tsvector('simple', search_text), plainto_tsquery('simple', :q)) AS score "
            "FROM document_chunks WHERE tenant_id = :tenant_id AND kb_id = ANY(:kb_ids) "
            "AND to_tsvector('simple', search_text) @@ plainto_tsquery('simple', :q) "
            "ORDER BY score DESC LIMIT :limit"
        ),
        {"q": tokenize_for_search(query), "tenant_id": tenant_id, "kb_ids": kb_ids, "limit": limit},
    )
    return [(row[0], float(row[1] or 0)) for row in result.fetchall()]


def _metadata_value(metadata: dict[str, Any], key: str) -> Any:
    current: Any = metadata
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _coerce_filter_value(expected: Any, actual: Any) -> Any:
    """Coerce a UI string value to the type stored in metadata."""
    if isinstance(actual, bool):
        if isinstance(expected, str):
            return expected.strip().lower() in {"true", "1", "yes", "on"}
        return bool(expected)
    if isinstance(actual, (int, float)):
        try:
            number = float(expected)
            return int(number) if isinstance(actual, int) else number
        except (TypeError, ValueError):
            return expected
    if isinstance(actual, str):
        return str(expected)
    return expected


def _matches_filters(metadata: dict[str, Any], filters: list[dict[str, Any]] | None) -> bool:
    for item in filters or []:
        key = str(item.get("key") or "")
        operator = str(item.get("operator") or "eq")
        expected = item.get("value")
        actual = _metadata_value(metadata, key)
        if actual is None:
            return False
        if operator == "eq":
            ok = actual == _coerce_filter_value(expected, actual)
        elif operator == "ne":
            ok = actual != _coerce_filter_value(expected, actual)
        elif operator == "contains":
            if isinstance(actual, list):
                ok = any(str(expected).lower() in str(value).lower() for value in actual)
            else:
                ok = str(expected).lower() in str(actual).lower()
        elif operator == "in":
            values = expected if isinstance(expected, list) else [expected]
            ok = actual in [_coerce_filter_value(value, actual) for value in values]
        elif operator == "gte":
            try:
                ok = float(actual) >= float(expected)
            except (TypeError, ValueError):
                ok = str(actual) >= str(expected)
        elif operator == "lte":
            try:
                ok = float(actual) <= float(expected)
            except (TypeError, ValueError):
                ok = str(actual) <= str(expected)
        else:
            ok = False
        if not ok:
            return False
    return True


def _keyword_rerank(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    query_terms = set(tokenize_for_search(query).split())

    def score(hit: SearchHit) -> float:
        text_terms = set(tokenize_for_search(hit.text).split())
        overlap = len(query_terms & text_terms) / max(1, len(query_terms))
        return hit.score * 0.65 + overlap * 0.35

    rescored = []
    for hit in hits:
        value = score(hit)
        rescored.append(hit.model_copy(update={"score": value}))
    return sorted(rescored, key=lambda item: item.score, reverse=True)


async def _llm_rerank(
    session: AsyncSession,
    tenant_id: str,
    query: str,
    hits: list[SearchHit],
    model_profile_id: str | None,
) -> list[SearchHit]:
    if len(hits) <= 1:
        return hits
    profile = await model_gateway.resolve_chat_profile(session, tenant_id, model_profile_id)
    candidates = [{"id": hit.chunk_id, "text": hit.text[:600]} for hit in hits]
    prompt = (
        "Rank the following knowledge chunks by relevance to the query. "
        "Return JSON only in the form {\"order\": [\"chunk_id\", ...]}. "
        "Include every chunk id exactly once.\n\n"
        f"Query: {query}\n\nCandidates:\n{json.dumps(candidates, ensure_ascii=False)}"
    )
    result = await model_gateway.chat(
        profile,
        [{"role": "system", "content": "You are a retrieval reranker. Return valid JSON only."}, {"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    data = json.loads(result.content)
    order = [str(item) for item in data.get("order", [])]
    by_id = {hit.chunk_id: hit for hit in hits}
    ranked = [by_id[chunk_id] for chunk_id in order if chunk_id in by_id]
    seen = {hit.chunk_id for hit in ranked}
    ranked.extend(hit for hit in hits if hit.chunk_id not in seen)
    return ranked


async def search(
    session: AsyncSession,
    *,
    tenant_id: str,
    kb_ids: list[str],
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
    metadata_filters: list[dict[str, Any]] | None = None,
    rerank_mode: str = "none",
    rerank_model_profile_id: str | None = None,
) -> SearchResponse:
    if not kb_ids:
        return SearchResponse(hits=[], query=query, rerank_mode=rerank_mode)
    count_result = await session.execute(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.kb_id.in_(kb_ids),
        )
    )
    if not count_result.scalar_one():
        return SearchResponse(hits=[], query=query, rerank_mode=rerank_mode)
    kb = await session.get(KnowledgeBase, kb_ids[0])
    profile = await model_gateway.resolve_embedding_profile(
        session, tenant_id, kb.embedding_model_profile_id if kb else None
    )
    vectors, _ = await model_gateway.embed(profile, [query])
    vector = vectors[0]
    if len(vector) != 1024:
        raise ValueError("查询向量维度必须为 1024，请检查 Embedding 模型配置。")
    # Metadata filtering happens after candidate retrieval, so widen the pool when filters exist.
    candidate_limit = max(top_k * 8, 48) if metadata_filters else max(top_k * 4, 16)
    chunks: list[DocumentChunk] = []
    scores: dict[str, float] = {}
    if settings.is_sqlite:
        stmt = select(DocumentChunk).where(
            DocumentChunk.tenant_id == tenant_id, DocumentChunk.kb_id.in_(kb_ids)
        )
        if document_ids:
            stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))
        result = await session.execute(stmt.limit(5000))
        candidates = list(result.scalars().all())
        query_terms = set(tokenize_for_search(query).split())
        scored: list[tuple[DocumentChunk, float]] = []
        for chunk in candidates:
            similarity = _cosine(chunk.embedding or [], vector)
            terms = set((chunk.search_text or "").split())
            keyword = len(query_terms & terms) / max(1, len(query_terms))
            scored.append((chunk, similarity * 0.8 + keyword * 0.2))
        scored.sort(key=lambda item: item[1], reverse=True)
        selected = scored[:candidate_limit]
        chunks = [item[0] for item in selected]
        scores = {item[0].id: item[1] for item in selected}
    else:
        vector_rows = await _vector_search_postgres(session, tenant_id, kb_ids, vector, 60)
        text_rows = await _text_search_postgres(session, tenant_id, kb_ids, query, 60)
        fused: dict[str, float] = {}
        for rank, (chunk_id, _score) in enumerate(vector_rows):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (60 + rank + 1)
        for rank, (chunk_id, _score) in enumerate(text_rows):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (60 + rank + 1)
        ranked_ids = [chunk_id for chunk_id, _score in sorted(fused.items(), key=lambda item: item[1], reverse=True)]
        if document_ids:
            result = await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.id.in_(ranked_ids[: candidate_limit * 3]),
                    DocumentChunk.document_id.in_(document_ids),
                )
            )
            by_id = {chunk.id: chunk for chunk in result.scalars().all()}
        else:
            result = await session.execute(
                select(DocumentChunk).where(DocumentChunk.id.in_(ranked_ids[: candidate_limit * 3]))
            )
            by_id = {chunk.id: chunk for chunk in result.scalars().all()}
        ranked_ids = [chunk_id for chunk_id in ranked_ids if chunk_id in by_id][:candidate_limit]
        chunks = [by_id[chunk_id] for chunk_id in ranked_ids]
        scores = fused

    doc_ids = {chunk.document_id for chunk in chunks}
    doc_result = await session.execute(select(Document).where(Document.id.in_(doc_ids))) if doc_ids else None
    docs = {doc.id: doc for doc in (doc_result.scalars().all() if doc_result else [])}
    hits: list[SearchHit] = []
    for chunk in chunks:
        doc = docs.get(chunk.document_id)
        metadata = dict(chunk.metadata_json or {})
        if doc:
            metadata = {**dict(doc.metadata_json or {}), **metadata}
        if not _matches_filters(metadata, metadata_filters):
            continue
        citation = Citation(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            title=doc.filename if doc else chunk.document_id,
            page=metadata.get("page"),
            sheet=metadata.get("sheet"),
            row_start=metadata.get("row_start"),
            row_end=metadata.get("row_end"),
        )
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                title=citation.title,
                text=chunk.text[:4000],
                score=float(scores.get(chunk.id, 0.0)),
                metadata=metadata,
                citation=citation,
            )
        )
    rerank_error = None
    if rerank_mode == "keyword":
        hits = _keyword_rerank(query, hits)
    elif rerank_mode == "llm":
        try:
            hits = await _llm_rerank(session, tenant_id, query, hits, rerank_model_profile_id)
        except Exception as exc:
            rerank_error = str(exc)
    hits = hits[:top_k]
    return SearchResponse(hits=hits, query=query, rerank_mode=rerank_mode, rerank_error=rerank_error)


def format_context(hits: list[SearchHit]) -> str:
    blocks = []
    for hit in hits:
        location = f"page {hit.citation.page}" if hit.citation.page else ""
        if hit.citation.sheet:
            location = f"sheet {hit.citation.sheet} rows {hit.citation.row_start}-{hit.citation.row_end}"
        blocks.append(f"[chunk:{hit.chunk_id}] {hit.title} {location}\n{hit.text}")
    return "\n\n".join(blocks)

