---
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill]
---

Use the local decision model to label every review in reviews.jsonl with its sentiment (positive or negative) and its language (English or Spanish), then give me the totals for each sentiment and each language.
