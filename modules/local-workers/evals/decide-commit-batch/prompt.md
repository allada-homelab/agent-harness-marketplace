---
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill]
---

Ask the local decision model to label each commit message with its conventional-commit type (feat, fix, docs or chore) and whether it is a breaking change:
1. Add CSV export to the reports page
2. Fix crash when the cart is empty
3. Document the rate-limit headers in API.md
4. Bump eslint from 9.1 to 9.2
5. Drop support for Python 3.9; the minimum is now 3.11
6. Rename the user_id query parameter to account_id in the public API
