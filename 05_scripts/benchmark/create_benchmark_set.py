import os
import sys
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT / "05_scripts"))

from sonora_msg_pipeline import load_jsonl
from file_categories import get_file_category

EXPORT_FILE = ROOT / "02_work" / "export" / "sonora_export.jsonl"
BENCHMARK_FILE = ROOT / "02_work" / "benchmark" / "test_set.jsonl"

def main():
    print(f"Loading export file: {EXPORT_FILE}")
    if not EXPORT_FILE.exists():
        print("Error: Export file not found.")
        sys.exit(1)
        
    rows = load_jsonl(EXPORT_FILE)
    
    # Categorize
    by_file = {}
    for r in rows:
        f_name = r.get("file", "")
        if f_name not in by_file:
            by_file[f_name] = []
        by_file[f_name].append(r)

    file_categories = {}
    for f_name, f_rows in by_file.items():
        file_categories[f_name] = get_file_category(f_name, f_rows)

    for r in rows:
        r["file_category"] = file_categories.get(r.get("file", ""), "dialog_scenery")

    dialog_npc_rows = []
    dialog_scenery_rows = []
    game_rows = []
    
    problematic_keywords = ["on fire", "caps", "geiger counter", "spanish", "hit yourself", "you see", "gold"]
    problematic_rows = []
    
    for r in rows:
        en = r.get("en", "")
        if not en.strip(): continue
        
        en_lower = en.lower()
        is_problematic = any(kw in en_lower for kw in problematic_keywords)
        
        if is_problematic and len(problematic_rows) < 20:
            problematic_rows.append(r)
            continue
            
        cat = r["file_category"]
        if cat == "dialog_npc":
            dialog_npc_rows.append(r)
        elif cat == "dialog_scenery":
            dialog_scenery_rows.append(r)
        elif cat.startswith("game"):
            game_rows.append(r)
            
    # Deterministic randomness for consistent benchmarking if we re-run
    random.seed(42)
    random.shuffle(dialog_npc_rows)
    random.shuffle(dialog_scenery_rows)
    random.shuffle(game_rows)
    
    final_set = []
    final_set.extend(dialog_npc_rows[:50])
    final_set.extend(dialog_scenery_rows[:50])
    final_set.extend(game_rows[:50])
    final_set.extend(problematic_rows[:20])
    
    # Save
    BENCHMARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with BENCHMARK_FILE.open("w", encoding="utf-8", newline="\n") as f:
        for r in final_set:
            r["cs"] = ""
            r["status"] = "new"
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            
    print(f"Benchmark test set created: {BENCHMARK_FILE}")
    print(f"Total rows: {len(final_set)}")
    print(f" - dialog_npc: {min(len(dialog_npc_rows), 50)}")
    print(f" - dialog_scenery: {min(len(dialog_scenery_rows), 50)}")
    print(f" - game/combat: {min(len(game_rows), 50)}")
    print(f" - problematic: {len(problematic_rows)}")

if __name__ == "__main__":
    main()
