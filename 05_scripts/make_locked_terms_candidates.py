import json
import csv
import re
from pathlib import Path

ROOT = Path(r".")
INPUT = ROOT / "02_work" / "export" / "sonora_export.jsonl"
OUT = ROOT / "03_glossary" / "locked_terms_candidates.tsv"

CATEGORY_BY_FILE = {
    "quests.msg": "quest",
    "worldmap.msg": "location",
    "map.msg": "location",
    "skill.msg": "skill",
    "skilldex.msg": "ui_skilldex",
    "stat.msg": "stat",
    "trait.msg": "trait",
    "perk.msg": "perk",
    "proto.msg": "proto_system",
    "inventry.msg": "inventory_ui",
    "item.msg": "item_ui",
    "pipboy.msg": "pipboy_ui",
    "combat.msg": "combat_ui",
    "scrname.msg": "script_object_npc",
}

def guess_category(file_name: str) -> str:
    base = Path(file_name).name.lower()

    if base in CATEGORY_BY_FILE:
        return CATEGORY_BY_FILE[base]

    if base.startswith("pro_item"):
        return "item"
    if base.startswith("pro_crit"):
        return "critter_npc"
    if base.startswith("pro_scen"):
        return "scenery_object"
    if base.startswith("pro_wall"):
        return "wall_object"
    if base.startswith("pro_tile"):
        return "tile_object"

    return "other_game"

def is_candidate(row: dict) -> bool:
    file = row.get("file", "")
    en = (row.get("en") or "").strip()

    if not file.lower().startswith("game/"):
        return False

    if not en:
        return False

    # Skip pure punctuation / numbers.
    if re.fullmatch(r"[\d\s\-\+\.,:%/()xX]+", en):
        return False

    # Skip obvious debug/error lines for now.
    if en.lower().startswith("error:"):
        return False

    # Long help prose is usually not a locked term.
    # Quest/location names are exceptions.
    if len(en) > 90 and Path(file).name.lower() not in {"quests.msg", "worldmap.msg"}:
        return False

    return True

def priority_for(category: str, en: str) -> str:
    high = {
        "item",
        "quest",
        "location",
        "skill",
        "stat",
        "trait",
        "perk",
        "inventory_ui",
        "pipboy_ui",
        "ui_skilldex",
        "proto_system",
    }

    if category in high:
        return "high"

    if category in {"script_object_npc", "critter_npc", "scenery_object"}:
        return "medium"

    return "low"

rows = []
seen = set()

if not INPUT.exists():
    raise SystemExit(f"Missing input file: {INPUT}")

with INPUT.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue

        row = json.loads(line)

        if not is_candidate(row):
            continue

        file = row.get("file", "")
        en = (row.get("en") or "").strip()
        ru = (row.get("ru") or "").strip()
        category = guess_category(file)

        key = (category, en.lower())
        if key in seen:
            continue

        seen.add(key)

        rows.append({
            "category": category,
            "priority": priority_for(category, en),
            "source_en": en,
            "target_cs_locked": "",
            "file": file,
            "id": row.get("id", ""),
            "ru_context": ru,
            "decision": "todo",
            "notes": "",
        })

rows.sort(key=lambda r: (r["category"], r["priority"], r["source_en"].lower()))

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
print(f"Kandidatu: {len(rows)}")
