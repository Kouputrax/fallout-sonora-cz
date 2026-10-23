import csv
from pathlib import Path

INPUT = Path(r".\03_glossary\locked_terms_review_high.tsv")
OUT = Path(r".\03_glossary\review_items.tsv")

rows = []

with INPUT.open("r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        if row.get("category") == "item":
            rows.append(row)

rows.sort(key=lambda r: r.get("source_en", "").lower())

with OUT.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=reader.fieldnames,
        delimiter="\t"
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"Hotovo: {OUT}")
print(f"Itemu: {len(rows)}")
