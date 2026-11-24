#!/usr/bin/env bash
set -euo pipefail
cat > svc-a.md <<'DOC'
# Billing API
Owner: Priya Raman (payments team).
The service listens on port 8443. The legacy HTTP port 8080 was retired in 2025 and must not be used.
DOC
cat > svc-b.md <<'DOC'
# Search indexer
Owner: Tomás Ruiz (platform team).
Rebuilds the product index nightly at 02:00 UTC; a full rebuild takes about 40 minutes.
DOC
cat > svc-c.md <<'DOC'
# Notification relay
Owner: Mei Chen (growth team).
Fans out email and push notifications; retries a failed send three times with exponential backoff.
DOC
