"""Shared private-object storage helpers (Supabase Storage).

Generic, company-scope-checked infrastructure for storing app-generated files in
the PRIVATE ``documents`` bucket and handing out short-lived **signed** download
URLs to them. Built for CR-044 (Skills run files) but deliberately generic — CR-045
(scheduled skill runs) and any future server-generated export reuse it unchanged.

Security invariants:
  * Uploads/signs go through the Supabase **service** key (server-side only); the
    bucket is private, so an object is never publicly reachable.
  * ``signed_url`` REQUIRES a ``company_id`` and refuses to sign any path that is
    not under ``{company_id}/`` — so a caller can never mint a URL to another
    tenant's file (mirrors ``document_capture._confirmed_doc_url``). All paths in
    this codebase are written under ``{company_id}/...``.
  * Storage being unconfigured is a clean 503 (Türkçe), never a 500.
"""
from urllib.parse import quote

import httpx

from app.config import settings
from app.responses import APIError

# The single PRIVATE bucket for app-stored files (shared with document-capture).
DOCS_BUCKET = "documents"

# Short-lived by default — the URL is a transient download grant, not a durable
# link. The durable record is the ``skill_runs`` row (re-sign on demand).
DEFAULT_SIGNED_URL_TTL = 300  # seconds (5 min)


def _require_storage() -> None:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise APIError(503, "STORAGE_UNAVAILABLE", "Dosya depolama yapılandırılmadı")


def upload_bytes(path: str, data: bytes, content_type: str, *, bucket: str = DOCS_BUCKET) -> None:
    """Upload ``data`` to ``{bucket}/{path}`` (private), upserting. Raises a clean
    503/502 ``APIError`` on missing config / storage failure. ``path`` is the
    company-scoped object key (``{company_id}/...``); callers build it."""
    _require_storage()
    url = f"{settings.supabase_url}/storage/v1/object/{bucket}/{path}"
    try:
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            content=data,
            timeout=30,
        )
    except httpx.HTTPError:
        raise APIError(502, "STORAGE_ERROR", "Dosya yüklenemedi")
    if resp.status_code not in (200, 201):
        raise APIError(502, "STORAGE_ERROR", f"Dosya yüklenemedi (depolama hatası {resp.status_code})")


def signed_url(
    path: str,
    *,
    company_id,
    expires_in: int = DEFAULT_SIGNED_URL_TTL,
    bucket: str = DOCS_BUCKET,
    download_name: str | None = None,
) -> str:
    """Mint a short-lived **signed** download URL for the private object at
    ``{bucket}/{path}``.

    ``company_id`` is REQUIRED and ``path`` MUST live under ``{company_id}/`` — any
    other path raises 422, so a caller can never sign another tenant's file. Returns
    an absolute URL (``{supabase_url}/storage/v1{signedURL}``).

    ``download_name`` forces an attachment download with that filename: it appends
    ``&download=<name>`` to the URL (the same mechanism supabase-js uses), so the
    object is served ``Content-Disposition: attachment`` cross-origin — where the
    browser's ``<a download>`` attribute is otherwise ignored. Without it the file
    (esp. a PDF) would open inline in a tab instead of downloading."""
    _require_storage()
    prefix = f"{company_id}/"
    if not path or not path.startswith(prefix):
        raise APIError(422, "VALIDATION_ERROR", "Geçersiz dosya yolu", field="file_path")
    url = f"{settings.supabase_url}/storage/v1/object/sign/{bucket}/{path}"
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {settings.supabase_service_key}"},
            json={"expiresIn": int(expires_in)},
            timeout=30,
        )
    except httpx.HTTPError:
        raise APIError(502, "STORAGE_ERROR", "İndirme bağlantısı oluşturulamadı")
    if resp.status_code != 200:
        raise APIError(502, "STORAGE_ERROR", f"İndirme bağlantısı oluşturulamadı (depolama hatası {resp.status_code})")
    signed = (resp.json() or {}).get("signedURL") or (resp.json() or {}).get("signedUrl")
    if not signed:
        raise APIError(502, "STORAGE_ERROR", "İndirme bağlantısı oluşturulamadı")
    # The API returns a relative path beginning with ``/object/sign/...`` (already
    # carrying ``?token=``).
    full = signed if signed.startswith("http") else (
        f"{settings.supabase_url}/storage/v1{signed if signed.startswith('/') else '/' + signed}"
    )
    if download_name:
        sep = "&" if "?" in full else "?"
        full = f"{full}{sep}download={quote(download_name)}"
    return full
