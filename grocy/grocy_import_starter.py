#!/usr/bin/env python3
"""
Import Grocy starter master data from the workbook created in ChatGPT.

Reads these sheets from an .xlsx workbook:
- Locations
- Quantity Units
- Product Groups
- Stores
- Products

Then creates rows in Grocy via the generic object API.

Usage:
  python grocy_import_starter.py \
      --base-url http://homeassistant.local:9192 \
      --api-key YOUR_GROCY_API_KEY \
      --workbook grocy_starter_master_data.xlsx \
      --dry-run

  python grocy_import_starter.py \
      --base-url http://homeassistant.local:9192 \
      --api-key YOUR_GROCY_API_KEY \
      --workbook grocy_starter_master_data.xlsx

Notes:
- Create an API key in Grocy: wrench/menu -> Manage API keys.
- The script is idempotent by name where practical: it checks existing rows first.
- For products, it resolves referenced names (group, location, store, units) to IDs.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import openpyxl
import requests


ENTITY_ORDER = [
    ("locations", "Locations"),
    ("quantity_units", "Quantity Units"),
    ("product_groups", "Product Groups"),
    ("stores", "Stores"),
    ("products", "Products"),
]


@dataclass
class GrocyClient:
    base_url: str
    api_key: str
    timeout: int = 20
    dry_run: bool = False

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "GROCY-API-KEY": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get_objects(self, entity: str) -> List[Dict[str, Any]]:
        resp = self.session.get(self.url(f"/api/objects/{entity}"), timeout=self.timeout)
        self._raise_for_status(resp, f"GET objects/{entity}")
        data = resp.json()
        if not isinstance(data, list):
            raise RuntimeError(f"Expected list from /api/objects/{entity}, got: {type(data).__name__}")
        return data

    def create_object(self, entity: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.dry_run:
            print(f"[DRY RUN] POST /api/objects/{entity} -> {json.dumps(payload, ensure_ascii=False)}")
            return {"created_object_id": None, "dry_run": True}

        resp = self.session.post(
            self.url(f"/api/objects/{entity}"),
            timeout=self.timeout,
            data=json.dumps(payload, ensure_ascii=False),
        )
        self._raise_for_status(resp, f"POST objects/{entity} payload={payload}")
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "text": resp.text}

    @staticmethod
    def _raise_for_status(resp: requests.Response, context: str) -> None:
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            body = ""
            try:
                body = resp.text[:2000]
            except Exception:
                pass
            raise RuntimeError(f"{context} failed: {exc}\nResponse body:\n{body}") from exc


def sheet_rows(workbook_path: str, sheet_name: str) -> List[Dict[str, Any]]:
    wb = openpyxl.load_workbook(workbook_path, data_only=True)
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    output: List[Dict[str, Any]] = []

    for row in rows[1:]:
        if row is None:
            continue
        record = {}
        empty = True
        for key, value in zip(headers, row):
            if key == "":
                continue
            if value is not None and value != "":
                empty = False
            record[key] = value
        if not empty:
            output.append(record)

    return output


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def first_matching_id(rows: Iterable[Dict[str, Any]], field: str, value: str) -> Optional[int]:
    target = normalize_text(value).casefold()
    for row in rows:
        candidate = normalize_text(row.get(field)).casefold()
        if candidate == target:
            row_id = row.get("id")
            return int(row_id) if row_id is not None else None
    return None


def ensure_locations(client: GrocyClient, workbook_path: str) -> Dict[str, int]:
    source = sheet_rows(workbook_path, "Locations")
    existing = client.get_objects("locations")
    mapping: Dict[str, int] = {}

    for row in existing:
        name = normalize_text(row.get("name"))
        if name:
            mapping[name] = int(row["id"])

    for row in source:
        name = normalize_text(row.get("location_name"))
        if not name:
            continue
        if name in mapping:
            print(f"[SKIP] location exists: {name} (id={mapping[name]})")
            continue

        payload = {"name": name}
        result = client.create_object("locations", payload)
        print(f"[CREATE] location: {name}")
        # refresh mapping after create
        existing = client.get_objects("locations")
        loc_id = first_matching_id(existing, "name", name)
        if loc_id is None and not client.dry_run:
            raise RuntimeError(f"Could not find created location by name: {name}")
        if loc_id is not None:
            mapping[name] = loc_id

    return mapping


def ensure_quantity_units(client: GrocyClient, workbook_path: str) -> Dict[str, int]:
    source = sheet_rows(workbook_path, "Quantity Units")
    existing = client.get_objects("quantity_units")
    mapping: Dict[str, int] = {}

    for row in existing:
        name = normalize_text(row.get("name"))
        if name:
            mapping[name] = int(row["id"])

    for row in source:
        name = normalize_text(row.get("name"))
        if not name:
            continue
        if name in mapping:
            print(f"[SKIP] quantity unit exists: {name} (id={mapping[name]})")
            continue

        payload = {
            "name": name,
            "name_plural": normalize_text(row.get("name_plural")) or f"{name}s",
        }
        client.create_object("quantity_units", payload)
        print(f"[CREATE] quantity unit: {name}")

        existing = client.get_objects("quantity_units")
        qu_id = first_matching_id(existing, "name", name)
        if qu_id is None and not client.dry_run:
            raise RuntimeError(f"Could not find created quantity unit by name: {name}")
        if qu_id is not None:
            mapping[name] = qu_id

    return mapping


def ensure_product_groups(client: GrocyClient, workbook_path: str) -> Dict[str, int]:
    source = sheet_rows(workbook_path, "Product Groups")
    existing = client.get_objects("product_groups")
    mapping: Dict[str, int] = {}

    for row in existing:
        name = normalize_text(row.get("name"))
        if name:
            mapping[name] = int(row["id"])

    for row in source:
        name = normalize_text(row.get("group_name"))
        if not name:
            continue
        if name in mapping:
            print(f"[SKIP] product group exists: {name} (id={mapping[name]})")
            continue

        payload = {"name": name}
        client.create_object("product_groups", payload)
        print(f"[CREATE] product group: {name}")

        existing = client.get_objects("product_groups")
        group_id = first_matching_id(existing, "name", name)
        if group_id is None and not client.dry_run:
            raise RuntimeError(f"Could not find created product group by name: {name}")
        if group_id is not None:
            mapping[name] = group_id

    return mapping


def ensure_stores(client: GrocyClient, workbook_path: str) -> Dict[str, int]:
    source = sheet_rows(workbook_path, "Stores")
    existing = client.get_objects("stores")
    mapping: Dict[str, int] = {}

    for row in existing:
        name = normalize_text(row.get("name"))
        if name:
            mapping[name] = int(row["id"])

    for row in source:
        name = normalize_text(row.get("store_name"))
        if not name:
            continue
        if name in mapping:
            print(f"[SKIP] store exists: {name} (id={mapping[name]})")
            continue

        payload = {"name": name}
        client.create_object("stores", payload)
        print(f"[CREATE] store: {name}")

        existing = client.get_objects("stores")
        store_id = first_matching_id(existing, "name", name)
        if store_id is None and not client.dry_run:
            raise RuntimeError(f"Could not find created store by name: {name}")
        if store_id is not None:
            mapping[name] = store_id

    return mapping


def ensure_products(
    client: GrocyClient,
    workbook_path: str,
    locations: Dict[str, int],
    quantity_units: Dict[str, int],
    product_groups: Dict[str, int],
    stores: Dict[str, int],
) -> Dict[str, int]:
    source = sheet_rows(workbook_path, "Products")
    existing = client.get_objects("products")
    mapping: Dict[str, int] = {}

    for row in existing:
        name = normalize_text(row.get("name"))
        if name:
            mapping[name] = int(row["id"])

    for row in source:
        name = normalize_text(row.get("product_name"))
        if not name:
            continue
        if name in mapping:
            print(f"[SKIP] product exists: {name} (id={mapping[name]})")
            continue

        stock_unit_name = normalize_text(row.get("stock_unit"))
        purchase_unit_name = normalize_text(row.get("purchase_unit"))
        location_name = normalize_text(row.get("location_name"))
        group_name = normalize_text(row.get("group_name"))
        store_name = normalize_text(row.get("default_store"))

        qu_id_stock = quantity_units.get(stock_unit_name)
        qu_id_purchase = quantity_units.get(purchase_unit_name)
        location_id = locations.get(location_name)
        group_id = product_groups.get(group_name)
        store_id = stores.get(store_name) if store_name else None

        missing_refs = []
        if qu_id_stock is None:
            missing_refs.append(f"stock unit '{stock_unit_name}'")
        if qu_id_purchase is None:
            missing_refs.append(f"purchase unit '{purchase_unit_name}'")
        if location_id is None:
            missing_refs.append(f"location '{location_name}'")
        if group_id is None:
            missing_refs.append(f"group '{group_name}'")
        if store_name and store_id is None:
            missing_refs.append(f"store '{store_name}'")

        if missing_refs:
            raise RuntimeError(f"Cannot create product '{name}', missing references: {', '.join(missing_refs)}")

        payload: Dict[str, Any] = {
            "name": name,
            "description": normalize_text(row.get("description")),
            "location_id": location_id,
            "qu_id_stock": qu_id_stock,
            "qu_id_purchase": qu_id_purchase,
            "product_group_id": group_id,
            "min_stock_amount": row.get("min_stock") if row.get("min_stock") is not None else 0,
        }

        # Optional store field if your Grocy version exposes it
        if store_id is not None:
            payload["default_best_before_days_after_open"] = 0
            payload["shopping_location_id"] = store_id

        client.create_object("products", payload)
        print(f"[CREATE] product: {name}")

        existing = client.get_objects("products")
        product_id = first_matching_id(existing, "name", name)
        if product_id is None and not client.dry_run:
            raise RuntimeError(f"Could not find created product by name: {name}")
        if product_id is not None:
            mapping[name] = product_id

    return mapping


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Grocy starter workbook via Grocy API")
    parser.add_argument("--base-url", required=True, help="Grocy base URL, e.g. http://homeassistant.local:9192")
    parser.add_argument("--api-key", required=True, help="Grocy API key")
    parser.add_argument("--workbook", required=True, help="Path to grocy_starter_master_data.xlsx")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without creating anything")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = GrocyClient(
        base_url=args.base_url,
        api_key=args.api_key,
        dry_run=args.dry_run,
    )

    print("== Grocy starter import ==")
    print(f"Base URL: {client.base_url}")
    print(f"Workbook: {args.workbook}")
    print(f"Dry run: {client.dry_run}")
    print()

    locations = ensure_locations(client, args.workbook)
    quantity_units = ensure_quantity_units(client, args.workbook)
    product_groups = ensure_product_groups(client, args.workbook)
    stores = ensure_stores(client, args.workbook)
    products = ensure_products(
        client,
        args.workbook,
        locations=locations,
        quantity_units=quantity_units,
        product_groups=product_groups,
        stores=stores,
    )

    print()
    print("Import complete.")
    print(f"Locations: {len(locations)}")
    print(f"Quantity units: {len(quantity_units)}")
    print(f"Product groups: {len(product_groups)}")
    print(f"Stores: {len(stores)}")
    print(f"Products: {len(products)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
