from __future__ import annotations

try:
    from .catalogue_loader import (
        FALLBACK_RECORDS as CATALOGUE,
        MANUFACTURER,
        CatalogueMatch,
        CatalogueRecord as CatalogueEntry,
        resolve_catalogue,
    )
except ImportError:  # pragma: no cover - supports direct script-style imports in tests
    from catalogue_loader import (  # type: ignore
        FALLBACK_RECORDS as CATALOGUE,
        MANUFACTURER,
        CatalogueMatch,
        CatalogueRecord as CatalogueEntry,
        resolve_catalogue,
    )
