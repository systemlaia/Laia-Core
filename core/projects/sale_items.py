import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional


SALE_STATUSES = {
    "draft",
    "photos_in_progress",
    "photos_ready",
    "listing_ready",
    "listed",
    "reserved",
    "sold",
    "withdrawn",
    "archived",
    "unlisted",
    "pending_pickup",
}
LISTING_STATUSES = {
    "draft", "ready", "listed", "paused", "needs_update", "offer_received",
    "pending_pickup", "sold", "cancelled", "expired", "removed",
}
OFFER_STATUSES = {"received", "countered", "accepted", "declined", "expired", "ghosted", "completed"}
LISTING_EVENTS = {
    "drafted", "listed", "edited", "price_changed", "offer_received",
    "message_received", "pending_pickup", "sold", "removed", "renewed", "reposted",
}
CHANNEL_PRESETS = {
    "facebook_marketplace": {
        "channel_id": "facebook_marketplace", "display_name": "Facebook Marketplace",
        "listing_type": "local", "supports_url": True, "supports_local_pickup": True,
        "supports_shipping": False, "notes": "Local-first; supports photos, video, messages, and offers.",
    },
    "craigslist": {
        "channel_id": "craigslist", "display_name": "Craigslist",
        "listing_type": "local", "supports_url": True, "supports_local_pickup": True,
        "supports_shipping": False, "notes": "Local classified with a plain-text description and email relay.",
    },
    "offerup": {
        "channel_id": "offerup", "display_name": "OfferUp",
        "listing_type": "local", "supports_url": True, "supports_local_pickup": True,
        "supports_shipping": False, "notes": "Local-first app listing.",
    },
    "nextdoor": {
        "channel_id": "nextdoor", "display_name": "Nextdoor",
        "listing_type": "local", "supports_url": True, "supports_local_pickup": True,
        "supports_shipping": False, "notes": "Neighborhood-local trust channel.",
    },
    "ebay": {
        "channel_id": "ebay", "display_name": "eBay",
        "listing_type": "marketplace", "supports_url": True, "supports_local_pickup": True,
        "supports_shipping": True, "notes": "Wider market with shipping and local pickup.",
    },
    "discogs": {
        "channel_id": "discogs", "display_name": "Discogs",
        "listing_type": "specialist", "supports_url": True, "supports_local_pickup": False,
        "supports_shipping": True, "notes": "Records and music-media specialist.",
    },
    "reverb": {
        "channel_id": "reverb", "display_name": "Reverb",
        "listing_type": "specialist", "supports_url": True, "supports_local_pickup": True,
        "supports_shipping": True, "notes": "Audio and music-gear specialist.",
    },
    "other": {
        "channel_id": "other", "display_name": "Other",
        "listing_type": "other", "supports_url": True, "supports_local_pickup": True,
        "supports_shipping": True, "notes": "",
    },
}
ACTIVE_LISTING_STATUSES = LISTING_STATUSES - {"sold", "cancelled", "expired", "removed"}
CONDITION_VALUES = {"unassessed", "parts_only", "poor", "fair", "good", "very_good", "excellent", "new"}
FUNCTIONAL_STATES = {"untested", "working", "partially_working", "not_working", "unknown", "not_applicable"}
EDIT_STATUSES = {"unedited", "editing", "edited", "exported", "approved", "rejected"}
PHOTO_ROLES = {
    "hero",
    "front",
    "rear",
    "left",
    "right",
    "top",
    "controls",
    "controls_detail",
    "ports",
    "model_label",
    "serial_label",
    "accessories",
    "defect",
    "detail",
    "other",
    "cover_front",
    "cover_back",
    "vinyl_a",
    "vinyl_b",
    "label_a",
    "label_b",
    "spine",
    "inner_sleeve",
    "matrix",
}
UNIQUE_ROLES = PHOTO_ROLES - {"detail", "other", "defect", "accessories"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".raf", ".raw", ".dng"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}


def display_functional_status(value: str) -> str:
    return "not applicable" if value == "not_applicable" else str(value or "")


def sale_item_category(item: Optional[dict]) -> str:
    return str((item or {}).get("category", "")).strip().lower()


def verification_profile_for_item(item: Optional[dict]) -> str:
    category = sale_item_category(item)
    if category == "records":
        return "records"
    if category == "electronics" or item is None:
        return "electronics"
    return "generic"


def registry_module():
    try:
        from projects import registry
    except (ImportError, ModuleNotFoundError):
        from core.projects import registry
    return registry


def utc_now() -> str:
    return registry_module().utc_now()


def project_id(identifier: str) -> str:
    return registry_module().find_project(identifier)


def project_folder(identifier: str) -> Path:
    return registry_module().project_folder(project_id(identifier))


def sale_item_path(identifier: str) -> Path:
    return project_folder(identifier) / "sale_item.json"


def sale_item_markdown_path(identifier: str) -> Path:
    return project_folder(identifier) / "sale_item.md"


def photo_edit_root(identifier: str) -> Path:
    return project_folder(identifier) / "photo_edit"


def edit_manifest_path(identifier: str) -> Path:
    return photo_edit_root(identifier) / "edit_manifest.json"


def edit_report_path(identifier: str) -> Path:
    return photo_edit_root(identifier) / "edit_report.md"


def edit_history_path(identifier: str) -> Path:
    return photo_edit_root(identifier) / "history.json"


def listing_root(identifier: str) -> Path:
    return project_folder(identifier) / "listing"


def read_json(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON: {path}: {exc}")


def write_json(path: Path, data) -> None:
    registry_module().write_json(path, data)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decimal_value(value, field: str) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid decimal for {field}: {value}")


def decimal_text(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(value, ".2f")


def normalize_channel(channel: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(channel or "").strip().lower()).strip("_")
    aliases = {
        "facebook": "facebook_marketplace", "facebook_marketplace": "facebook_marketplace",
        "fb_marketplace": "facebook_marketplace", "craigs_list": "craigslist",
        "offer_up": "offerup", "e_bay": "ebay",
    }
    return aliases.get(value, value if value in CHANNEL_PRESETS else "other")


def channel_preset(channel: str) -> dict:
    channel_id = normalize_channel(channel)
    preset = dict(CHANNEL_PRESETS[channel_id])
    if channel_id == "other" and str(channel or "").strip():
        preset["display_name"] = str(channel).strip()
    return preset


def timestamp_date(value: str) -> str:
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    return "".join(match.groups()) if match else utc_now()[:10].replace("-", "")


def listing_slug(channel_id: str) -> str:
    return channel_id.replace("_", "-")


def append_listing_event(item: dict, listing: dict, event: str, note: str = "", at: Optional[str] = None) -> dict:
    if event not in LISTING_EVENTS:
        raise ValueError(f"Invalid listing event: {event}")
    row = {"event": event, "channel": listing["channel"], "at": at or utc_now(), "note": note}
    listing.setdefault("history", []).append(row)
    item.setdefault("listing_history", []).append({**row, "listing_id": listing["listing_id"]})
    return row


def migrate_sale_item(item: dict) -> dict:
    if not item:
        return item
    item.setdefault("listings", [])
    item.setdefault("offers", [])
    item.setdefault("listing_history", [])
    sale = item.setdefault("sale", {})
    sale.setdefault("channels", [])
    for legacy in sale["channels"]:
        if not isinstance(legacy, dict):
            legacy = {"channel": str(legacy)}
        preset = channel_preset(legacy.get("channel", "other"))
        posted_at = legacy.get("listed_at") or sale.get("listed_at") or item.get("updated_at") or utc_now()
        url = legacy.get("url", "")
        existing = next(
            (
                row for row in item["listings"]
                if row.get("channel") == preset["channel_id"]
                and (not url or row.get("url", "") == url)
            ),
            None,
        )
        if existing:
            continue
        base = f"{listing_slug(preset['channel_id'])}-{timestamp_date(posted_at)}"
        listing_id = base
        suffix = 2
        ids = {row.get("listing_id") for row in item["listings"]}
        while listing_id in ids:
            listing_id = f"{base}-{suffix}"
            suffix += 1
        item["listings"].append(
            {
                "listing_id": listing_id,
                "channel": preset["channel_id"],
                "channel_name": preset["display_name"],
                "status": "listed",
                "url": url,
                "asking_price": item.get("pricing", {}).get("asking_price"),
                "posted_at": posted_at,
                "updated_at": posted_at,
                "title": item.get("title", ""),
                "description_path": f"listing/channel/{preset['channel_id']}/description.txt",
                "asset_package_path": f"listing/channel/{preset['channel_id']}",
                "note": legacy.get("note", ""),
                "history": [{"event": "listed", "channel": preset["channel_id"], "at": posted_at, "note": legacy.get("note", "")}],
            }
        )
    summarize_sale_status(item)
    return item


def summarize_sale_status(item: dict) -> str:
    sale = item.setdefault("sale", {})
    if sale.get("sold_at") or sale.get("status") == "sold" or any(row.get("status") == "sold" for row in item.get("listings", [])):
        status = "sold"
    elif any(row.get("status") == "pending_pickup" for row in item.get("listings", [])):
        status = "pending_pickup"
    elif any(row.get("status") in {"listed", "offer_received"} for row in item.get("listings", [])):
        status = "listed"
    elif item.get("listings") and all(row.get("status") in {"removed", "cancelled", "expired"} for row in item["listings"]):
        status = "listing_ready" if item.get("pricing", {}).get("asking_price") else "unlisted"
    else:
        status = sale.get("status") or "draft"
    sale["status"] = status
    item["sale_status"] = status
    return status


def default_sale_item(project: dict, source: dict, **values) -> dict:
    now = utc_now()
    title = values.get("title") or project.get("name") or project.get("project_id")
    return {
        "record_type": "laia.sale_item",
        "record_version": "0.1",
        "item_id": project["project_id"],
        "project_id": project["project_id"],
        "title": title,
        "manufacturer": values.get("manufacturer") or "",
        "model": values.get("model") or "",
        "category": values.get("category") or "",
        "subcategory": "",
        "description": "",
        "condition": {
            "overall": "unassessed",
            "cosmetic": "",
            "functional": "untested",
            "known_defects": [],
            "condition_notes": "",
        },
        "identifiers": {"serial_number": "", "sku": "", "barcode": ""},
        "included_items": [],
        "missing_items": [],
        "dimensions": {},
        "weight": {},
        "source": source,
        "pricing": {
            "currency": "USD",
            "asking_price": None,
            "minimum_price": None,
            "estimated_value": None,
            "pricing_notes": "",
        },
        "sale": {
            "status": "draft",
            "channels": [],
            "listed_at": None,
            "sold_at": None,
            "sale_price": None,
            "fees": None,
            "shipping_cost": None,
            "net_proceeds": None,
            "buyer": "",
            "notes": "",
        },
        "sale_status": "draft",
        "listings": [],
        "offers": [],
        "listing_history": [],
        "created_at": now,
        "updated_at": now,
    }


def derive_source(project_identifier: str, cohort_id: Optional[str] = None) -> dict:
    registry = registry_module()
    pid = registry.find_project(project_identifier)
    cohorts = registry.project_cohorts(pid)
    if cohort_id:
        cohorts = [item for item in cohorts if item.get("cohort_id") == cohort_id]
    ready = [item for item in cohorts if item.get("cohort_status") == "ready"]
    selected = (ready or cohorts)[0] if (ready or cohorts) else {}
    return {
        "packet_id": selected.get("packet_id", ""),
        "cohort_id": selected.get("cohort_id", ""),
        "cohort_export_path": selected.get("artifact_path", ""),
    }


def sale_item_markdown(item: dict) -> str:
    condition = item.get("condition", {})
    pricing = item.get("pricing", {})
    sale = item.get("sale", {})
    source = item.get("source", {})
    return "\n".join(
        [
            f"# Sale Item: {item.get('title', '')}",
            "",
            f"- Item ID: {item.get('item_id', '')}",
            f"- Manufacturer: {item.get('manufacturer', '')}",
            f"- Model: {item.get('model', '')}",
            f"- Category: {item.get('category', '')}",
            f"- Condition: {condition.get('overall', '')}",
            f"- Functional: {display_functional_status(condition.get('functional', ''))}",
            f"- Sale status: {sale.get('status', '')}",
            f"- Asking price: {pricing.get('asking_price')}",
            "",
            "## Source",
            "",
            f"- Packet: {source.get('packet_id', '')}",
            f"- Cohort: {source.get('cohort_id', '')}",
            f"- Cohort export: {source.get('cohort_export_path', '')}",
            "",
            "## Description",
            "",
            item.get("description", ""),
            "",
        ]
    )


def write_sale_item(identifier: str, item: dict) -> dict:
    migrate_sale_item(item)
    item["updated_at"] = utc_now()
    write_json(sale_item_path(identifier), item)
    sale_item_markdown_path(identifier).write_text(sale_item_markdown(item), encoding="utf-8")
    return item


def load_sale_item(identifier: str) -> dict:
    path = sale_item_path(identifier)
    if not path.exists():
        raise FileNotFoundError(f"Sale item not initialized: {project_id(identifier)}")
    return migrate_sale_item(read_json(path))


def init_sale_item(
    identifier: str,
    title: Optional[str] = None,
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    cohort: Optional[str] = None,
    packet: Optional[str] = None,
    cohort_export: Optional[str] = None,
) -> dict:
    registry = registry_module()
    pid = registry.find_project(identifier)
    existing = read_json(sale_item_path(pid), {})
    if existing:
        return existing
    source = derive_source(pid, cohort)
    if cohort is not None:
        source["cohort_id"] = cohort
    if packet is not None:
        source["packet_id"] = packet
    if cohort_export is not None:
        source["cohort_export_path"] = str(Path(cohort_export).expanduser())
    item = default_sale_item(
        registry.load_project(pid),
        source,
        title=title,
        manufacturer=manufacturer,
        model=model,
        category=category,
    )
    return write_sale_item(pid, item)


def append_unique(values: list, value: Optional[str]) -> None:
    if value and value not in values:
        values.append(value)


def update_sale_item(identifier: str, **updates) -> dict:
    item = load_sale_item(identifier)
    for key in ["title", "manufacturer", "model", "category", "subcategory", "description"]:
        if updates.get(key) is not None:
            item[key] = updates[key]
    condition = item["condition"]
    if updates.get("condition") is not None:
        if updates["condition"] not in CONDITION_VALUES:
            raise ValueError(f"Invalid condition: {updates['condition']}")
        condition["overall"] = updates["condition"]
    if updates.get("functional_status") is not None:
        if updates["functional_status"] not in FUNCTIONAL_STATES:
            raise ValueError(f"Invalid functional status: {updates['functional_status']}")
        condition["functional"] = updates["functional_status"]
    if updates.get("condition_note") is not None:
        condition["condition_notes"] = updates["condition_note"]
    append_unique(condition["known_defects"], updates.get("known_defect"))
    append_unique(item["included_items"], updates.get("included_item"))
    append_unique(item["missing_items"], updates.get("missing_item"))
    if updates.get("serial_number") is not None:
        item["identifiers"]["serial_number"] = updates["serial_number"]
    pricing = item["pricing"]
    for key in ["asking_price", "minimum_price", "estimated_value"]:
        if updates.get(key) is not None:
            pricing[key] = decimal_text(decimal_value(updates[key], key))
    if updates.get("pricing_note") is not None:
        pricing["pricing_notes"] = updates["pricing_note"]
    record_metadata = item.setdefault("record_metadata", {})
    record_field_map = {
        "record_artist": "artist",
        "record_title": "title",
        "record_label": "record_label",
        "catalog_number": "catalog_number",
        "media_condition": "media_condition",
        "sleeve_condition": "sleeve_condition",
        "grading_note": "grading_note",
    }
    for update_key, metadata_key in record_field_map.items():
        if updates.get(update_key) is not None:
            record_metadata[metadata_key] = updates[update_key]
    if updates.get("status") is not None:
        if updates["status"] not in SALE_STATUSES:
            raise ValueError(f"Invalid sale status: {updates['status']}")
        item["sale"]["status"] = updates["status"]
    return write_sale_item(identifier, item)


def record_listing(identifier: str, channel: str, url: str = "", asking_price=None, note: str = "") -> dict:
    item = load_sale_item(identifier)
    now = utc_now()
    preset = channel_preset(channel)
    price = (
        decimal_text(decimal_value(asking_price, "asking price"))
        if asking_price is not None
        else item.get("pricing", {}).get("asking_price")
    )
    existing_listing = next(
        (
            row for row in item["listings"]
            if row.get("channel") == preset["channel_id"] and row.get("status") in ACTIVE_LISTING_STATUSES
        ),
        None,
    )
    if existing_listing:
        old_price = existing_listing.get("asking_price")
        existing_listing.update(
            {
                "channel_name": preset["display_name"], "status": "listed",
                "url": url or existing_listing.get("url", ""), "asking_price": price,
                "updated_at": now, "title": item.get("title", ""),
                "description_path": f"listing/channel/{preset['channel_id']}/description.txt",
                "asset_package_path": f"listing/channel/{preset['channel_id']}",
                "note": note or existing_listing.get("note", ""),
            }
        )
        append_listing_event(
            item, existing_listing, "price_changed" if old_price != price else "listed", note, now
        )
        listing = existing_listing
    else:
        base = f"{listing_slug(preset['channel_id'])}-{timestamp_date(now)}"
        listing_id = base
        suffix = 2
        ids = {row.get("listing_id") for row in item["listings"]}
        while listing_id in ids:
            listing_id = f"{base}-{suffix}"
            suffix += 1
        listing = {
            "listing_id": listing_id, "channel": preset["channel_id"],
            "channel_name": preset["display_name"], "status": "listed", "url": url,
            "asking_price": price, "posted_at": now, "updated_at": now,
            "title": item.get("title", ""),
            "description_path": f"listing/channel/{preset['channel_id']}/description.txt",
            "asset_package_path": f"listing/channel/{preset['channel_id']}",
            "note": note, "history": [],
        }
        item["listings"].append(listing)
        append_listing_event(item, listing, "listed", note, now)
    entry = {"channel": preset["display_name"], "url": url, "listed_at": now, "note": note}
    channels = item["sale"].setdefault("channels", [])
    existing = next(
        (value for value in channels if normalize_channel(value.get("channel", "")) == preset["channel_id"]),
        None,
    )
    if existing:
        existing.update(entry)
    else:
        channels.append(entry)
    if asking_price is not None:
        item["pricing"]["asking_price"] = price
    item["sale"]["listed_at"] = now
    if note:
        item["sale"]["notes"] = note
    summarize_sale_status(item)
    return write_sale_item(identifier, item)


def find_listing(item: dict, listing_id: str) -> dict:
    exact = next((row for row in item.get("listings", []) if row.get("listing_id") == listing_id), None)
    if exact:
        return exact
    channel_id = normalize_channel(listing_id)
    matches = [
        row for row in item.get("listings", [])
        if row.get("channel") == channel_id and row.get("status") in ACTIVE_LISTING_STATUSES
    ]
    if matches:
        return sorted(matches, key=lambda row: row.get("updated_at", ""), reverse=True)[0]
    raise ValueError(f"Listing not found: {listing_id}")


def update_listing(identifier: str, listing_id: str, status=None, url=None, asking_price=None, title=None, note=None, event=None) -> dict:
    item = load_sale_item(identifier)
    listing = find_listing(item, listing_id)
    now = utc_now()
    old_price = listing.get("asking_price")
    if status is not None:
        if status not in LISTING_STATUSES:
            raise ValueError(f"Invalid listing status: {status}")
        listing["status"] = status
    if url is not None:
        listing["url"] = url
    if asking_price is not None:
        listing["asking_price"] = decimal_text(decimal_value(asking_price, "asking price"))
    if title is not None:
        listing["title"] = title
    if note is not None:
        listing["note"] = note
    listing["updated_at"] = now
    derived_event = event
    if not derived_event:
        if listing.get("asking_price") != old_price:
            derived_event = "price_changed"
        elif status in {"listed", "pending_pickup", "sold", "removed"}:
            derived_event = status
        else:
            derived_event = "edited"
    append_listing_event(item, listing, derived_event, note or "", now)
    summarize_sale_status(item)
    return write_sale_item(identifier, item)


def add_listing_note(identifier: str, listing_id: str, note: str) -> dict:
    return update_listing(identifier, listing_id, note=note, event="edited")


def record_offer(identifier: str, listing_id: str, amount, buyer="", note="", status="received") -> dict:
    if status not in OFFER_STATUSES:
        raise ValueError(f"Invalid offer status: {status}")
    item = load_sale_item(identifier)
    listing = find_listing(item, listing_id)
    now = utc_now()
    date = timestamp_date(now)
    sequence = 1 + sum(1 for row in item["offers"] if str(row.get("offer_id", "")).startswith(f"offer-{date}-"))
    offer = {
        "offer_id": f"offer-{date}-{sequence:03d}",
        "listing_id": listing["listing_id"], "channel": listing["channel"],
        "amount": decimal_text(decimal_value(amount, "offer amount")), "buyer": buyer,
        "status": status, "received_at": now, "updated_at": now, "note": note,
        "history": [{"status": status, "at": now, "note": note}],
    }
    item["offers"].append(offer)
    if status == "accepted":
        listing["status"] = "pending_pickup"
    append_listing_event(item, listing, "offer_received", note, now)
    summarize_sale_status(item)
    write_sale_item(identifier, item)
    return offer


def update_offer(identifier: str, offer_id: str, status: str, note: str = "") -> dict:
    if status not in OFFER_STATUSES:
        raise ValueError(f"Invalid offer status: {status}")
    item = load_sale_item(identifier)
    offer = next((row for row in item["offers"] if row.get("offer_id") == offer_id), None)
    if not offer:
        raise ValueError(f"Offer not found: {offer_id}")
    now = utc_now()
    offer.update({"status": status, "updated_at": now})
    if note:
        offer["note"] = note
    offer.setdefault("history", []).append({"status": status, "at": now, "note": note})
    listing = find_listing(item, offer["listing_id"])
    if status == "accepted":
        listing["status"] = "pending_pickup"
        append_listing_event(item, listing, "pending_pickup", note, now)
    elif status == "completed":
        listing["status"] = "sold"
        append_listing_event(item, listing, "sold", note, now)
    summarize_sale_status(item)
    write_sale_item(identifier, item)
    return offer


def record_sale(identifier: str, channel: str, sale_price, fees=None, shipping=None, buyer="", note="") -> dict:
    item = load_sale_item(identifier)
    price = decimal_value(sale_price, "sale price")
    if price is None:
        raise ValueError("Sale price is required.")
    fees_value = decimal_value(fees, "fees") or Decimal("0.00")
    shipping_value = decimal_value(shipping, "shipping") or Decimal("0.00")
    sale = item["sale"]
    sale.update(
        {
            "status": "sold",
            "sold_at": utc_now(),
            "sale_price": decimal_text(price),
            "fees": decimal_text(fees_value),
            "shipping_cost": decimal_text(shipping_value),
            "net_proceeds": decimal_text(price - fees_value - shipping_value),
            "buyer": buyer,
            "notes": note,
        }
    )
    if channel:
        append_unique(sale.setdefault("sold_channels", []), channel)
    return write_sale_item(identifier, item)


def source_images(source: Path) -> list[Path]:
    return sorted(
        [item for item in source.rglob("*") if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS],
        key=lambda item: str(item.relative_to(source)).lower(),
    )


def source_id(packet_id: str, cohort_id: str) -> str:
    slug = registry_module().project_slug
    return f"{slug(packet_id)}__{slug(cohort_id)}"


def migrate_edit_manifest(manifest: dict) -> dict:
    if not manifest:
        return manifest
    packet_id = str(manifest.get("source_packet_id", ""))
    cohort_id = str(manifest.get("source_cohort_id", ""))
    export_path = str(manifest.get("source_export_path", ""))
    if not isinstance(manifest.get("sources"), list):
        manifest["sources"] = [
            {
                "source_id": source_id(packet_id, cohort_id),
                "packet_id": packet_id,
                "cohort_id": cohort_id,
                "cohort_export_path": export_path,
                "file_count": len(manifest.get("images", [])),
                "added_at": manifest.get("prepared_at", ""),
                "status": "active",
                "note": "",
                "import_batch_id": "batch-initial",
            }
        ]
    default_source = manifest["sources"][0] if manifest["sources"] else {}
    source_by_id = {item.get("source_id"): item for item in manifest["sources"]}
    for image in manifest.get("images", []):
        sid = image.get("source_id") or default_source.get("source_id", "")
        source = source_by_id.get(sid, default_source)
        work_filename = image.get("work_filename") or image.get("filename") or Path(image.get("work_path", "")).name
        image.setdefault("source_id", sid)
        image.setdefault("source_packet_id", source.get("packet_id", packet_id))
        image.setdefault("source_cohort_id", source.get("cohort_id", cohort_id))
        image.setdefault("source_export_path", source.get("cohort_export_path", export_path))
        image.setdefault("source_filename", Path(image.get("source_path", "")).name or work_filename)
        image.setdefault("work_filename", work_filename)
        image.setdefault("filename", work_filename)
        image.setdefault("import_batch_id", source.get("import_batch_id", "batch-initial"))
        image.setdefault("added_at", source.get("added_at", manifest.get("prepared_at", "")))
        image["tags"] = normalize_tags(image.get("tags", []))
    manifest["image_count"] = len(manifest.get("images", []))
    return manifest


def load_edit_manifest(identifier: str) -> dict:
    path = edit_manifest_path(identifier)
    if not path.exists():
        raise FileNotFoundError(f"Photo edit workspace not prepared: {project_id(identifier)}")
    return migrate_edit_manifest(read_json(path))


def save_edit_manifest(identifier: str, manifest: dict) -> dict:
    manifest["updated_at"] = utc_now()
    write_json(edit_manifest_path(identifier), manifest)
    history = {"project_id": manifest["project_id"], "history": manifest.get("history", [])}
    write_json(edit_history_path(identifier), history)
    return manifest


def prepare_photo_edit(identifier: str, cohort: Optional[str] = None, source: Optional[str] = None, copy_mode="copy") -> dict:
    if copy_mode not in {"copy", "hardlink"}:
        raise ValueError(f"Invalid copy mode: {copy_mode}")
    pid = project_id(identifier)
    item = load_sale_item(pid)
    derived = derive_source(pid, cohort)
    source_path = Path(source or derived.get("cohort_export_path") or item["source"].get("cohort_export_path", "")).expanduser()
    images_root = source_path / "files" if (source_path / "files").is_dir() else source_path
    if not images_root.is_dir():
        raise FileNotFoundError(f"Cohort export image source not found: {images_root}")
    inputs = source_images(images_root)
    if not inputs:
        raise FileNotFoundError(f"No source images found: {images_root}")
    names = [path.name for path in inputs]
    if len(names) != len(set(name.lower() for name in names)):
        raise ValueError("Cohort export contains duplicate filenames; workspace would be ambiguous.")
    root = photo_edit_root(pid)
    work = root / "work"
    exports = root / "exports"
    rejected = root / "rejected"
    for folder in [work, exports, rejected]:
        folder.mkdir(parents=True, exist_ok=True)
    existing_manifest = migrate_edit_manifest(read_json(edit_manifest_path(pid), {}))
    existing_by_name = {image.get("filename"): image for image in existing_manifest.get("images", [])}
    image_rows = []
    copied = 0
    existing = 0
    packet_id = derived.get("packet_id") or item["source"].get("packet_id", "")
    cohort_id = cohort or derived.get("cohort_id") or item["source"].get("cohort_id", "")
    sid = source_id(packet_id, cohort_id)
    now = utc_now()
    for src in inputs:
        target = work / src.name
        checksum = file_sha256(src)
        if target.exists():
            if file_sha256(target) != checksum:
                raise ValueError(f"Workspace file conflicts with source: {target}")
            existing += 1
        else:
            if copy_mode == "hardlink":
                os.link(src, target)
            else:
                shutil.copy2(src, target)
            copied += 1
        old = existing_by_name.get(src.name, {})
        image_rows.append(
            {
                "filename": src.name,
                "source_id": sid,
                "source_packet_id": packet_id,
                "source_cohort_id": cohort_id,
                "source_export_path": str(source_path),
                "source_filename": src.name,
                "work_filename": src.name,
                "import_batch_id": old.get("import_batch_id", "batch-initial"),
                "added_at": old.get("added_at", now),
                "source_path": str(src),
                "source_sha256": checksum,
                "work_path": str(target),
                "xmp_path": str(target) + ".xmp",
                "export_path": old.get("export_path"),
                "export_sha256": old.get("export_sha256", ""),
                "dimensions": old.get("dimensions", {}),
                "role": old.get("role", ""),
                "tags": normalize_tags(old.get("tags", [])),
                "edit_status": old.get("edit_status", "unedited"),
                "review_status": old.get("review_status", "unreviewed"),
                "note": old.get("note", ""),
            }
        )
    history = existing_manifest.get("history", [])
    history.append({"event": "prepared", "timestamp": now, "copied": copied, "existing": existing, "copy_mode": copy_mode})
    manifest = {
        "record_type": "laia.photo_edit",
        "record_version": "0.1",
        "project_id": pid,
        "source_packet_id": packet_id,
        "source_cohort_id": cohort_id,
        "source_export_path": str(source_path),
        "sources": existing_manifest.get("sources") or [
            {
                "source_id": sid,
                "packet_id": packet_id,
                "cohort_id": cohort_id,
                "cohort_export_path": str(source_path),
                "file_count": len(image_rows),
                "added_at": existing_manifest.get("prepared_at") or now,
                "status": "active",
                "note": "",
                "import_batch_id": "batch-initial",
            }
        ],
        "workspace_path": str(work),
        "export_path": str(exports),
        "editor": "darktable",
        "status": existing_manifest.get("status", "prepared"),
        "image_count": len(image_rows),
        "edited_count": 0,
        "exported_count": 0,
        "approved_count": 0,
        "prepared_at": existing_manifest.get("prepared_at") or now,
        "opened_at": existing_manifest.get("opened_at"),
        "reviewed_at": existing_manifest.get("reviewed_at"),
        "completed_at": existing_manifest.get("completed_at"),
        "images": image_rows,
        "history": history,
    }
    refresh_edit_counts(manifest)
    save_edit_manifest(pid, manifest)
    update_sale_item(pid, status="photos_in_progress")
    write_edit_report(pid, manifest, [])
    return {"manifest": manifest, "copied": copied, "existing": existing}


def resolve_add_source(packet: Optional[str], cohort: Optional[str], source: Optional[str]) -> dict:
    if packet and cohort:
        try:
            from photo_ingest.cohorts import latest_cohort_export_path, read_cohort, resolve_photo_packet
        except (ImportError, ModuleNotFoundError):
            from core.photo_ingest.cohorts import latest_cohort_export_path, read_cohort, resolve_photo_packet
        packet_path = resolve_photo_packet(packet)
        cohort_data = read_cohort(packet_path, cohort)
        if cohort_data.get("status") != "ready":
            raise ValueError(f"Cohort must be ready: {cohort_data.get('cohort_id', cohort)}")
        packet_data = read_json(packet_path / "packet_manifest.json", {})
        packet_id = str(packet_data.get("job_id") or packet_path.name)
        cohort_id = str(cohort_data["cohort_id"])
        export_path = Path(source or latest_cohort_export_path(packet_path, cohort_data)).expanduser()
    elif source:
        packet_path = None
        cohort_data = {}
        export_path = Path(source).expanduser()
        packet_id = str(packet or "")
        cohort_id = str(cohort or export_path.name)
    else:
        raise ValueError("Supply --packet and --cohort, or an explicit --source path.")
    images_root = export_path / "files" if (export_path / "files").is_dir() else export_path
    if not images_root.is_dir():
        raise FileNotFoundError(f"Cohort export image source not found: {images_root}")
    inputs = source_images(images_root)
    if not inputs:
        raise FileNotFoundError(f"No source images found: {images_root}")
    return {
        "packet_id": packet_id,
        "packet_path": str(packet_path) if packet_path else "",
        "cohort_id": cohort_id,
        "cohort": cohort_data,
        "export_path": str(export_path),
        "inputs": inputs,
        "source_id": source_id(packet_id, cohort_id),
    }


def collision_work_filename(source_info: dict, filename: str, reserved_names: set[str]) -> str:
    cohort_prefix = registry_module().project_slug(source_info["cohort_id"])
    candidate = f"{cohort_prefix}__{filename}"
    if candidate.lower() not in reserved_names:
        return candidate
    packet_prefix = registry_module().project_slug(source_info["packet_id"])
    candidate = f"{packet_prefix}__{cohort_prefix}__{filename}"
    if candidate.lower() not in reserved_names:
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 2
    while True:
        candidate = f"{cohort_prefix}__{stem}-{counter}{suffix}"
        if candidate.lower() not in reserved_names:
            return candidate
        counter += 1


def plan_add_source(identifier: str, packet=None, cohort=None, source=None, copy_mode="copy", note="") -> dict:
    if copy_mode not in {"copy", "hardlink"}:
        raise ValueError(f"Invalid copy mode: {copy_mode}")
    manifest = load_edit_manifest(identifier)
    source_info = resolve_add_source(packet, cohort, source)
    already_linked = any(
        item.get("source_id") == source_info["source_id"] for item in manifest.get("sources", [])
    )
    reserved_names = {
        str(image.get("work_filename") or image.get("filename", "")).lower()
        for image in manifest.get("images", [])
    }
    checksum_to_image = {
        image.get("source_sha256"): image
        for image in manifest.get("images", [])
        if image.get("source_sha256")
    }
    items = []
    for path in source_info["inputs"]:
        checksum = file_sha256(path)
        duplicate = checksum_to_image.get(checksum)
        if duplicate:
            items.append(
                {
                    "source_path": str(path),
                    "source_filename": path.name,
                    "source_sha256": checksum,
                    "action": "identical_existing",
                    "existing_work_filename": duplicate.get("work_filename") or duplicate.get("filename"),
                }
            )
            continue
        work_filename = path.name
        if work_filename.lower() in reserved_names:
            work_filename = collision_work_filename(source_info, path.name, reserved_names)
        reserved_names.add(work_filename.lower())
        items.append(
            {
                "source_path": str(path),
                "source_filename": path.name,
                "source_sha256": checksum,
                "work_filename": work_filename,
                "work_path": str(Path(manifest["workspace_path"]) / work_filename),
                "action": copy_mode,
            }
        )
    return {
        "project_id": manifest["project_id"],
        "source": {
            "source_id": source_info["source_id"],
            "packet_id": source_info["packet_id"],
            "cohort_id": source_info["cohort_id"],
            "cohort_export_path": source_info["export_path"],
            "file_count": len(source_info["inputs"]),
            "status": "active",
            "note": note,
        },
        "copy_mode": copy_mode,
        "already_linked": already_linked,
        "items": items,
        "new_count": sum(1 for item in items if item["action"] in {"copy", "hardlink"}),
        "identical_count": sum(1 for item in items if item["action"] == "identical_existing"),
    }


def add_photo_edit_source(
    identifier: str,
    packet=None,
    cohort=None,
    source=None,
    copy_mode="copy",
    dry_run=False,
    note="",
) -> dict:
    plan = plan_add_source(identifier, packet, cohort, source, copy_mode, note)
    if dry_run:
        return {"dry_run": True, **plan}
    manifest = load_edit_manifest(identifier)
    if plan["already_linked"]:
        return {"dry_run": False, "added": 0, "existing_source": True, **plan}
    batch_id = f"batch-{uuid.uuid4().hex[:12]}"
    now = utc_now()
    additions = []
    for item in plan["items"]:
        if item["action"] == "identical_existing":
            continue
        source_path = Path(item["source_path"])
        target = Path(item["work_path"])
        if target.exists():
            raise ValueError(f"Refusing to overwrite workspace file: {target}")
        if copy_mode == "hardlink":
            os.link(source_path, target)
        else:
            shutil.copy2(source_path, target)
        if file_sha256(target) != item["source_sha256"]:
            raise ValueError(f"Workspace checksum mismatch after copy: {target}")
        additions.append(
            {
                "filename": item["work_filename"],
                "source_id": plan["source"]["source_id"],
                "source_packet_id": plan["source"]["packet_id"],
                "source_cohort_id": plan["source"]["cohort_id"],
                "source_export_path": plan["source"]["cohort_export_path"],
                "source_filename": item["source_filename"],
                "work_filename": item["work_filename"],
                "import_batch_id": batch_id,
                "added_at": now,
                "source_path": item["source_path"],
                "source_sha256": item["source_sha256"],
                "work_path": str(target),
                "xmp_path": str(target) + ".xmp",
                "export_path": None,
                "export_sha256": "",
                "dimensions": {},
                "role": "",
                "tags": [],
                "edit_status": "unedited",
                "review_status": "unreviewed",
                "note": "",
            }
        )
    source_entry = dict(plan["source"])
    source_entry.update(
        {
            "added_at": now,
            "import_batch_id": batch_id,
            "imported_count": len(additions),
        }
    )
    manifest.setdefault("sources", []).append(source_entry)
    manifest.setdefault("images", []).extend(additions)
    previous_verification = {
        "status": manifest.get("status", ""),
        "reviewed_at": manifest.get("reviewed_at"),
        "completed_at": manifest.get("completed_at"),
    }
    manifest["status"] = "needs_reverify"
    manifest["pending_filenames"] = [image["work_filename"] for image in additions]
    manifest["image_count"] = len(manifest["images"])
    manifest["history"].append(
        {
            "event": "supplemental_source_added",
            "timestamp": now,
            "source_id": source_entry["source_id"],
            "import_batch_id": batch_id,
            "added_files": manifest["pending_filenames"],
            "identical_existing": plan["identical_count"],
            "previous_verification": previous_verification,
            "note": note,
        }
    )
    refresh_edit_counts(manifest)
    save_edit_manifest(identifier, manifest)
    update_sale_item(identifier, status="photos_in_progress")
    write_edit_report(identifier, manifest, [])
    return {"dry_run": False, "added": len(additions), "batch_id": batch_id, **plan}


def darktable_launch() -> list[str]:
    configured = os.environ.get("LAIA_DARKTABLE_APP")
    if configured:
        app = Path(configured).expanduser()
        if not app.exists():
            raise FileNotFoundError(f"Configured Darktable application not found: {app}")
        if app.suffix == ".app":
            return ["open", "-a", str(app)]
        if not app.is_file():
            raise FileNotFoundError(f"Configured Darktable executable is invalid: {app}")
        return [str(app)]
    if shutil.which("darktable"):
        return [shutil.which("darktable")]
    app = Path("/Applications/darktable.app")
    if app.exists():
        return ["open", "-a", "darktable"]
    raise FileNotFoundError("Darktable not found. Set LAIA_DARKTABLE_APP to an installed application path.")


def open_photo_edit(identifier: str, pending: bool = False) -> dict:
    manifest = load_edit_manifest(identifier)
    launch = darktable_launch()
    workspace = Path(manifest["workspace_path"])
    pending_paths = [
        str(workspace / filename)
        for filename in manifest.get("pending_filenames", [])
        if (workspace / filename).is_file()
    ]
    targets = pending_paths if pending and pending_paths else [str(workspace)]
    subprocess.run(launch + targets, check=False)
    now = utc_now()
    manifest["opened_at"] = now
    manifest["history"].append(
        {
            "event": "opened_for_darktable_import" if pending_paths else "darktable_opened",
            "timestamp": now,
            "pending_filenames": manifest.get("pending_filenames", []),
            "passed_pending_directly": bool(pending and pending_paths),
        }
    )
    save_edit_manifest(identifier, manifest)
    return {
        "workspace": str(workspace),
        "command": launch,
        "pending_filenames": manifest.get("pending_filenames", []),
        "passed_pending_directly": bool(pending and pending_paths),
    }


def find_image(manifest: dict, filename: str) -> dict:
    matches = [image for image in manifest.get("images", []) if image.get("filename") == Path(filename).name]
    if len(matches) != 1:
        raise FileNotFoundError(f"Workspace image not found: {filename}")
    return matches[0]


def assign_role(identifier: str, filename: str, role: str, note: str = "") -> dict:
    if role not in PHOTO_ROLES:
        raise ValueError(f"Invalid photo role: {role}")
    manifest = load_edit_manifest(identifier)
    image = find_image(manifest, filename)
    image["role"] = role
    if note:
        image["note"] = note
    manifest["history"].append({"event": "role_assigned", "timestamp": utc_now(), "filename": image["filename"], "role": role})
    save_edit_manifest(identifier, manifest)
    return image


def normalize_tag(value: str) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def normalize_tags(values) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    return sorted({tag for tag in (normalize_tag(value) for value in values) if tag})


def unknown_tags(values: list[str]) -> list[str]:
    path = Path(__file__).resolve().parents[2] / "config" / "photo_tags.json"
    if not path.exists():
        return []
    data = read_json(path, {})
    allowed = data.get("tags", data if isinstance(data, list) else [])
    allowed = set(normalize_tags(allowed))
    return sorted(set(normalize_tags(values)) - allowed)


def update_image_tags(identifier: str, filename: str, tags: list[str], mode: str) -> dict:
    manifest = load_edit_manifest(identifier)
    image = find_image(manifest, filename)
    current = normalize_tags(image.get("tags", []))
    requested = normalize_tags(tags)
    if mode == "add":
        updated = normalize_tags(current + requested)
    elif mode == "remove":
        updated = sorted(set(current) - set(requested))
    elif mode == "set":
        updated = requested
    elif mode == "clear":
        updated = []
    else:
        raise ValueError(f"Invalid tag update mode: {mode}")
    image["tags"] = updated
    manifest["history"].append(
        {
            "event": "tags_updated",
            "timestamp": utc_now(),
            "filename": image["filename"],
            "mode": mode,
            "tags": updated,
        }
    )
    save_edit_manifest(identifier, manifest)
    return image


def photo_tag_summary(identifier: str, tag: Optional[str] = None) -> list[dict]:
    manifest = load_edit_manifest(identifier)
    selected = normalize_tag(tag) if tag else None
    grouped = {}
    for image in manifest.get("images", []):
        for image_tag in normalize_tags(image.get("tags", [])):
            if selected and image_tag != selected:
                continue
            row = grouped.setdefault(image_tag, {"tag": image_tag, "approved": 0, "files": []})
            row["files"].append(image.get("work_filename", image.get("filename", "")))
            if image.get("review_status") == "approved":
                row["approved"] += 1
    for row in grouped.values():
        row["files"] = sorted(row["files"])
    return [grouped[key] for key in sorted(grouped)]


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise ValueError(f"Not a readable JPEG: {path}")
        while True:
            marker_start = handle.read(1)
            if not marker_start:
                break
            if marker_start != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if marker in {bytes([value]) for value in range(0xC0, 0xC4)} | {bytes([value]) for value in range(0xC5, 0xC8)} | {bytes([value]) for value in range(0xC9, 0xCC)} | {bytes([value]) for value in range(0xCD, 0xD0)}:
                length = struct.unpack(">H", handle.read(2))[0]
                data = handle.read(length - 2)
                return struct.unpack(">H", data[3:5])[0], struct.unpack(">H", data[1:3])[0]
            if marker in {b"\xd8", b"\xd9"}:
                continue
            length_data = handle.read(2)
            if len(length_data) != 2:
                break
            length = struct.unpack(">H", length_data)[0]
            handle.seek(length - 2, 1)
    raise ValueError(f"JPEG dimensions not found: {path}")


def scan_exports(identifier: str) -> dict:
    manifest = load_edit_manifest(identifier)
    exports = Path(manifest["export_path"])
    by_stem = {}
    for path in exports.iterdir() if exports.exists() else []:
        if path.is_file() and path.suffix.lower() in JPEG_EXTENSIONS:
            by_stem.setdefault(path.stem.lower(), []).append(path)
    unmatched = []
    duplicates = []
    matched_stems = set()
    for image in manifest["images"]:
        matches = by_stem.get(Path(image["filename"]).stem.lower(), [])
        if len(matches) > 1:
            duplicates.append({"filename": image["filename"], "exports": [str(path) for path in matches]})
            continue
        if len(matches) == 1:
            render = matches[0]
            width, height = jpeg_dimensions(render)
            image.update(
                {
                    "export_path": str(render),
                    "export_sha256": file_sha256(render),
                    "dimensions": {"width": width, "height": height},
                    "edit_status": "exported" if image.get("review_status") not in {"approved", "rejected"} else image.get("edit_status"),
                }
            )
            matched_stems.add(render.stem.lower())
    for stem, paths in by_stem.items():
        if stem not in matched_stems and not any(entry["exports"] == [str(path) for path in paths] for entry in duplicates):
            unmatched.extend(str(path) for path in paths)
    manifest["history"].append(
        {"event": "exports_scanned", "timestamp": utc_now(), "matched": len(matched_stems), "unmatched": unmatched, "duplicates": duplicates}
    )
    refresh_edit_counts(manifest)
    save_edit_manifest(identifier, manifest)
    return {"matched": len(matched_stems), "unmatched": unmatched, "duplicates": duplicates}


def review_images(identifier: str, filenames: list[str], decision: str) -> list[dict]:
    manifest = load_edit_manifest(identifier)
    results = []
    for filename in filenames:
        image = find_image(manifest, filename)
        if decision == "approved":
            if not image.get("export_path") or not Path(image["export_path"]).is_file():
                raise ValueError(f"Rendered export required before approval: {image['filename']}")
            image["review_status"] = "approved"
            image["edit_status"] = "approved"
        else:
            image["review_status"] = "rejected"
            image["edit_status"] = "rejected"
        results.append(image)
    manifest["history"].append({"event": f"images_{decision}", "timestamp": utc_now(), "files": [item["filename"] for item in results]})
    refresh_edit_counts(manifest)
    save_edit_manifest(identifier, manifest)
    return results


def refresh_edit_counts(manifest: dict) -> None:
    images = manifest.get("images", [])
    manifest["edited_count"] = sum(1 for image in images if Path(image.get("xmp_path", "")).is_file())
    manifest["exported_count"] = sum(1 for image in images if image.get("export_path") and Path(image["export_path"]).is_file())
    manifest["approved_count"] = sum(1 for image in images if image.get("review_status") == "approved")
    manifest["rejected_count"] = sum(1 for image in images if image.get("review_status") == "rejected")


def edit_status_data(identifier: str) -> dict:
    manifest = load_edit_manifest(identifier)
    refresh_edit_counts(manifest)
    roles = {image.get("role") for image in manifest["images"] if image.get("role")}
    latest_source_ids = {
        source.get("source_id")
        for source in manifest.get("sources", [])[1:]
        if source.get("source_id")
    }
    return {
        "manifest": manifest,
        "xmp_count": manifest["edited_count"],
        "source_count": len(manifest.get("sources", [])),
        "new_unreviewed": sum(
            1
            for image in manifest.get("images", [])
            if image.get("source_id") in latest_source_ids and image.get("review_status") == "unreviewed"
        ),
        "missing_roles": sorted({"hero", "rear", "ports", "model_label"} - roles),
    }


def edit_sources(identifier: str) -> list[dict]:
    return load_edit_manifest(identifier).get("sources", [])


def edit_source_detail(identifier: str, source_identifier: str) -> dict:
    manifest = load_edit_manifest(identifier)
    source = next(
        (item for item in manifest.get("sources", []) if item.get("source_id") == source_identifier),
        None,
    )
    if source is None:
        raise FileNotFoundError(f"Photo edit source not found: {source_identifier}")
    images = [image for image in manifest.get("images", []) if image.get("source_id") == source_identifier]
    rows = []
    for image in images:
        source_path = Path(image.get("source_path", ""))
        work_path = Path(image.get("work_path", ""))
        source_ok = source_path.is_file() and file_sha256(source_path) == image.get("source_sha256")
        work_ok = work_path.is_file() and file_sha256(work_path) == image.get("source_sha256")
        rows.append(
            {
                "source_filename": image.get("source_filename", ""),
                "work_filename": image.get("work_filename", image.get("filename", "")),
                "import_batch_id": image.get("import_batch_id", ""),
                "source_exists": source_path.is_file(),
                "work_exists": work_path.is_file(),
                "checksum_ok": source_ok and work_ok,
            }
        )
    return {**source, "image_count": len(images), "images": rows}


def approved_role_counts(approved: list[dict]) -> dict:
    role_counts = {}
    for image in approved:
        role = image.get("role")
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1
    return role_counts


def photo_coverage(profile: str, role_counts: dict) -> dict:
    if profile == "records":
        roles = ["cover_front", "cover_back"]
    elif profile == "electronics":
        roles = ["hero", "model_label", "rear", "ports"]
    else:
        roles = []
    return {
        role: "approved" if role_counts.get(role, 0) else "missing"
        for role in roles
    }


def verify_photo_profile(profile: str, approved: list[dict], role_counts: dict, item: Optional[dict]) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    if not approved:
        errors.append("At least one approved image is required.")
    if profile == "records":
        cover_front_count = role_counts.get("cover_front", 0)
        if cover_front_count != 1:
            errors.append("Exactly one approved cover_front image is required.")
        if role_counts.get("cover_back", 0) < 1:
            warnings.append("No approved cover_back image.")
        return errors, warnings
    if profile == "generic":
        return errors, warnings
    heroes = role_counts.get("hero", 0)
    if heroes != 1:
        errors.append("Exactly one approved hero image is required.")
    if item is None:
        return errors, warnings
    if not role_counts.get("model_label", 0):
        warnings.append("No approved model-label image.")
    if item["condition"].get("known_defects") and not role_counts.get("defect", 0):
        warnings.append("Known defects exist but no approved defect image.")
    if len(approved) < 3:
        warnings.append("Fewer than three approved listing images.")
    for role in ["rear", "ports"]:
        if not role_counts.get(role, 0):
            warnings.append(f"No approved {role} image.")
    return errors, warnings


def verify_photo_edit(identifier: str) -> dict:
    manifest = load_edit_manifest(identifier)
    approved = [image for image in manifest["images"] if image.get("review_status") == "approved"]
    try:
        item = load_sale_item(identifier)
    except FileNotFoundError:
        item = None
    profile = verification_profile_for_item(item)
    errors = []
    warnings = []
    role_counts = approved_role_counts(approved)
    profile_errors, profile_warnings = verify_photo_profile(profile, approved, role_counts, item)
    errors.extend(profile_errors)
    warnings.extend(profile_warnings)
    for image in approved:
        render = Path(image.get("export_path", ""))
        if not render.is_file():
            errors.append(f"Approved export missing: {image.get('filename', '')}")
            continue
        try:
            width, height = jpeg_dimensions(render)
            image["dimensions"] = {"width": width, "height": height}
        except ValueError as exc:
            errors.append(str(exc))
        if not image.get("source_sha256") or not Path(image.get("source_path", "")).is_file():
            errors.append(f"Source provenance missing: {image.get('filename', '')}")
    for role, count in role_counts.items():
        if role in UNIQUE_ROLES and count > 1:
            errors.append(f"Duplicate unique role: {role}")
    orientations = {
        "landscape" if image.get("dimensions", {}).get("width", 0) >= image.get("dimensions", {}).get("height", 0) else "portrait"
        for image in approved
        if image.get("dimensions")
    }
    if len(orientations) > 1:
        warnings.append("Approved exports have mixed orientation.")
    success = not errors
    if success:
        was_reverify = manifest.get("status") == "needs_reverify"
        manifest["status"] = "complete"
        manifest["reviewed_at"] = utc_now()
        manifest["completed_at"] = manifest["reviewed_at"]
        manifest["pending_filenames"] = []
        if item is not None:
            update_sale_item(identifier, status="photos_ready")
    manifest["history"].append(
        {
            "event": "project_reverified" if success and was_reverify else "verification",
            "timestamp": utc_now(),
            "success": success,
            "profile": profile,
            "errors": errors,
            "warnings": warnings,
        }
    )
    refresh_edit_counts(manifest)
    save_edit_manifest(identifier, manifest)
    coverage = photo_coverage(profile, role_counts)
    write_edit_report(identifier, manifest, errors, warnings, profile, coverage)
    return {
        "success": success,
        "profile": profile,
        "coverage": coverage,
        "errors": errors,
        "warnings": warnings,
        "approved_count": len(approved),
    }


def write_edit_report(
    identifier: str,
    manifest: dict,
    errors: list,
    warnings: Optional[list] = None,
    profile: Optional[str] = None,
    coverage: Optional[dict] = None,
) -> Path:
    warnings = warnings or []
    coverage = coverage or {}
    lines = [
        f"# Photo Edit Report: {manifest.get('project_id', '')}",
        "",
        f"- Status: {manifest.get('status', '')}",
        f"- Profile: {profile or 'unknown'}",
        f"- Source images: {manifest.get('image_count', 0)}",
        f"- XMP sidecars: {manifest.get('edited_count', 0)}",
        f"- Rendered exports: {manifest.get('exported_count', 0)}",
        f"- Approved: {manifest.get('approved_count', 0)}",
        "",
        "## Coverage",
        *(f"- {role}: {state}" for role, state in coverage.items()),
        *(["- none"] if not coverage else []),
        "",
        "## Errors",
        *(f"- {value}" for value in errors),
        *(["- none"] if not errors else []),
        "",
        "## Warnings",
        *(f"- {value}" for value in warnings),
        *(["- none"] if not warnings else []),
        "",
    ]
    path = edit_report_path(identifier)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def package_photos(identifier: str) -> dict:
    pid = project_id(identifier)
    item = load_sale_item(pid)
    manifest = load_edit_manifest(pid)
    approved = [image for image in manifest["images"] if image.get("review_status") == "approved"]
    if not approved:
        raise ValueError("No approved listing images.")
    destination = listing_root(pid) / "photos"
    destination.mkdir(parents=True, exist_ok=True)
    role_counts = {}
    entries = []
    expected_names = set()
    for image in approved:
        role = image.get("role") or "other"
        role_counts[role] = role_counts.get(role, 0) + 1
        suffix = f"-{role_counts[role]}" if role_counts[role] > 1 else ""
        name = f"{item['item_id']}_{role.replace('_', '-')}{suffix}.jpg"
        expected_names.add(name)
        source = Path(image["export_path"])
        target = destination / name
        shutil.copy2(source, target)
        entries.append(
            {
                "filename": name,
                "listing_filename": name,
                "role": role,
                "tags": normalize_tags(image.get("tags", [])),
                "review": image.get("review_status", ""),
                "source_id": image.get("source_id", ""),
                "packet_id": image.get("source_packet_id", manifest.get("source_packet_id", "")),
                "cohort_id": image.get("source_cohort_id", manifest.get("source_cohort_id", "")),
                "source_packet_id": image.get("source_packet_id", manifest.get("source_packet_id", "")),
                "source_cohort_id": image.get("source_cohort_id", manifest.get("source_cohort_id", "")),
                "source_export_path": image.get("source_export_path", manifest.get("source_export_path", "")),
                "source_filename": image.get("source_filename", image["filename"]),
                "workspace_filename": image.get("work_filename", image["filename"]),
                "xmp_path": image["xmp_path"],
                "render_path": image["export_path"],
                "render_sha256": image["export_sha256"],
                "packaged_path": str(target),
            }
        )
    for stale in destination.glob(f"{item['item_id']}_*.jpg"):
        if stale.name not in expected_names:
            stale.unlink()
    photo_manifest = {
        "record_type": "laia.listing_photos",
        "record_version": "0.1",
        "project_id": pid,
        "created_at": utc_now(),
        "photos": entries,
    }
    path = destination / "photo_manifest.json"
    write_json(path, photo_manifest)
    listing_manifest_path = listing_root(pid) / "photos_manifest.json"
    write_json(listing_manifest_path, photo_manifest)
    (listing_root(pid) / "photos_manifest.md").write_text(
        "\n".join(
            [
                f"# Listing Photos: {item.get('title', '')}",
                "",
                *[
                    "\n".join(
                        [
                            f"- {entry['listing_filename']}",
                            f"  - role: {entry['role']}",
                            f"  - tags: {', '.join(entry['tags']) if entry['tags'] else 'none'}",
                        ]
                    )
                    for entry in entries
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    manifest["history"].append({"event": "photo_package_created", "timestamp": utc_now(), "path": str(destination), "count": len(entries)})
    save_edit_manifest(pid, manifest)
    return {"path": str(destination), "manifest": str(path), "count": len(entries), "photos": entries}


def listing_missing_fields(item: dict, photo_manifest: Optional[dict]) -> list[str]:
    profile = verification_profile_for_item(item)
    missing = []
    if not item.get("title"):
        missing.append("title")
    if not item.get("category"):
        missing.append("category")
    if item["condition"].get("overall") == "unassessed":
        missing.append("condition")
    if profile == "electronics" and item["condition"].get("functional") in {"untested", "unknown"}:
        missing.append("functional status")
    if item["pricing"].get("asking_price") is None:
        missing.append("asking price")
    if not item.get("description"):
        missing.append("description")
    if not photo_manifest or not photo_manifest.get("photos"):
        missing.append("verified listing photos")
    return missing


def build_listing_package(identifier: str) -> dict:
    pid = project_id(identifier)
    item = load_sale_item(pid)
    root = listing_root(pid)
    photos_manifest_path = root / "photos" / "photo_manifest.json"
    photos = read_json(photos_manifest_path, {})
    missing = listing_missing_fields(item, photos)
    status = "ready" if not missing and item["sale"].get("status") in {"photos_ready", "listing_ready"} else "incomplete"
    tasks = registry_module().project_tasks(pid)
    package = {
        "record_type": "laia.listing_package",
        "record_version": "0.1",
        "project_id": pid,
        "profile": verification_profile_for_item(item),
        "item": item,
        "photos": photos.get("photos", []),
        "source": item.get("source", {}),
        "task_ids": [task.get("task_id", "") for task in tasks],
        "missing_fields": missing,
        "status": status,
        "created_at": utc_now(),
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "drafts").mkdir(exist_ok=True)
    write_json(root / "listing_package.json", package)
    (root / "listing_package.md").write_text(
        "\n".join(
            [
                f"# Listing Package: {item.get('title', '')}",
                "",
                f"- Status: {status}",
                f"- Photos: {len(package['photos'])}",
                "",
                "## Missing Before Publication",
                *(f"- {value}" for value in missing),
                *(["- none"] if not missing else []),
                "",
            ]
        ),
        encoding="utf-8",
    )
    if status == "ready":
        update_sale_item(pid, status="listing_ready")
    return package


def channel_recommendations(item: dict) -> dict:
    category = " ".join([str(item.get("category", "")), str(item.get("subcategory", ""))]).lower()
    if any(word in category for word in ("record", "vinyl", "music media", "compact disc")):
        recommended = [
            ("facebook_marketplace", "local buyers"),
            ("craigslist", "local buyers and bundles"),
            ("offerup", "local buyers"),
            ("discogs", "specialist record marketplace"),
            ("ebay", "wider collector market"),
        ]
        optional = [("nextdoor", "local bundles")]
        not_primary = []
    else:
        recommended = [
            ("facebook_marketplace", "local electronics buyers"),
            ("craigslist", "local electronics buyers"),
            ("offerup", "local electronics buyers"),
        ]
        optional = [
            ("ebay", "wider reach with local pickup or shipping"),
            ("reverb", "vintage AV or audio gear"),
        ]
        not_primary = [("discogs", "records and media, not hardware")]
    active = {row.get("channel"): row.get("status") for row in item.get("listings", [])}
    def rows(values):
        return [
            {
                **channel_preset(channel_id),
                "reason": reason,
                "current_status": active.get(channel_id, ""),
            }
            for channel_id, reason in values
        ]
    return {"recommended": rows(recommended), "optional": rows(optional), "not_primary": rows(not_primary)}


def listing_description(item: dict, channel_id: str) -> str:
    description = (item.get("description") or "").strip()
    condition = item.get("condition", {})
    parts = [description] if description else []
    if condition.get("condition_notes"):
        parts.append(f"Condition notes: {condition['condition_notes']}")
    if condition.get("known_defects"):
        parts.append("Known defects: " + "; ".join(condition["known_defects"]))
    if item.get("included_items"):
        parts.append("Included: " + ", ".join(item["included_items"]))
    if channel_id == "craigslist":
        parts.append("Local pickup preferred. Functional demonstration video available on request.")
    elif channel_id == "facebook_marketplace":
        parts.append("Local pickup preferred.")
    elif channel_id == "ebay":
        parts.append("Shipping policy: [confirm shipping or local pickup].")
        parts.append("Package weight/dimensions: [measure before publishing].")
    elif channel_id == "discogs":
        parts.extend(
            [
                "Artist: [enter artist]", "Release title: [enter title]",
                "Pressing/version: [enter pressing]", "Media condition: [grade]",
                "Sleeve condition: [grade]", "Matrix/runout: [enter matrix]",
                "Grading notes: [enter notes]", "Photo evidence tags: [enter tags]",
            ]
        )
    return "\n\n".join(part for part in parts if part).strip() + "\n"


def build_channel_package(identifier: str, channel: str) -> dict:
    pid = project_id(identifier)
    item = load_sale_item(pid)
    preset = channel_preset(channel)
    channel_id = preset["channel_id"]
    root = listing_root(pid)
    destination = root / "channel" / channel_id
    photos_destination = destination / "photos"
    videos_destination = destination / "videos"
    destination.mkdir(parents=True, exist_ok=True)
    photos_destination.mkdir(exist_ok=True)
    videos_destination.mkdir(exist_ok=True)
    for folder in (photos_destination, videos_destination):
        for path in folder.iterdir():
            if path.is_file():
                path.unlink()
    source_photos = root / "photos"
    copied_photos = []
    if source_photos.is_dir():
        for source in sorted(source_photos.iterdir(), key=lambda value: value.name.lower()):
            if source.is_file() and source.suffix.lower() in JPEG_EXTENSIONS:
                shutil.copy2(source, photos_destination / source.name)
                copied_photos.append(source.name)
    copied_videos = []
    if channel_id == "facebook_marketplace":
        for video in registry_module().project_video_evidence(pid):
            source_text = video.get("proxy_path") or video.get("original_path")
            source = Path(source_text) if source_text else None
            if source and source.is_file():
                name = f"{listing_slug(pid)}_{listing_slug(video.get('role') or 'video')}{source.suffix.lower()}"
                shutil.copy2(source, videos_destination / name)
                copied_videos.append(name)
    title = item.get("title", pid)
    if channel_id == "facebook_marketplace" and len(title) > 80:
        title = title[:77].rstrip() + "..."
    price = item.get("pricing", {}).get("asking_price") or ""
    description = listing_description(item, channel_id)
    posting_notes = [
        f"# {preset['display_name']} Posting Notes", "",
        f"- Listing type: {preset['listing_type']}",
        f"- Local pickup: {'yes' if preset['supports_local_pickup'] else 'no'}",
        f"- Shipping: {'yes' if preset['supports_shipping'] else 'no'}",
        f"- Photos: {len(copied_photos)}",
        f"- Videos: {len(copied_videos)}",
    ]
    if channel_id == "craigslist":
        posting_notes.append("- Video is not copied; mention that a functional demo is available.")
    (destination / "title.txt").write_text(title.strip() + "\n", encoding="utf-8")
    (destination / "description.txt").write_text(description, encoding="utf-8")
    (destination / "price.txt").write_text(str(price) + "\n", encoding="utf-8")
    (destination / "posting_notes.md").write_text("\n".join(posting_notes) + "\n", encoding="utf-8")
    package = {
        "record_type": "laia.sale_item.channel_package", "record_version": "0.1",
        "project_id": pid, "channel": preset, "title": title, "price": price,
        "description_path": str(destination / "description.txt"),
        "photos": copied_photos, "videos": copied_videos,
        "package_path": str(destination), "created_at": utc_now(),
    }
    write_json(destination / "package.json", package)
    listing = next(
        (row for row in item["listings"] if row.get("channel") == channel_id and row.get("status") in ACTIVE_LISTING_STATUSES),
        None,
    )
    if listing is None:
        now = utc_now()
        listing = {
            "listing_id": f"{listing_slug(channel_id)}-{timestamp_date(now)}",
            "channel": channel_id, "channel_name": preset["display_name"], "status": "draft",
            "url": "", "asking_price": price, "posted_at": None, "updated_at": now,
            "title": title, "description_path": f"listing/channel/{channel_id}/description.txt",
            "asset_package_path": f"listing/channel/{channel_id}", "note": "Channel package generated.",
            "history": [],
        }
        item["listings"].append(listing)
        append_listing_event(item, listing, "drafted", "Channel package generated.", now)
    else:
        listing.update(
            {
                "asking_price": price, "title": title,
                "description_path": f"listing/channel/{channel_id}/description.txt",
                "asset_package_path": f"listing/channel/{channel_id}", "updated_at": utc_now(),
            }
        )
    summarize_sale_status(item)
    write_sale_item(pid, item)
    return package


def channel_packages(identifier: str) -> list[dict]:
    root = listing_root(identifier) / "channel"
    if not root.is_dir():
        return []
    return [
        read_json(path / "package.json")
        for path in sorted(root.iterdir(), key=lambda value: value.name)
        if path.is_dir() and (path / "package.json").is_file()
    ]


def bootstrap_sale_item(identifier: str) -> dict:
    registry = registry_module()
    pid = registry.find_project(identifier)
    item = init_sale_item(pid)
    existing_titles = {task.get("title") for task in registry.project_tasks(pid)}
    specs = [
        (
            f"Assess {item['title']}",
            [
                "identify manufacturer and full model",
                "record serial/model labels",
                "test power and core functions",
                "record cosmetic condition",
                "record included and missing accessories",
                "record known defects",
            ],
            {},
        ),
        (
            f"Edit {item['title']} listing photos",
            [
                "prepare Darktable workspace",
                "assign photo roles",
                "edit images non-destructively in Darktable",
                "export listing JPEGs",
                "scan rendered exports",
                "approve listing images",
                "verify listing photo set",
                "create listing photo package",
            ],
            {
                "prepare Darktable workspace": ("photo_edit_prepare", {"project": pid}),
                "edit images non-destructively in Darktable": (
                    "manual",
                    {"instruction": "Edit project workspace images in Darktable and export JPEGs to photo_edit/exports."},
                ),
                "scan rendered exports": ("photo_edit_scan_exports", {"project": pid}),
                "verify listing photo set": ("photo_edit_verify", {"project": pid}),
                "create listing photo package": ("photo_edit_package", {"project": pid}),
            },
        ),
        (
            "Research price and prepare listing",
            [
                "record comparable prices",
                "choose asking price",
                "choose minimum acceptable price",
                "draft title",
                "draft description",
                "select selling channels",
                "review final listing package",
            ],
            {},
        ),
        (
            f"Capture missing {item['title']} listing coverage",
            [
                "photograph rear panel",
                "photograph ports and connector labels",
                "photograph keypad close-up",
                "ingest supplemental photo session",
                f"create supplemental {item['title']} cohort",
                "generate cohort contact sheet",
                "export supplemental cohort",
                f"link supplemental cohort to {item['title']} project",
                "add supplemental cohort to Darktable workspace",
                "edit and export supplemental photos",
                "assign rear and ports roles",
                "approve supplemental renders",
                "reverify listing photo set",
                "regenerate listing photo package",
            ],
            {
                "edit and export supplemental photos": (
                    "manual",
                    {"instruction": "Edit supplemental workspace images in Darktable and export JPEGs to photo_edit/exports."},
                ),
                "reverify listing photo set": ("photo_edit_verify", {"project": pid}),
                "regenerate listing photo package": ("photo_edit_package", {"project": pid}),
            },
        ),
    ]
    created = []
    for title, checklist, actions in specs:
        if title in existing_titles:
            continue
        task = registry.add_project_task(pid, title, priority="high")
        for text in checklist:
            row = registry.add_task_checklist_item(task["task_id"], text, pid)
            if text in actions:
                action_type, parameters = actions[text]
                registry.set_checklist_action(task["task_id"], row["item_id"], action_type, parameters, pid)
        created.append(task["task_id"])
    return {"sale_item": item, "created_tasks": created, "task_count": len(registry.project_tasks(pid))}


def bootstrap_record_sale_item(
    identifier: str,
    packet: str,
    cohort: str,
    artist: str,
    title: str,
    label: str = "",
    catalog_number: str = "",
) -> dict:
    display_title = " - ".join(value for value in [artist.strip(), title.strip()] if value)
    item = init_sale_item(
        identifier,
        title=display_title,
        manufacturer=label,
        model=catalog_number,
        category="records",
        cohort=cohort,
        packet=packet,
    )
    item = update_sale_item(
        identifier,
        title=display_title,
        manufacturer=label,
        model=catalog_number,
        category="records",
        functional_status="not_applicable",
    )
    item["condition"]["functional"] = "not_applicable"
    item["record_metadata"] = {
        "artist": artist, "title": title, "record_label": label,
        "catalog_number": catalog_number,
        "media_condition": "",
        "sleeve_condition": "",
        "grading_note": "",
    }
    item["source"]["packet_id"] = packet
    item["source"]["cohort_id"] = cohort
    return write_sale_item(identifier, item)


def _read_record_cohort_metadata(packet_path: Path, cohort_id: str) -> dict:
    try:
        from photo_ingest.cohorts import _read_json, cohort_dir
    except (ImportError, ModuleNotFoundError):
        from core.photo_ingest.cohorts import _read_json, cohort_dir
    return _read_json(cohort_dir(packet_path, cohort_id) / "record_metadata.json", {})


def _record_placeholder_title(cohort_id: str) -> str:
    suffix = cohort_id.replace("-", " ").title()
    return f"Unidentified {suffix}"


def _record_bootstrap_metadata(packet_path: Path, cohort_id: str) -> dict:
    metadata = _read_record_cohort_metadata(packet_path, cohort_id)
    artist = str(metadata.get("artist") or "").strip()
    title = str(metadata.get("title") or "").strip()
    return {
        "artist": artist,
        "title": title,
        "record_label": str(metadata.get("record_label") or metadata.get("label") or "").strip(),
        "catalog_number": str(metadata.get("catalog_number") or "").strip(),
        "display_title": " - ".join(value for value in [artist, title] if value) or _record_placeholder_title(cohort_id),
        "metadata_found": bool(metadata),
    }


def _record_cohort_rows(packet_path: Path, parent: str, prefix: str, limit: Optional[int], only: Optional[list[str]]) -> list[dict]:
    try:
        from photo_ingest.cohorts import read_cohort, read_cohort_index
    except (ImportError, ModuleNotFoundError):
        from core.photo_ingest.cohorts import read_cohort, read_cohort_index
    parent_id = read_cohort(packet_path, parent)["cohort_id"]
    only_set = {value.strip() for value in (only or []) if value.strip()}
    rows = [
        row
        for row in read_cohort_index(packet_path).get("cohorts", [])
        if row.get("parent_cohort_id") == parent_id
        and str(row.get("cohort_id", "")).startswith(f"{prefix}-")
        and (not only_set or row.get("cohort_id") in only_set)
    ]
    rows = sorted(rows, key=lambda row: row.get("cohort_id", ""))
    return rows[:limit] if limit is not None else rows


def bootstrap_record_sale_items_from_cohorts(
    packet: str,
    parent: str = "records-for-sale",
    prefix: str = "record",
    limit: Optional[int] = None,
    only: Optional[list[str]] = None,
    skip_existing: bool = True,
    prepare_photo_edit_workspace: bool = False,
    appraisal_context: bool = False,
    condition: bool = False,
    listing_draft: bool = False,
) -> dict:
    try:
        from photo_ingest.cohorts import export_cohort, latest_cohort_export_path, read_cohort, resolve_photo_packet
    except (ImportError, ModuleNotFoundError):
        from core.photo_ingest.cohorts import export_cohort, latest_cohort_export_path, read_cohort, resolve_photo_packet
    packet_path = resolve_photo_packet(packet)
    packet_id = packet_path.name
    registry = registry_module()
    rows = _record_cohort_rows(packet_path, parent, prefix, limit, only)
    created = []
    skipped = []
    for row in rows:
        cohort_id = str(row["cohort_id"])
        try:
            existing_project = registry.find_project(cohort_id)
        except FileNotFoundError:
            existing_project = ""
        if existing_project and skip_existing:
            skipped.append({"project_id": existing_project, "cohort_id": cohort_id, "reason": "already exists"})
            continue
        cohort = read_cohort(packet_path, cohort_id)
        export_path = latest_cohort_export_path(packet_path, cohort)
        if prepare_photo_edit_workspace and not export_path:
            export_path = export_cohort(packet_path, cohort_id)["destination"]
            cohort = read_cohort(packet_path, cohort_id)
        metadata = _record_bootstrap_metadata(packet_path, cohort_id)
        project = registry.ensure_project_record(cohort_id, project_type="sale_item", status="active")
        registry.add_cohort_to_project(
            project["project_id"],
            {
                "packet_id": packet_id,
                "cohort_id": cohort_id,
                "cohort_name": cohort.get("name", cohort_id),
                "cohort_status": cohort.get("status", ""),
                "parent_cohort_id": cohort.get("parent_cohort_id", ""),
                "artifact_path": export_path,
                "linked_at": registry.utc_now(),
            },
        )
        if export_path:
            registry.add_artifact_to_project(project["project_id"], export_path, packet_id, registry.utc_now(), "photo_cohort_export")
        item = bootstrap_record_sale_item(
            project["project_id"],
            packet_id,
            cohort_id,
            metadata["artist"],
            metadata["display_title"] if not metadata["title"] else metadata["title"],
            metadata["record_label"],
            metadata["catalog_number"],
        )
        item["title"] = metadata["display_title"]
        item["manufacturer"] = metadata["record_label"]
        item["model"] = metadata["catalog_number"]
        item["record_metadata"] = {
            "artist": metadata["artist"],
            "title": metadata["title"],
            "record_label": metadata["record_label"],
            "catalog_number": metadata["catalog_number"],
            "media_condition": "",
            "sleeve_condition": "",
            "grading_note": "",
        }
        item["sale"]["status"] = "photos_ready" if cohort.get("status") == "ready" else "photos_in_progress"
        item["sale_status"] = item["sale"]["status"]
        item["source"]["cohort_export_path"] = export_path
        write_sale_item(project["project_id"], item)
        photo_edit = None
        if prepare_photo_edit_workspace:
            photo_edit = prepare_photo_edit(project["project_id"], cohort=cohort_id, source=export_path)
            for image in photo_edit["manifest"].get("images", []):
                relative = next(
                    (
                        file_row.get("relative_path", "")
                        for file_row in cohort.get("files", [])
                        if Path(file_row.get("relative_path", "")).name == image.get("source_filename")
                    ),
                    "",
                )
                position = [file_row.get("relative_path", "") for file_row in cohort.get("files", [])].index(relative) if relative else -1
                if position == 0:
                    assign_role(project["project_id"], image["filename"], "cover_front")
                elif position == 1:
                    assign_role(project["project_id"], image["filename"], "cover_back")
        scaffolds = {}
        if appraisal_context or condition or listing_draft:
            try:
                from projects import appraisal_context as appraisal
            except (ImportError, ModuleNotFoundError):
                from core.projects import appraisal_context as appraisal
            if appraisal_context:
                scaffolds["appraisal_context"] = appraisal.write_appraisal_context(project["project_id"])
            if condition:
                scaffolds["condition"] = appraisal.write_record_condition(project["project_id"])
            if listing_draft:
                scaffolds["listing_draft"] = appraisal.write_listing_draft_context(project["project_id"])
        created.append(
            {
                "project_id": project["project_id"],
                "cohort_id": cohort_id,
                "title": item["title"],
                "metadata_found": metadata["metadata_found"],
                "photo_edit": photo_edit["manifest"]["workspace_path"] if photo_edit else "",
                "scaffolds": scaffolds,
            }
        )
    return {"packet": packet_id, "parent": parent, "created": created, "skipped": skipped}


def sale_briefing(identifier: str) -> dict:
    item = migrate_sale_item(read_json(sale_item_path(identifier), {}))
    edit = migrate_edit_manifest(read_json(edit_manifest_path(identifier), {}))
    if edit:
        refresh_edit_counts(edit)
    suggestions = []
    if not edit and item:
        suggestions.append("Prepare the Darktable workspace.")
    elif edit and edit.get("exported_count", 0) == 0:
        suggestions.append("Edit listing photos in Darktable and export edited JPEGs.")
    elif edit and edit.get("approved_count", 0) == 0:
        suggestions.append("Approve a hero image and the final listing images.")
    if edit and len(edit.get("sources", [])) > 1 and edit.get("status") == "needs_reverify":
        suggestions = [
            f"Edit supplemental {item.get('title', identifier)} photos in Darktable.",
            "Approve rear and ports images.",
            "Reverify the listing photo set.",
            "Regenerate the listing photo package.",
        ]
    if item:
        if item["condition"].get("overall") == "unassessed":
            suggestions.append("Assess item condition.")
        if item["pricing"].get("asking_price") is None:
            suggestions.append("Set the asking price.")
        if item["sale"].get("status") == "photos_ready":
            suggestions.append("Generate the listing package.")
    return {
        "sale_item": item,
        "listings": item.get("listings", []) if item else [],
        "offers": item.get("offers", []) if item else [],
        "photo_edit": edit,
        "suggestions": suggestions,
    }


def register_sale_item_subcommands(projects_sub) -> None:
    init_p = projects_sub.add_parser("sale-item-init", help="Initialize a project sale item record")
    init_p.add_argument("identifier")
    for option in ["title", "manufacturer", "model", "category", "cohort", "packet", "cohort-export"]:
        init_p.add_argument(f"--{option}")
    init_p.add_argument("--json", action="store_true")
    init_p.set_defaults(func=command_sale_item_init)

    show_p = projects_sub.add_parser("sale-item", help="Show a project sale item")
    show_p.add_argument("identifier")
    show_p.add_argument("--json", action="store_true")
    show_p.set_defaults(func=command_sale_item)

    update_p = projects_sub.add_parser("sale-item-update", help="Update sale item fields")
    update_p.add_argument("identifier")
    for option in [
        "title", "manufacturer", "model", "category", "subcategory", "description",
        "condition-note", "known-defect", "included-item", "missing-item",
        "serial-number", "asking-price", "minimum-price", "estimated-value",
        "pricing-note", "record-artist", "record-title", "record-label",
        "catalog-number", "media-condition", "sleeve-condition", "grading-note",
    ]:
        update_p.add_argument(f"--{option}")
    update_p.add_argument("--condition", choices=sorted(CONDITION_VALUES))
    update_p.add_argument("--functional-status", choices=sorted(FUNCTIONAL_STATES))
    update_p.add_argument("--status", choices=sorted(SALE_STATUSES))
    update_p.add_argument("--json", action="store_true")
    update_p.set_defaults(func=command_sale_item_update)

    list_p = projects_sub.add_parser("sale-item-list", help="Record marketplace listing")
    list_p.add_argument("identifier")
    list_p.add_argument("--channel", required=True)
    list_p.add_argument("--url", default="")
    list_p.add_argument("--asking-price")
    list_p.add_argument("--note", default="")
    list_p.set_defaults(func=command_sale_item_list)

    listings_p = projects_sub.add_parser("sale-item-listings", help="List channel listings")
    listings_p.add_argument("identifier")
    listings_p.add_argument("--json", action="store_true")
    listings_p.set_defaults(func=command_sale_item_listings)

    listing_show_p = projects_sub.add_parser("sale-item-listing", help="Show one channel listing")
    listing_show_p.add_argument("identifier")
    listing_show_p.add_argument("listing_id")
    listing_show_p.add_argument("--json", action="store_true")
    listing_show_p.set_defaults(func=command_sale_item_listing)

    listing_update_p = projects_sub.add_parser("sale-item-listing-update", help="Update a channel listing")
    listing_update_p.add_argument("identifier")
    listing_update_p.add_argument("listing_id")
    listing_update_p.add_argument("--status", choices=sorted(LISTING_STATUSES))
    listing_update_p.add_argument("--url")
    listing_update_p.add_argument("--asking-price")
    listing_update_p.add_argument("--title")
    listing_update_p.add_argument("--note")
    listing_update_p.add_argument("--event", choices=sorted(LISTING_EVENTS))
    listing_update_p.set_defaults(func=command_sale_item_listing_update)

    listing_note_p = projects_sub.add_parser("sale-item-listing-note", help="Add a note to a channel listing")
    listing_note_p.add_argument("identifier")
    listing_note_p.add_argument("listing_id")
    listing_note_p.add_argument("--note", required=True)
    listing_note_p.set_defaults(func=command_sale_item_listing_note)

    offer_p = projects_sub.add_parser("sale-item-offer", help="Record an offer")
    offer_p.add_argument("identifier")
    offer_p.add_argument("listing_id")
    offer_p.add_argument("--amount", required=True)
    offer_p.add_argument("--buyer", default="")
    offer_p.add_argument("--note", default="")
    offer_p.add_argument("--status", choices=sorted(OFFER_STATUSES), default="received")
    offer_p.set_defaults(func=command_sale_item_offer)

    offers_p = projects_sub.add_parser("sale-item-offers", help="List offers")
    offers_p.add_argument("identifier")
    offers_p.add_argument("--json", action="store_true")
    offers_p.set_defaults(func=command_sale_item_offers)

    offer_update_p = projects_sub.add_parser("sale-item-offer-update", help="Update an offer status")
    offer_update_p.add_argument("identifier")
    offer_update_p.add_argument("offer_id")
    offer_update_p.add_argument("--status", choices=sorted(OFFER_STATUSES), required=True)
    offer_update_p.add_argument("--note", default="")
    offer_update_p.set_defaults(func=command_sale_item_offer_update)

    crosspost_p = projects_sub.add_parser("sale-item-crosspost-plan", help="Recommend sales channels")
    crosspost_p.add_argument("identifier")
    crosspost_p.add_argument("--json", action="store_true")
    crosspost_p.set_defaults(func=command_sale_item_crosspost_plan)

    channel_package_p = projects_sub.add_parser("sale-item-channel-package", help="Build a channel-specific listing package")
    channel_package_p.add_argument("identifier")
    channel_package_p.add_argument("--channel", choices=sorted(CHANNEL_PRESETS), required=True)
    channel_package_p.add_argument("--json", action="store_true")
    channel_package_p.set_defaults(func=command_sale_item_channel_package)

    channel_packages_p = projects_sub.add_parser("sale-item-channel-packages", help="List channel-specific packages")
    channel_packages_p.add_argument("identifier")
    channel_packages_p.add_argument("--json", action="store_true")
    channel_packages_p.set_defaults(func=command_sale_item_channel_packages)

    sold_p = projects_sub.add_parser("sale-item-sold", help="Record completed sale")
    sold_p.add_argument("identifier")
    sold_p.add_argument("--channel", required=True)
    sold_p.add_argument("--sale-price", required=True)
    sold_p.add_argument("--fees")
    sold_p.add_argument("--shipping")
    sold_p.add_argument("--buyer", default="")
    sold_p.add_argument("--note", default="")
    sold_p.set_defaults(func=command_sale_item_sold)

    bootstrap_p = projects_sub.add_parser("sale-item-bootstrap", help="Create sale project tasks")
    bootstrap_p.add_argument("identifier")
    bootstrap_p.add_argument("--json", action="store_true")
    bootstrap_p.set_defaults(func=command_sale_item_bootstrap)

    bootstrap_record_p = projects_sub.add_parser("sale-item-bootstrap-record", help="Initialize a lightweight record sale item")
    bootstrap_record_p.add_argument("identifier")
    bootstrap_record_p.add_argument("--packet", required=True)
    bootstrap_record_p.add_argument("--cohort", required=True)
    bootstrap_record_p.add_argument("--artist", required=True)
    bootstrap_record_p.add_argument("--title", required=True)
    bootstrap_record_p.add_argument("--label", default="")
    bootstrap_record_p.add_argument("--catalog-number", default="")
    bootstrap_record_p.add_argument("--json", action="store_true")
    bootstrap_record_p.set_defaults(func=command_sale_item_bootstrap_record)

    bootstrap_records_p = projects_sub.add_parser(
        "sale-items-bootstrap-records-from-cohorts",
        help="Bootstrap record sale item projects from record child cohorts",
    )
    bootstrap_records_p.add_argument("packet")
    bootstrap_records_p.add_argument("--parent", default="records-for-sale")
    bootstrap_records_p.add_argument("--prefix", default="record")
    bootstrap_records_p.add_argument("--limit", type=int)
    bootstrap_records_p.add_argument("--only")
    bootstrap_records_p.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    bootstrap_records_p.add_argument("--prepare-photo-edit", action="store_true")
    bootstrap_records_p.add_argument("--appraisal-context", action="store_true")
    bootstrap_records_p.add_argument("--condition", action="store_true")
    bootstrap_records_p.add_argument("--listing-draft", action="store_true")
    bootstrap_records_p.add_argument("--json", action="store_true")
    bootstrap_records_p.set_defaults(func=command_sale_items_bootstrap_records_from_cohorts)

    prepare_p = projects_sub.add_parser("photo-edit-prepare", help="Prepare a Darktable editing workspace")
    prepare_p.add_argument("identifier")
    prepare_p.add_argument("--cohort")
    prepare_p.add_argument("--source")
    prepare_p.add_argument("--copy-mode", choices=["copy", "hardlink"], default="copy")
    prepare_p.add_argument("--json", action="store_true")
    prepare_p.set_defaults(func=command_photo_edit_prepare)

    add_source_p = projects_sub.add_parser("photo-edit-add-source", help="Add a supplemental cohort source")
    add_source_p.add_argument("identifier")
    add_source_p.add_argument("--packet")
    add_source_p.add_argument("--cohort")
    add_source_p.add_argument("--source")
    add_source_p.add_argument("--copy-mode", choices=["copy", "hardlink"], default="copy")
    add_source_p.add_argument("--dry-run", action="store_true")
    add_source_p.add_argument("--open", action="store_true")
    add_source_p.add_argument("--note", default="")
    add_source_p.add_argument("--json", action="store_true")
    add_source_p.set_defaults(func=command_photo_edit_add_source)

    sources_p = projects_sub.add_parser("photo-edit-sources", help="List photo edit sources")
    sources_p.add_argument("identifier")
    sources_p.add_argument("--json", action="store_true")
    sources_p.set_defaults(func=command_photo_edit_sources)

    source_p = projects_sub.add_parser("photo-edit-source", help="Inspect one photo edit source")
    source_p.add_argument("identifier")
    source_p.add_argument("source_id")
    source_p.add_argument("--json", action="store_true")
    source_p.set_defaults(func=command_photo_edit_source)

    open_p = projects_sub.add_parser("photo-edit-open", help="Open photo workspace in Darktable")
    open_p.add_argument("identifier")
    open_p.add_argument("--pending", action="store_true")
    open_p.set_defaults(func=command_photo_edit_open)

    role_p = projects_sub.add_parser("photo-edit-role", help="Assign a primary photo role")
    role_p.add_argument("identifier")
    role_p.add_argument("file")
    role_p.add_argument("role", choices=sorted(PHOTO_ROLES))
    role_p.add_argument("--note", default="")
    role_p.set_defaults(func=command_photo_edit_role)

    tag_p = projects_sub.add_parser("photo-edit-tag", help="Add descriptive tags to an image")
    tag_p.add_argument("identifier")
    tag_p.add_argument("file")
    tag_p.add_argument("tags", nargs="+")
    tag_p.set_defaults(func=command_photo_edit_tag)

    untag_p = projects_sub.add_parser("photo-edit-untag", help="Remove descriptive tags from an image")
    untag_p.add_argument("identifier")
    untag_p.add_argument("file")
    untag_p.add_argument("tags", nargs="+")
    untag_p.set_defaults(func=command_photo_edit_untag)

    tags_set_p = projects_sub.add_parser("photo-edit-tags-set", help="Replace all descriptive tags on an image")
    tags_set_p.add_argument("identifier")
    tags_set_p.add_argument("file")
    tags_set_p.add_argument("tags", nargs="+")
    tags_set_p.set_defaults(func=command_photo_edit_tags_set)

    tags_clear_p = projects_sub.add_parser("photo-edit-tags-clear", help="Clear descriptive tags from an image")
    tags_clear_p.add_argument("identifier")
    tags_clear_p.add_argument("file")
    tags_clear_p.set_defaults(func=command_photo_edit_tags_clear)

    tags_p = projects_sub.add_parser("photo-edit-tags", help="List photo-edit tags")
    tags_p.add_argument("identifier")
    tags_p.add_argument("--tag")
    tags_p.add_argument("--json", action="store_true")
    tags_p.set_defaults(func=command_photo_edit_tags)

    status_p = projects_sub.add_parser("photo-edit-status", help="Show photo editing status")
    status_p.add_argument("identifier")
    status_p.add_argument("--json", action="store_true")
    status_p.set_defaults(func=command_photo_edit_status)

    scan_p = projects_sub.add_parser("photo-edit-scan-exports", help="Register Darktable JPEG exports")
    scan_p.add_argument("identifier")
    scan_p.add_argument("--json", action="store_true")
    scan_p.set_defaults(func=command_photo_edit_scan_exports)

    for command, decision, handler in [
        ("photo-edit-approve", "approved", command_photo_edit_approve),
        ("photo-edit-reject", "rejected", command_photo_edit_reject),
    ]:
        parser = projects_sub.add_parser(command, help=f"Mark rendered images {decision}")
        parser.add_argument("identifier")
        parser.add_argument("files", nargs="+")
        parser.set_defaults(func=handler)

    verify_p = projects_sub.add_parser("photo-edit-verify", help="Verify approved listing photo set")
    verify_p.add_argument("identifier")
    verify_p.add_argument("--json", action="store_true")
    verify_p.set_defaults(func=command_photo_edit_verify)

    package_p = projects_sub.add_parser("photo-edit-package", help="Package approved listing photos")
    package_p.add_argument("identifier")
    package_p.add_argument("--json", action="store_true")
    package_p.set_defaults(func=command_photo_edit_package)

    listing_p = projects_sub.add_parser("sale-item-listing-package", help="Build a sale listing package")
    listing_p.add_argument("identifier")
    listing_p.add_argument("--json", action="store_true")
    listing_p.set_defaults(func=command_listing_package)


def emit(data, as_json=False) -> None:
    if as_json:
        print(json.dumps(data, indent=2))


def command_sale_item_init(args):
    item = init_sale_item(args.identifier, args.title, args.manufacturer, args.model, args.category, args.cohort, args.packet, args.cohort_export)
    if args.json:
        emit(item, True)
    else:
        print(f"Initialized sale item: {item['item_id']}")


def command_sale_item(args):
    item = load_sale_item(args.identifier)
    if args.json:
        emit(item, True)
    else:
        print(sale_item_markdown(item), end="")


def command_sale_item_update(args):
    updates = {key: value for key, value in vars(args).items() if key not in {"identifier", "func", "json"}}
    item = update_sale_item(args.identifier, **updates)
    if args.json:
        emit(item, True)
    else:
        print(f"Updated sale item: {item['item_id']}")


def command_sale_item_list(args):
    item = record_listing(args.identifier, args.channel, args.url, args.asking_price, args.note)
    print(f"Listed sale item: {item['item_id']}")


def print_listings(listings: list[dict]) -> None:
    print(f"{'channel':22} {'status':15} {'price':9} url")
    print(f"{'-' * 22} {'-' * 15} {'-' * 9} {'-' * 20}")
    for listing in listings:
        print(
            f"{listing.get('channel_name', ''):22} {listing.get('status', ''):15} "
            f"{listing.get('asking_price') or '-':9} {listing.get('url') or '-'}"
        )


def command_sale_item_listings(args):
    rows = load_sale_item(args.identifier).get("listings", [])
    emit(rows, True) if args.json else print_listings(rows)


def command_sale_item_listing(args):
    listing = find_listing(load_sale_item(args.identifier), args.listing_id)
    if args.json:
        emit(listing, True)
    else:
        print(json.dumps(listing, indent=2))


def command_sale_item_listing_update(args):
    item = update_listing(
        args.identifier, args.listing_id, args.status, args.url, args.asking_price,
        args.title, args.note, args.event,
    )
    print(f"Updated listing: {find_listing(item, args.listing_id)['listing_id']}")


def command_sale_item_listing_note(args):
    item = add_listing_note(args.identifier, args.listing_id, args.note)
    print(f"Noted listing: {find_listing(item, args.listing_id)['listing_id']}")


def command_sale_item_offer(args):
    offer = record_offer(args.identifier, args.listing_id, args.amount, args.buyer, args.note, args.status)
    print(f"Recorded offer: {offer['offer_id']} ${offer['amount']}")


def command_sale_item_offers(args):
    rows = load_sale_item(args.identifier).get("offers", [])
    if args.json:
        emit(rows, True)
        return
    print(f"{'offer':20} {'channel':22} {'status':10} {'amount':9} buyer")
    for offer in rows:
        print(
            f"{offer.get('offer_id', ''):20} {channel_preset(offer.get('channel', 'other'))['display_name']:22} "
            f"{offer.get('status', ''):10} {offer.get('amount') or '-':9} {offer.get('buyer') or '-'}"
        )


def command_sale_item_offer_update(args):
    offer = update_offer(args.identifier, args.offer_id, args.status, args.note)
    print(f"Updated offer: {offer['offer_id']} {offer['status']}")


def command_sale_item_crosspost_plan(args):
    plan = channel_recommendations(load_sale_item(args.identifier))
    if args.json:
        emit(plan, True)
        return
    for label, key in [("Recommended", "recommended"), ("Optional", "optional"), ("Not primary", "not_primary")]:
        if not plan[key]:
            continue
        print(f"{label}:")
        for row in plan[key]:
            state = f"; {row['current_status']}" if row.get("current_status") else ""
            print(f"  {row['display_name']}: {row['reason']}{state}")


def command_sale_item_channel_package(args):
    package = build_channel_package(args.identifier, args.channel)
    if args.json:
        emit(package, True)
    else:
        print(f"Channel package: {package['package_path']}")


def command_sale_item_channel_packages(args):
    packages = channel_packages(args.identifier)
    if args.json:
        emit(packages, True)
    elif packages:
        for package in packages:
            print(f"{package['channel']['display_name']}: {package['package_path']}")
    else:
        print("No channel packages.")


def command_sale_item_sold(args):
    item = record_sale(args.identifier, args.channel, args.sale_price, args.fees, args.shipping, args.buyer, args.note)
    print(f"Sold sale item: {item['item_id']} net {item['sale']['net_proceeds']}")


def command_sale_item_bootstrap(args):
    result = bootstrap_sale_item(args.identifier)
    if args.json:
        emit(result, True)
    else:
        print(f"Sale item tasks created: {len(result['created_tasks'])}")


def command_sale_item_bootstrap_record(args):
    item = bootstrap_record_sale_item(
        args.identifier, args.packet, args.cohort, args.artist, args.title,
        args.label, args.catalog_number,
    )
    if args.json:
        emit(item, True)
    else:
        print(f"Record sale item: {item['item_id']} - {item['title']}")


def _comma_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def command_sale_items_bootstrap_records_from_cohorts(args):
    result = bootstrap_record_sale_items_from_cohorts(
        args.packet,
        parent=args.parent,
        prefix=args.prefix,
        limit=args.limit,
        only=_comma_list(args.only),
        skip_existing=args.skip_existing,
        prepare_photo_edit_workspace=args.prepare_photo_edit,
        appraisal_context=args.appraisal_context,
        condition=args.condition,
        listing_draft=args.listing_draft,
    )
    if args.json:
        emit(result, True)
        return
    print(f"Record sale item projects bootstrapped: {len(result['created'])}")
    print(f"Skipped existing: {sum(1 for item in result['skipped'] if item.get('reason') == 'already exists')}")
    if result["created"]:
        print("\nCreated:")
        for item in result["created"]:
            print(f"  {item['project_id']}: {item['title']}")
    if result["skipped"]:
        print("\nSkipped:")
        for item in result["skipped"]:
            print(f"  {item['cohort_id']}: {item['reason']}")


def command_photo_edit_prepare(args):
    result = prepare_photo_edit(args.identifier, args.cohort, args.source, args.copy_mode)
    if args.json:
        emit(result, True)
    else:
        print(f"Workspace prepared: {result['manifest']['workspace_path']}")
        print(f"Copied: {result['copied']}  Existing: {result['existing']}")


def command_photo_edit_add_source(args):
    result = add_photo_edit_source(
        args.identifier,
        packet=args.packet,
        cohort=args.cohort,
        source=args.source,
        copy_mode=args.copy_mode,
        dry_run=args.dry_run,
        note=args.note,
    )
    if args.json:
        emit(result, True)
    else:
        print(f"Add source plan: {result['source']['source_id']}")
        print(f"New files: {result['new_count']}  Identical existing: {result['identical_count']}")
        if args.dry_run:
            print("Dry run: no changes made.")
        elif result.get("existing_source"):
            print("Source already present; no changes made.")
        else:
            print(f"Added: {result['added']}")
    if args.open and not args.dry_run:
        opened = open_photo_edit(args.identifier, pending=True)
        if opened["pending_filenames"]:
            print("Opened pending supplemental files for Darktable import; verify them in the existing library.")


def command_photo_edit_sources(args):
    sources = edit_sources(args.identifier)
    if args.json:
        emit(sources, True)
        return
    registry_module().print_rows(
        ["source_id", "packet_id", "cohort_id", "files", "added_at", "status"],
        [
            (
                source.get("source_id", ""),
                source.get("packet_id", ""),
                source.get("cohort_id", ""),
                source.get("file_count", 0),
                source.get("added_at", ""),
                source.get("status", ""),
            )
            for source in sources
        ],
    )


def command_photo_edit_source(args):
    detail = edit_source_detail(args.identifier, args.source_id)
    if args.json:
        emit(detail, True)
        return
    print(f"Source: {detail.get('source_id', '')}")
    print(f"Packet: {detail.get('packet_id', '')}")
    print(f"Cohort: {detail.get('cohort_id', '')}")
    print(f"Export: {detail.get('cohort_export_path', '')}")
    print(f"Images: {detail.get('image_count', 0)}")
    print(f"Import batch: {detail.get('import_batch_id', '')}")
    registry_module().print_rows(
        ["source_filename", "work_filename", "batch", "source", "work", "checksum"],
        [
            (
                image.get("source_filename", ""),
                image.get("work_filename", ""),
                image.get("import_batch_id", ""),
                "exists" if image.get("source_exists") else "missing",
                "exists" if image.get("work_exists") else "missing",
                "ok" if image.get("checksum_ok") else "mismatch",
            )
            for image in detail.get("images", [])
        ],
    )


def command_photo_edit_open(args):
    try:
        result = open_photo_edit(args.identifier, pending=getattr(args, "pending", False))
    except FileNotFoundError as exc:
        manifest = load_edit_manifest(args.identifier)
        raise SystemExit(f"Workspace: {manifest['workspace_path']}\nDarktable application problem: {exc}")
    print(f"Opened Darktable workspace: {result['workspace']}")
    if result["pending_filenames"]:
        print(
            f"Pending supplemental files: {len(result['pending_filenames'])}. "
            "They may need to be added to the existing Darktable library."
        )


def command_photo_edit_role(args):
    image = assign_role(args.identifier, args.file, args.role, args.note)
    print(f"{image['filename']}: {image['role']}")


def print_image_tags(prefix: str, image: dict) -> None:
    print(f"{prefix}: {image['filename']}")
    print(f"Tags: {', '.join(image.get('tags', [])) if image.get('tags') else '-'}")
    for tag in unknown_tags(image.get("tags", [])):
        print(f"Warning: unknown configured tag: {tag}")


def command_photo_edit_tag(args):
    try:
        image = update_image_tags(args.identifier, args.file, args.tags, "add")
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    print_image_tags("Tagged", image)


def command_photo_edit_untag(args):
    try:
        image = update_image_tags(args.identifier, args.file, args.tags, "remove")
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    print_image_tags("Updated tags", image)


def command_photo_edit_tags_set(args):
    try:
        image = update_image_tags(args.identifier, args.file, args.tags, "set")
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    print_image_tags("Set tags", image)


def command_photo_edit_tags_clear(args):
    try:
        image = update_image_tags(args.identifier, args.file, [], "clear")
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    print_image_tags("Cleared tags", image)


def command_photo_edit_tags(args):
    try:
        rows = photo_tag_summary(args.identifier, args.tag)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    if args.json:
        emit(rows, True)
        return
    registry_module().print_rows(
        ["tag", "approved", "files"],
        [(row["tag"], row["approved"], ", ".join(row["files"])) for row in rows],
    )


def command_photo_edit_status(args):
    data = edit_status_data(args.identifier)
    if args.json:
        emit(data, True)
        return
    manifest = data["manifest"]
    print(f"Photo Editing: {manifest['project_id']}")
    print(f"Sources: {data['source_count']}")
    print(f"Source images: {manifest['image_count']}")
    print(f"XMP sidecars: {data['xmp_count']}")
    print(f"Rendered exports: {manifest['exported_count']}")
    print(f"Existing approved: {manifest['approved_count']}")
    print(f"New unreviewed: {data['new_unreviewed']}")
    print(f"Rejected: {manifest.get('rejected_count', 0)}")
    print(f"Verification: {manifest['status'].replace('_', ' ')}")
    source_labels = {
        source.get("source_id"): (
            "original"
            if index == 0
            else str(source.get("cohort_id", "")).replace("cld-3080-", "") or f"source-{index + 1}"
        )
        for index, source in enumerate(manifest.get("sources", []))
    }
    registry_module().print_rows(
        ["filename", "source", "role", "tags", "xmp", "export", "review", "note"],
        [
            (
                image.get("work_filename", image.get("filename", "")),
                source_labels.get(image.get("source_id"), "-"),
                image.get("role") or "-",
                ",".join(normalize_tags(image.get("tags", []))) or "-",
                "yes" if Path(image["xmp_path"]).is_file() else "no",
                "yes" if image.get("export_path") and Path(image["export_path"]).is_file() else "no",
                image.get("review_status") or "-",
                image.get("note") or "-",
            )
            for image in manifest["images"]
        ],
    )


def command_photo_edit_scan_exports(args):
    result = scan_exports(args.identifier)
    if args.json:
        emit(result, True)
    else:
        print(f"Matched exports: {result['matched']}")
        print(f"Unmatched: {len(result['unmatched'])}  Duplicates: {len(result['duplicates'])}")


def command_photo_edit_approve(args):
    print(f"Approved: {len(review_images(args.identifier, args.files, 'approved'))}")


def command_photo_edit_reject(args):
    print(f"Rejected: {len(review_images(args.identifier, args.files, 'rejected'))}")


def command_photo_edit_verify(args):
    result = verify_photo_edit(args.identifier)
    if args.json:
        emit(result, True)
    else:
        print("Photo edit verification: " + ("ok" if result["success"] else "failed"))
        print(f"Profile: {result['profile']}")
        if result.get("coverage"):
            print("Coverage:")
            for role, state in result["coverage"].items():
                print(f"  {role}: {state}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
        if result["warnings"]:
            for warning in result["warnings"]:
                print(f"WARNING: {warning}")
        else:
            print("Warnings: none")
    if not result["success"]:
        raise SystemExit(2)


def command_photo_edit_package(args):
    try:
        result = package_photos(args.identifier)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    if args.json:
        emit(result, True)
    else:
        print(f"Listing photos packaged: {result['count']} -> {result['path']}")


def command_listing_package(args):
    result = build_listing_package(args.identifier)
    if args.json:
        emit(result, True)
    else:
        print(f"Listing package: {result['status']}")
        for field in result["missing_fields"]:
            print(f"Missing: {field}")
