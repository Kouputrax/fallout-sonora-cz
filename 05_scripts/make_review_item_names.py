import csv
from pathlib import Path

INPUT = Path(r".\03_glossary\review_items.tsv")
OUT = Path(r".\03_glossary\review_item_names.tsv")

rows = []

with INPUT.open("r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    fieldnames = reader.fieldnames

    for row in reader:
        try:
            item_id = int(str(row.get("id", "")).strip())
        except ValueError:
            continue

        # Fallout-style pro_item.msg:
        # usually xxx00 = item name, xxx01 = item description
        if item_id % 100 != 0:
            continue

        source = (row.get("source_en") or "").strip()

        if not source:
            continue

        rows.append(row)

rows.sort(key=lambda r: int(str(r.get("id", "0")).strip()))

with OUT.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)

print(f"Hotovo: {OUT}")
print(f"Nazvu itemu: {len(rows)}")
