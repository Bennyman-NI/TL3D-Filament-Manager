from __future__ import annotations

from dataclasses import dataclass


MANUFACTURER = "Bambu Lab"


@dataclass(frozen=True)
class CatalogueEntry:
    tray_info_material_id: str
    tray_info_variant_id: str
    filament_type: str
    detailed_filament_type: str
    color_rgba: str
    material_name: str
    color_name: str

    @property
    def catalogue_name(self) -> str:
        return f"{MANUFACTURER} {self.material_name} {self.color_name}"


@dataclass(frozen=True)
class CatalogueMatch:
    manufacturer: str
    catalogue_name: str | None
    material_name: str | None
    color_name: str | None
    status: str
    source: str
    warning: str | None = None


CATALOGUE: tuple[CatalogueEntry, ...] = (
    CatalogueEntry("GFA00", "A00-B9", "PLA", "PLA Basic", "0A2989FF", "PLA Basic", "Blue"),
    CatalogueEntry("GFA00", "A00-R3", "PLA", "PLA Basic", "F5547CFF", "PLA Basic", "Hot Pink"),
    CatalogueEntry("GFA00", "A00-G6", "PLA", "PLA Basic", "00AE42FF", "PLA Basic", "Green"),
    CatalogueEntry("GFA00", "A00-A1", "PLA", "PLA Basic", "FF9016FF", "PLA Basic", "Pumpkin Orange"),
    CatalogueEntry("GFA00", "A00-G3", "PLA", "PLA Basic", "BECF00FF", "PLA Basic", "Bright Green"),
    CatalogueEntry("GFA01", "A01-Y3", "PLA", "PLA Matte", "E8DBB7FF", "PLA Matte", "Desert Tan"),
    CatalogueEntry("GFA01", "A01-K1", "PLA", "PLA Matte", "000000FF", "PLA Matte", "Charcoal"),
    CatalogueEntry("GFA01", "A01-R2", "PLA", "PLA Matte", "B15533FF", "PLA Matte", "Terracotta"),
    CatalogueEntry("GFA06", "A06-D1", "PLA", "PLA Silk+", "C8C8C8FF", "PLA Silk+", "Silver"),
    CatalogueEntry("GFG00", "G00-D00", "PETG", "PETG Basic", "7F7E83FF", "PETG Basic", "Gray"),
    CatalogueEntry("GFG00", "G00-B00", "PETG", "PETG Basic", "001489FF", "PETG Basic", "Blue"),
    CatalogueEntry("GFG00", "G00-Y00", "PETG", "PETG Basic", "FCE300FF", "PETG Basic", "Yellow"),
    CatalogueEntry("GFG02", "G02-K0", "PETG", "PETG HF", "000000FF", "PETG HF", "Black"),
)


def resolve_catalogue(fields: dict[str, object]) -> CatalogueMatch:
    identifiers = {
        "tray_info_material_id": as_string(fields.get("tray_info_material_id")),
        "tray_info_variant_id": as_string(fields.get("tray_info_variant_id")),
        "filament_type": as_string(fields.get("filament_type")),
        "detailed_filament_type": as_string(fields.get("detailed_filament_type")),
    }
    color_rgba = color_hex(fields.get("color_rgba"))

    missing = [name for name, value in identifiers.items() if not value]
    if missing:
        return unknown(
            "identifier",
            f"Cannot resolve Bambu catalogue entry; missing required field(s): {', '.join(missing)}.",
        )

    identifier_matches = [
        entry
        for entry in CATALOGUE
        if entry.tray_info_material_id == identifiers["tray_info_material_id"]
        and entry.tray_info_variant_id == identifiers["tray_info_variant_id"]
        and entry.filament_type == identifiers["filament_type"]
        and entry.detailed_filament_type == identifiers["detailed_filament_type"]
    ]

    if len(identifier_matches) == 1:
        entry = identifier_matches[0]
        if color_rgba is None:
            return exact(entry, "identifier")
        if color_rgba == entry.color_rgba:
            return exact(entry, "identifier_and_rgba")
        return ambiguous(
            "identifier_and_rgba",
            "Bambu catalogue identifiers match "
            f"{entry.catalogue_name}, but decoded RGBA {color_rgba} differs from expected {entry.color_rgba}.",
        )
    if len(identifier_matches) > 1:
        return ambiguous("identifier", "Bambu catalogue identifiers matched more than one validated entry.")

    return unknown("identifier", "No validated Bambu catalogue entry matches the decoded identifiers.")


def exact(entry: CatalogueEntry, source: str) -> CatalogueMatch:
    return CatalogueMatch(
        manufacturer=MANUFACTURER,
        catalogue_name=entry.catalogue_name,
        material_name=entry.material_name,
        color_name=entry.color_name,
        status="exact",
        source=source,
    )


def ambiguous(source: str, warning: str) -> CatalogueMatch:
    return CatalogueMatch(
        manufacturer=MANUFACTURER,
        catalogue_name=None,
        material_name=None,
        color_name=None,
        status="ambiguous",
        source=source,
        warning=warning,
    )


def unknown(source: str, warning: str | None = None) -> CatalogueMatch:
    return CatalogueMatch(
        manufacturer=MANUFACTURER,
        catalogue_name=None,
        material_name=None,
        color_name=None,
        status="unknown",
        source=source,
        warning=warning,
    )


def as_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def color_hex(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    hex_value = value.get("hex")
    return hex_value if isinstance(hex_value, str) and hex_value else None
