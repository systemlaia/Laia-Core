# LAIA Grocy Architecture

Grocy is a LAIA operational state service. It tracks what needs attention now: inventory, household supplies, routines, batteries, chores, restock cycles, and check-in cycles.

LAIA packets remain the archival truth. Scans, OCR text, extraction sidecars, corrections, approvals, final records, and catalog entries stay in LAIA packet storage. Grocy should not become the system of record for receipts, documents, automotive paperwork, or scanner logs.

## What Belongs In Grocy

- Pantry inventory and expiring-soon checks
- Household supplies such as batteries, bulbs, and paper goods
- Workshop consumables such as filament, glue, blades, and PPE
- Vehicle check-ins for the Ranger, including oil, coolant, tires, registration, and insurance reminders
- Scanner maintenance cycles such as rollers, jam logs, and OCR quality sampling

## What Remains In LAIA Packets

- Original packet metadata
- Source images and OCR output
- Receipt extraction sidecars
- Human corrections
- Classification, review, approval, and finalization sidecars
- Catalog records

## Receipt Bridge

Future receipt extraction can suggest Grocy item updates, but only through explicit, reviewable commands. A receipt packet may produce candidate pantry or household items, quantities, prices, and restock hints. Those suggestions should be shown to the user before Grocy is changed.

## Automotive Paperwork

Vehicle paperwork should remain archived in LAIA packets. Grocy can track operational cycles for the Ranger: registration renewal, insurance review, oil checks, coolant checks, tire checks, and maintenance supply reminders.

## Safety Rule

No automatic Grocy writes from OCR without review. OCR and regex extraction are useful hints, not final truth. LAIA should require an explicit bridge command and a human approval step before writing operational state into Grocy.
