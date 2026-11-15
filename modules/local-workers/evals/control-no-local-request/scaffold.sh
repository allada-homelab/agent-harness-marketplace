#!/usr/bin/env bash
set -euo pipefail
cat > svc-a.md <<'EOF'
# Billing API
Owner: Priya Raman (payments team).
The service listens on port 8443. The legacy HTTP port 8080 was retired in 2025 and must not be used.
EOF
