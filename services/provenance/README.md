# LAIA Provenance Service

Purpose:
Track actions performed through LAIA services.

Phase 2 scope:
- Log packet creation
- Log workflow submission
- Log generation results
- Link outputs to packet IDs

Rules:
- Every generated artifact needs a source packet.
- Every action should be auditable.
- Logs should be markdown + JSON when possible.
