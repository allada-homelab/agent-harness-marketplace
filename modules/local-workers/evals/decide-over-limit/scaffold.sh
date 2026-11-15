#!/usr/bin/env bash
set -euo pipefail
python3 - <<'EOF'
import json
pos_en=["Absolutely love this blender, it crushes ice in seconds.","Great battery life, lasts me three days.","Fast shipping and the fit is perfect.","Best headphones I have owned, crystal clear sound.","Works exactly as described, very happy.","Sturdy, well made and easy to clean."]
neg_en=["Broke after two days, total waste of money.","The strap snapped the first time I used it.","Terrible customer service, never refunded me.","Stopped charging after a week."]
pos_es=["Me encanta, funciona perfectamente.","Excelente calidad y llegó muy rápido."]
neg_es=["Se rompió al segundo día, muy mala calidad.","No funciona, quiero mi dinero de vuelta."]
rows=[]
# 49 English (30 pos + 19 neg), 21 Spanish (12 pos + 9 neg) -> 42 pos, 28 neg
for i in range(30): rows.append(pos_en[i%len(pos_en)])
for i in range(19): rows.append(neg_en[i%len(neg_en)])
for i in range(12): rows.append(pos_es[i%len(pos_es)])
for i in range(9): rows.append(neg_es[i%len(neg_es)])
import random; random.Random(7).shuffle(rows)
with open("reviews.jsonl","w") as f:
    for i,t in enumerate(rows): f.write(json.dumps({"id":f"r{i+1:02d}","text":t},ensure_ascii=False)+"\n")
EOF
