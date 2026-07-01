"""CR-032 — Report Studio: semantic layer (catalog) + read-only query engine.

The invisible foundation CR-033/034/035 reuse. Backend-only, no migration, no UI:
a registry of what users can chart (``catalog``) and an engine that turns a saved
"spec" (JSON) into a result set (``engine.run_spec``). Read-only over the existing
financial services — it never writes a row and never trusts ``company_id`` from
the request body.
"""
from app.services.studio.catalog import get_catalog_public, validate_spec
from app.services.studio.engine import run_spec

__all__ = ["get_catalog_public", "validate_spec", "run_spec"]
