"""
Knowledge Base API routes — CRUD for KB documents and chunks.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AgencyMember, CurrentUser, TenantDB
from app.models.client import Client
from app.models.kb import KBDocument
from app.schemas.core import KBDocumentCreate, KBDocumentResponse, KBDocumentUpdate
from app.services.embeddings import ingest_document_chunks

router = APIRouter(prefix="/kb", tags=["knowledge_base"])


@router.get("/client/{client_id}", response_model=list[KBDocumentResponse])
async def list_kb_documents(client_id: UUID, token: CurrentUser, db: TenantDB):
    """List all knowledge base documents for a client."""
    # Ensure client exists
    client_result = await db.execute(select(Client).where(Client.id == client_id))
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    result = await db.execute(
        select(KBDocument)
        .where(KBDocument.client_id == client_id)
        .order_by(KBDocument.created_at.desc())
    )
    return result.scalars().all()


@router.post("/client/{client_id}", response_model=KBDocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_kb_document(
    client_id: UUID,
    data: KBDocumentCreate,
    token: AgencyMember,
    db: TenantDB,
):
    """Create a new knowledge base document and automatically generate embeddings."""
    # Ensure client exists
    client_result = await db.execute(select(Client).where(Client.id == client_id))
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    doc = KBDocument(
        client_id=client_id,
        agency_id=client.agency_id,
        title=data.title,
        content=data.content,
        doc_type=data.doc_type,
        source_url=data.source_url,
        is_active=True,
    )
    db.add(doc)
    await db.flush()  # Populate ID

    # Generate embeddings / chunks
    await ingest_document_chunks(db, doc)

    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/{doc_id}", response_model=KBDocumentResponse)
async def get_kb_document(doc_id: UUID, token: CurrentUser, db: TenantDB):
    """Get a specific knowledge base document."""
    result = await db.execute(select(KBDocument).where(KBDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


@router.patch("/{doc_id}", response_model=KBDocumentResponse)
async def update_kb_document(
    doc_id: UUID,
    data: KBDocumentUpdate,
    token: AgencyMember,
    db: TenantDB,
):
    """Update a knowledge base document, re-generating embeddings if the content changed."""
    result = await db.execute(select(KBDocument).where(KBDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    content_changed = data.content is not None and data.content != doc.content

    update_data = data.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(doc, field, val)
    await db.flush()

    if content_changed:
        # Re-generate embeddings/chunks
        await ingest_document_chunks(db, doc)

    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/{doc_id}", status_code=status.HTTP_200_OK)
async def delete_kb_document(doc_id: UUID, token: AgencyMember, db: TenantDB):
    """Delete a knowledge base document and all its chunks."""
    result = await db.execute(select(KBDocument).where(KBDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    await db.delete(doc)
    await db.commit()
    return {"status": "deleted", "document_id": str(doc_id)}
