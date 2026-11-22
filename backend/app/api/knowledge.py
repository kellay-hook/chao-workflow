from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import settings
from app.db import get_session
from app.deps import Principal, audit_context, require_tenant
from app.models import Document, DocumentChunk, KnowledgeBase
from app.permissions import authorize_tenant_request
from app.schemas import (
    ChunkOut,
    ChunkUpdate,
    DocumentOut,
    DocumentUpdate,
    KbStatsOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    SearchRequest,
    SearchResponse,
)
from app.services import model_gateway, rag, storage
from app.services.dispatch import dispatch_ingest

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/knowledge-bases", tags=["knowledge"], dependencies=[Depends(authorize_tenant_request)])

ALLOWED_SUFFIXES = {".pdf", ".docx", ".md", ".markdown", ".txt", ".xlsx", ".csv"}


def _require_editor(principal: Principal) -> None:
    if principal.is_api_key or principal.role not in {"owner", "admin", "editor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="editor required")


async def _get_kb(session: AsyncSession, tenant_id: str, kb_id: str) -> KnowledgeBase:
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb or kb.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    return kb


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_kbs(
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[KnowledgeBase]:
    result = await session.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.tenant_id == principal.tenant_id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_kb(
    payload: KnowledgeBaseCreate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeBase:
    _require_editor(principal)
    kb = KnowledgeBase(
        tenant_id=principal.tenant_id,
        name=payload.name,
        description=payload.description,
        embedding_model_profile_id=payload.embedding_model_profile_id,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
        created_by=principal.user_id,
    )
    session.add(kb)
    await session.commit()
    return kb


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_kb(
    kb_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeBase:
    return await _get_kb(session, principal.tenant_id, kb_id)


@router.patch("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_kb(
    kb_id: str,
    payload: KnowledgeBaseUpdate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeBase:
    _require_editor(principal)
    kb = await _get_kb(session, principal.tenant_id, kb_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(kb, field, value)
    await session.commit()
    return kb


@router.get("/{kb_id}/stats", response_model=KbStatsOut)
async def kb_stats(
    kb_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> KbStatsOut:
    await _get_kb(session, principal.tenant_id, kb_id)
    status_rows = await session.execute(
        select(Document.status, func.count(Document.id)).where(Document.kb_id == kb_id).group_by(Document.status)
    )
    counts = {row[0]: int(row[1]) for row in status_rows.all()}
    chunk_count = await session.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.kb_id == kb_id)
    )
    return KbStatsOut(
        documents=sum(counts.values()),
        ready=counts.get("ready", 0),
        processing=counts.get("processing", 0) + counts.get("pending", 0),
        failed=counts.get("failed", 0),
        chunks=int(chunk_count.scalar_one() or 0),
    )


@router.patch("/{kb_id}/documents/{document_id}", response_model=DocumentOut)
async def update_document(
    kb_id: str,
    document_id: str,
    payload: DocumentUpdate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Document:
    _require_editor(principal)
    await _get_kb(session, principal.tenant_id, kb_id)
    document = await session.get(Document, document_id)
    if not document or document.tenant_id != principal.tenant_id or document.kb_id != kb_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    document.metadata_json = payload.metadata_json
    await session.commit()
    return document


@router.get("/{kb_id}/documents/{document_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    kb_id: str,
    document_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[DocumentChunk]:
    await _get_kb(session, principal.tenant_id, kb_id)
    document = await session.get(Document, document_id)
    if not document or document.tenant_id != principal.tenant_id or document.kb_id != kb_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .limit(500)
    )
    return list(result.scalars().all())


@router.patch("/{kb_id}/chunks/{chunk_id}", response_model=ChunkOut)
async def update_chunk(
    kb_id: str,
    chunk_id: str,
    payload: ChunkUpdate,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> DocumentChunk:
    _require_editor(principal)
    kb = await _get_kb(session, principal.tenant_id, kb_id)
    chunk = await session.get(DocumentChunk, chunk_id)
    if not chunk or chunk.tenant_id != principal.tenant_id or chunk.kb_id != kb_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chunk not found")
    profile = await model_gateway.resolve_embedding_profile(session, principal.tenant_id, kb.embedding_model_profile_id)
    vectors, _ = await model_gateway.embed(profile, [payload.text])
    if not vectors or len(vectors[0]) != 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="embedding dimension must be 1024")
    chunk.text = payload.text
    chunk.token_count = rag.count_tokens(payload.text)
    chunk.search_text = rag.tokenize_for_search(payload.text)
    chunk.embedding = vectors[0]
    await session.commit()
    return chunk


@router.delete("/{kb_id}/chunks/{chunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chunk(
    kb_id: str,
    chunk_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    await _get_kb(session, principal.tenant_id, kb_id)
    chunk = await session.get(DocumentChunk, chunk_id)
    if chunk and chunk.tenant_id == principal.tenant_id and chunk.kb_id == kb_id:
        await session.delete(chunk)
        await session.commit()


@router.post("/{kb_id}/documents/{document_id}/reprocess", response_model=DocumentOut)
async def reprocess_document(
    kb_id: str,
    document_id: str,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Document:
    _require_editor(principal)
    await _get_kb(session, principal.tenant_id, kb_id)
    document = await session.get(Document, document_id)
    if not document or document.tenant_id != principal.tenant_id or document.kb_id != kb_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    document.status = "pending"
    document.error = ""
    await session.commit()
    dispatch_ingest(document.id, background_tasks)
    return document


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kb(
    kb_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    kb = await _get_kb(session, principal.tenant_id, kb_id)
    await session.delete(kb)
    await session.commit()


@router.get("/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> list[Document]:
    await _get_kb(session, principal.tenant_id, kb_id)
    result = await session.execute(
        select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/{kb_id}/documents/upload", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    kb_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Document:
    _require_editor(principal)
    await _get_kb(session, principal.tenant_id, kb_id)
    filename = file.filename or "upload.bin"
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的文件类型，请上传 PDF / DOCX / MD / TXT / XLSX / CSV")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件为空，请重新选择文件")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件超过 {settings.max_upload_bytes // (1024 * 1024)} MB 限制",
        )
    key = storage.new_storage_key(principal.tenant_id, kb_id, filename)
    storage.put_bytes(key, data, file.content_type or "application/octet-stream")
    document = Document(
        tenant_id=principal.tenant_id,
        kb_id=kb_id,
        filename=filename,
        mime_type=file.content_type or "application/octet-stream",
        size=len(data),
        sha256=storage.sha256_bytes(data),
        storage_key=key,
        status="pending",
        created_by=principal.user_id,
    )
    session.add(document)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="document.upload",
        resource_type="document",
        resource_id=document.id,
        detail={"filename": filename, "size": len(data)},
        **audit_context(request),
    )
    await session.commit()
    dispatch_ingest(document.id, background_tasks)
    return document


@router.post("/{kb_id}/documents/upload-url", status_code=status.HTTP_201_CREATED)
async def upload_url(
    kb_id: str,
    filename: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_editor(principal)
    await _get_kb(session, principal.tenant_id, kb_id)
    key = storage.new_storage_key(principal.tenant_id, kb_id, filename)
    document = Document(
        tenant_id=principal.tenant_id,
        kb_id=kb_id,
        filename=filename,
        mime_type="application/octet-stream",
        size=0,
        sha256="",
        storage_key=key,
        status="pending",
        created_by=principal.user_id,
    )
    session.add(document)
    await session.commit()
    url = storage.presigned_put_url(key)
    return {"document_id": document.id, "upload_url": url, "storage_key": key}


@router.post("/{kb_id}/documents/{document_id}/complete", response_model=DocumentOut)
async def complete_upload(
    kb_id: str,
    document_id: str,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> Document:
    _require_editor(principal)
    document = await session.get(Document, document_id)
    if not document or document.tenant_id != principal.tenant_id or document.kb_id != kb_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    dispatch_ingest(document.id, background_tasks)
    return document


@router.delete("/{kb_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    kb_id: str,
    document_id: str,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_editor(principal)
    document = await session.get(Document, document_id)
    if document and document.tenant_id == principal.tenant_id and document.kb_id == kb_id:
        storage.delete_object(document.storage_key)
        await session.delete(document)
        await session.commit()


@router.post("/{kb_id}/search", response_model=SearchResponse)
async def search_kb(
    kb_id: str,
    payload: SearchRequest,
    principal: Principal = Depends(require_tenant),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    await _get_kb(session, principal.tenant_id, kb_id)
    return await rag.search(
        session,
        tenant_id=principal.tenant_id,
        kb_ids=[kb_id],
        query=payload.query,
        top_k=payload.top_k,
        document_ids=payload.document_ids,
        metadata_filters=[item.model_dump() for item in payload.metadata_filters],
        rerank_mode=payload.rerank_mode,
        rerank_model_profile_id=payload.rerank_model_profile_id,
    )
