# Delivery artifact lifecycle

Delivery creates logical artifacts under `.dx/`. `collab-state.py record` freezes each recorded artifact below `.dx/collab/runs/<run-id>/artifacts/` and records its logical path, immutable path, byte size, and SHA-256 in `run.json`.

`collab-artifact-publish.sh` resolves exactly one logical path through a completed success or failure run. It verifies the immutable source, verifies a temporary copy, rejects unsafe destinations, and only then atomically replaces the stable `.dx/` artifact.

Temporary files are internal and may be cleaned up. Immutable run artifacts are authoritative evidence. Stable `.dx/` files are the only operator-facing upload artifacts, and are printed with run ID, size, and SHA-256. Generated `.dx/` files are not committed.
