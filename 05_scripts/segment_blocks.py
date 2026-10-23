import json
import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict
import uuid

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from file_categories import get_file_category

def main():
    parser = argparse.ArgumentParser(description="Segment JSONL into translation units.")
    parser.add_argument("--input", type=str, default=str(ROOT/"02_work"/"translated"/"sonora_translated.jsonl"))
    parser.add_argument("--out", type=str, default=str(ROOT/"02_work"/"translated"/"translation_units.jsonl"))
    parser.add_argument("--block-size", type=int, default=40)
    args = parser.parse_args()
    
    in_path = Path(args.input)
    out_path = Path(args.out)
    
    if not in_path.exists():
        print(f"File {in_path} not found.")
        return
        
    print(f"Loading {in_path}...")
    rows = []
    with open(in_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
                
    # Group by file
    files_map = defaultdict(list)
    for r in rows:
        files_map[r.get("file", "unknown")].append(r)
        
    valid_categories = {"dialog_npc", "dialog_scenery", "terminal", "quest"}
        
    units = []
    
    print("Segmenting into blocks...")
    for file_name, file_rows in files_map.items():
        norm_path = (file_name or "").replace("\\", "/").lower()
        cat = file_rows[0].get("file_category") or get_file_category(file_name, file_rows)

        # Dialogy a textové bloky; game/ řeší row-by-row překladač (Ollama/director)
        if not norm_path.startswith("dialog/") and "dialog" not in cat and cat not in valid_categories and "text" not in cat:
            continue
        # Sort by line_no or ID to ensure sequential flow
        file_rows.sort(key=lambda x: int(x.get("id", 0)) if str(x.get("id", "0")).isdigit() else 0)

        total_rows = len(file_rows)
        for i in range(0, total_rows, args.block_size):
            block = file_rows[i:i + args.block_size]
            
            # Context
            prev_ctx = file_rows[max(0, i-3):i]
            next_ctx = file_rows[i + args.block_size: min(total_rows, i + args.block_size + 3)]
            
            # Extract location code and NPC name from Sonora naming convention
            # e.g. "dialog/ACBoss.msg" → location="AC", npc="Boss"
            # e.g. "dialog/FCBishop.msg" → location="FC", npc="Bishop"
            base_name = os.path.basename(file_name).replace(".msg", "")
            loc_code = ""
            npc_name = base_name
            # First 2 uppercase chars = location prefix
            if len(base_name) >= 2 and base_name[0].isupper() and base_name[1].isupper():
                loc_code = base_name[:2]
                npc_name = base_name[2:]
            
            unit = {
                "unit_id": str(uuid.uuid4()),
                "location": loc_code,
                "npc_name": npc_name,
                "category": cat,
                "file": file_name,
                "ids": [r["id"] for r in block],
                "en_lines": [{"id": r["id"], "text": r["en"]} for r in block],
                "ru_lines": [{"id": r["id"], "text": r["ru"]} for r in block],
                "previous_context": [{"id": r["id"], "text": r["en"]} for r in prev_ctx],
                "next_context": [{"id": r["id"], "text": r["en"]} for r in next_ctx],
                "locked_terms": [],
                "tone_hint": "" 
            }
            units.append(unit)
            
    print(f"Created {len(units)} translation units.")
    with open(out_path, "w", encoding="utf-8") as f:
        for u in units:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
            
    print(f"Saved to {out_path}")

if __name__ == "__main__":
    main()
