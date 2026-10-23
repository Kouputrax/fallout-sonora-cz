import csv
from pathlib import Path
from collections import Counter

ROOT = Path(".")
INPUT = ROOT / "03_glossary" / "locked_terms_candidates.tsv"
OUT = ROOT / "03_glossary" / "locked_terms_review_high.tsv"

KEEP_CATEGORIES = {
    "item",
    "location",
    "quest",
    "skill",
    "stat",
    "trait",
    "perk",
    "inventory_ui",
    "ui_skilldex",
    "proto_system",
}

if not INPUT.exists():
    raise SystemExit(f"Missing input file: {INPUT}")

rows = []

with INPUT.open("r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        category = (row.get("category") or "").strip()
        source_en = (row.get("source_en") or "").strip()

        if category not in KEEP_CATEGORIES:
            continue

        if not source_en:
            continue

        rows.append(row)

rows.sort(key=lambda r: (
    r.get("category", ""),
    r.get("source_en", "").lower()
))

OUT.parent.mkdir(parents=True, exist_ok=True)

with OUT.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "category",
            "priority",
            "source_en",
            "target_cs_locked",
            "file",
            "id",
            "ru_context",
            "decision",
            "notes",
        ],
        delimiter="\t",
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"Hotovo: {OUT}")
print(f"Radku pro review: {len(rows)}")

counts = Counter(r.get("category", "") for r in rows)
print()
print("Kategorie:")
for category, count in sorted(counts.items()):
    print(f"  {category}: {count}")
