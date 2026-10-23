import os
import sys
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT / "05_scripts"))

from sonora_msg_pipeline import load_jsonl

BENCHMARK_DIR = ROOT / "02_work" / "benchmark"
REPORT_FILE = ROOT / "06_output" / "benchmark_report.md"

def evaluate_model(model_file: Path) -> dict:
    if not model_file.exists():
        return None
        
    rows = load_jsonl(model_file)
    
    stats = {
        "total": len(rows),
        "json_broken": 0,
        "cyrillic": 0,
        "false_friends": 0,
        "gender_issues": 0,
        "glossary_fails": 0,
        "empty": 0
    }
    
    # Regex for cyrillic
    cyrillic_re = re.compile(r'[А-Яа-я]')
    
    for r in rows:
        cs = r.get("cs", "")
        en = r.get("en", "")
        cat = r.get("file_category", "")
        
        if not cs.strip():
            stats["empty"] += 1
            continue
            
        if cyrillic_re.search(cs):
            stats["cyrillic"] += 1
            
        # False friends check
        en_lower = en.lower()
        cs_lower = cs.lower()
        
        if "on fire" in en_lower and "palb" in cs_lower:
            stats["false_friends"] += 1
            
        # Glossary check (caps -> zátky, not víčka)
        if "caps" in en_lower and ("víčk" in cs_lower or "víček" in cs_lower):
            stats["glossary_fails"] += 1
            
        # Gender check in combat messages (zasáhla/zasáhl instead of zasahuješ/zásah)
        if cat.startswith("game") and ("hit yourself" in en_lower or "you see" in en_lower):
            if "jsi" in cs_lower or "zasáhla" in cs_lower or "zasáhl " in cs_lower or "ztratil " in cs_lower or "ztratila " in cs_lower:
                stats["gender_issues"] += 1
                
    return stats

def main():
    print("Evaluating models...")
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    results = {}
    for f in BENCHMARK_DIR.glob("results_*.jsonl"):
        model_name = f.stem.replace("results_", "")
        stats = evaluate_model(f)
        if stats:
            results[model_name] = stats
            
    if not results:
        print("No benchmark results found.")
        return
        
    md = [
        "# Benchmark Report",
        "",
        "| Model | Total | Empty | Cyrillic | False Friends | Glossary Fails | Gender Issues |",
        "|---|---|---|---|---|---|---|"
    ]
    
    for model, s in sorted(results.items()):
        row = f"| {model} | {s['total']} | {s['empty']} | {s['cyrillic']} | {s['false_friends']} | {s['glossary_fails']} | {s['gender_issues']} |"
        md.append(row)
        
    md.append("\n## Hodnocení kritérií")
    md.append("- **Empty:** Model nevrátil překlad (JSON parsing chyba nebo timeout).")
    md.append("- **Cyrillic:** Výstup obsahuje azbuku (halucinace z RU kontextu).")
    md.append("- **False Friends:** Špatný překlad `on fire` jako `v palbě` apod.")
    md.append("- **Glossary Fails:** Model použil špatný termín (`caps` -> `víčka`).")
    md.append("- **Gender Issues:** Model použil rodově zabarvená slovesa v neutrálních game zprávách.")
    
    REPORT_FILE.write_text("\n".join(md), encoding="utf-8")
    print(f"Report generated: {REPORT_FILE}")

if __name__ == "__main__":
    main()
