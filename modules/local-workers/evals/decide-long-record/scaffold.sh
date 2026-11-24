#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOF'
lines=[f"2026-10-11T09:{(i//60)%60:02d}:{i%60:02d}Z INFO http: GET /api/items/{i} 200 in {i%97+3}ms" for i in range(5200)]
lines.insert(2600,"2026-10-11T09:43:20Z ERROR db: connection refused to postgres:5432 (attempt 5/5), giving up")
open("app.log","w").write("\n".join(lines)+"\n")
EOF
