"""Document upload router → Supabase Storage (Section 2.5, 8.1)."""
import uuid

import httpx
from fastapi import APIRouter, Depends, File, UploadFile

from app.config import settings
from app.deps import CurrentUser
from app.responses import APIError, success

router = APIRouter(prefix="/upload", tags=["uploads"])

MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}
BUCKET = "documents"


@router.post("/document")
async def upload_document(user: CurrentUser, file: UploadFile = File(...)):
    # Server-side type & size validation (Section 8.1).
    if file.content_type not in ALLOWED:
        raise APIError(
            422, "VALIDATION_ERROR",
            "Sadece PDF, JPEG veya PNG yükleyebilirsiniz (max 10MB)", field="file",
        )
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise APIError(422, "VALIDATION_ERROR", "Dosya en fazla 10MB olabilir", field="file")

    ext = ALLOWED[file.content_type]
    # Namespacing by company keeps tenant files isolated within the bucket.
    object_path = f"{user.company_id}/{uuid.uuid4()}.{ext}"

    if not settings.supabase_url or not settings.supabase_service_key:
        raise APIError(503, "STORAGE_UNAVAILABLE", "Dosya depolama yapılandırılmadı")

    url = f"{settings.supabase_url}/storage/v1/object/{BUCKET}/{object_path}"
    try:
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": file.content_type,
                "x-upsert": "true",
            },
            content=data,
            timeout=30,
        )
    except httpx.HTTPError:
        raise APIError(502, "STORAGE_ERROR", "Dosya yüklenemedi")
    if resp.status_code not in (200, 201):
        raise APIError(502, "STORAGE_ERROR", "Dosya yüklenemedi")

    public_url = f"{settings.supabase_url}/storage/v1/object/public/{BUCKET}/{object_path}"
    return success({"document_url": public_url, "path": object_path})
