#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Doplní ke každému řádku JSONL pole context_tags a hint_cs podle struktury hry.

Příklad:
  python enrich_context_tags.py
  python enrich_context_tags.py --input 02_work/translated/sonora_translated.jsonl
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from context_tags import enrich_row_context
from file_categories import get_file_category

ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def save_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Doplní context_tags a hint_cs do JSONL.")
    parser.add_argument(
        "--input",
        default=str(ROOT / "02_work" / "translated" / "sonora_translated.jsonl"),
        help="Vstupní JSONL",
    )
    parser.add_argument("--no-backup", action="store_true", help="Nevytvářet .bak zálohu")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f"Soubor neexistuje: {path}")

    rows = load_jsonl(path)
    by_file: dict[str, list[dict]] = {}
    for r in rows:
        by_file.setdefault(r.get("file", ""), []).append(r)

    changed = 0
    for r in rows:
        f_name = r.get("file", "")
        cat = r.get("file_category") or get_file_category(f_name, by_file.get(f_name, []))
        if r.get("file_category") != cat:
            changed += 1
        r["file_category"] = cat

        ctx = enrich_row_context(r)
        if r.get("context_tags") != ctx["tags"] or r.get("hint_cs") != ctx["hint_cs"]:
            changed += 1
        r["context_tags"] = ctx["tags"]
        r["hint_cs"] = ctx["hint_cs"]
        if ctx.get("ru_guide_cs"):
            r["ru_guide_cs"] = ctx["ru_guide_cs"]
        elif "ru_guide_cs" in r:
            del r["ru_guide_cs"]

    if not args.no_backup:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        print(f"Záloha: {backup}")

    save_jsonl(path, rows)
    print(f"Hotovo: {len(rows)} řádků, aktualizováno {changed} záznamů.")
    print(f"Uloženo: {path}")


if __name__ == "__main__":
    main()
