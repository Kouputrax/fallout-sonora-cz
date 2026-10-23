#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
align_classic_translations.py

Párování herních řádků Sonory s oficiálními CZ překlady z F2, Nevada a F1.
Před přijetím shody platí stejná pravidla jako u QA / context_tags (COMBAT rod, QA).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from alignment_rules import postprocess_aligned_cs, validate_alignment_candidate

FORBIDDEN_T3_FILES = {"COMBAT.MSG", "MISC.MSG", "PRO_CRIT.MSG"}

REFERENCE_SOURCES: list[tuple[str, Path, Path]] = [
    (
        "F2",
        ROOT / "04_reference" / "fallout2_en" / "text" / "english" / "game",
        ROOT / "04_reference" / "fallout2_cz" / "text" / "english" / "game",
    ),
    (
        "Nevada",
        ROOT / "04_reference" / "nevada_en" / "text" / "english" / "game",
        ROOT / "04_reference" / "nevada_cz" / "text" / "english" / "game",
    ),
    (
        "F1",
        ROOT / "04_reference" / "fallout1_en" / "TEXT" / "ENGLISH" / "GAME",
        ROOT / "04_reference" / "fallout1_cz" / "TEXT" / "ENGLISH" / "GAME",
    ),
]


def parse_msg_file(path: Path, is_cz: bool = False) -> dict[str, str]:
    if not path.exists():
        return {}

    data = path.read_bytes()
    encodings = ["cp1250", "utf-8", "latin-1"] if is_cz else ["utf-8-sig", "utf-8", "latin-1"]
    content = ""
    for enc in encodings:
        try:
            content = data.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if not content:
        content = data.decode("latin-1", errors="replace")

    rows: dict[str, str] = {}
    msg_line_start_re = re.compile(r"^\s*\{")

    def parse_brace_group(line: str, start: int):
        n = len(line)
        while start < n and line[start].isspace():
            start += 1
        if start >= n or line[start] != "{":
            return None
        i = start + 1
        chars = []
        while i < n:
            ch = line[i]
            if ch == "}":
                return "".join(chars), i + 1
            chars.append(ch)
            i += 1
        return None

    for line in content.splitlines():
        if not msg_line_start_re.match(line):
            continue
        line_no_newline = line.rstrip("\r\n")
        idx = 0
        while idx < len(line_no_newline) and line_no_newline[idx].isspace():
            idx += 1

        g1 = parse_brace_group(line_no_newline, idx)
        if not g1:
            continue
        msg_id, pos = g1

        g2 = parse_brace_group(line_no_newline, pos)
        if not g2:
            continue
        _, pos = g2

        g3 = parse_brace_group(line_no_newline, pos)
        if not g3:
            continue
        text, _ = g3

        rows[msg_id.strip()] = text
    return rows


class ReferenceIndex:
    def __init__(self, name: str, en_dir: Path, cz_dir: Path) -> None:
        self.name = name
        self.en_dir = en_dir
        self.cz_dir = cz_dir
        self.en_data: dict[str, dict[str, str]] = {}
        self.cz_data: dict[str, dict[str, str]] = {}
        self.file_en_to_cz: dict[tuple[str, str], str] = {}
        self.global_en_to_cz: dict[str, tuple[str, str, str]] = {}
        self.loaded = False

    def load(self) -> bool:
        if not self.en_dir.exists() or not self.cz_dir.exists():
            return False

        en_files = {f.name.upper(): f for f in self.en_dir.glob("*.msg")}
        en_files.update({f.name.upper(): f for f in self.en_dir.glob("*.MSG")})
        cz_files = {f.name.upper(): f for f in self.cz_dir.glob("*.msg")}
        cz_files.update({f.name.upper(): f for f in self.cz_dir.glob("*.MSG")})

        for name_upper, path_en in en_files.items():
            path_cz = cz_files.get(name_upper)
            if not path_cz:
                continue

            en_rows = parse_msg_file(path_en, is_cz=False)
            cz_rows = parse_msg_file(path_cz, is_cz=True)
            self.en_data[name_upper] = en_rows
            self.cz_data[name_upper] = cz_rows

            for msg_id, en_text in en_rows.items():
                cz_text = cz_rows.get(msg_id)
                if not cz_text or not cz_text.strip():
                    continue
                norm_en = en_text.strip().lower()
                if not norm_en:
                    continue

                self.file_en_to_cz[(name_upper, norm_en)] = cz_text

                if name_upper in FORBIDDEN_T3_FILES:
                    continue

                word_count = len(norm_en.split())
                has_variable = "%" in norm_en
                is_valid_t3 = False
                if re.search(r"[a-zA-Z]", norm_en):
                    if len(norm_en) >= 15:
                        is_valid_t3 = True
                    elif has_variable and len(norm_en) >= 15:
                        is_valid_t3 = True

                if is_valid_t3 and norm_en not in self.global_en_to_cz:
                    self.global_en_to_cz[norm_en] = (cz_text, name_upper, msg_id)

        self.loaded = True
        return True


def load_config() -> dict[str, Any]:
    cfg_path = ROOT / "05_scripts" / "pipeline_config.json"
    default_config = {"translated_file": "02_work/translated/sonora_translated.jsonl"}
    if cfg_path.exists():
        try:
            with cfg_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_config


def try_tier1(index: ReferenceIndex, base_name: str, msg_id: str, norm_en: str) -> str | None:
    if base_name not in index.en_data or base_name not in index.cz_data:
        return None
    en_ref_rows = index.en_data[base_name]
    cz_ref_rows = index.cz_data[base_name]
    if msg_id not in en_ref_rows:
        return None
    ref_en = en_ref_rows[msg_id]
    if norm_en != ref_en.strip().lower():
        return None
    cz_ref = cz_ref_rows.get(msg_id)
    if cz_ref and cz_ref.strip():
        return cz_ref
    return None


def try_tier2(index: ReferenceIndex, base_name: str, norm_en: str) -> str | None:
    cz_ref = index.file_en_to_cz.get((base_name, norm_en))
    if not cz_ref or not cz_ref.strip():
        return None
    word_count = len(norm_en.split())
    has_variable = "%" in norm_en
    if len(norm_en) >= 10 or has_variable or word_count >= 3:
        return cz_ref
    return None


def try_tier3(index: ReferenceIndex, norm_en: str) -> tuple[str, str, str] | None:
    val = index.global_en_to_cz.get(norm_en)
    if not val:
        return None
    cz_ref, f_file, f_id = val
    if cz_ref and cz_ref.strip():
        return cz_ref, f_file, f_id
    return None


def find_best_match(
    row: dict[str, Any],
    indexes: list[ReferenceIndex],
    base_name: str,
    msg_id: str,
    norm_en: str,
    en_text: str,
) -> dict[str, Any] | None:
    for index in indexes:
        cz = try_tier1(index, base_name, msg_id, norm_en)
        if cz:
            val = validate_alignment_candidate(row, cz, match_tier=1, source_game=index.name)
            if val["accepted"]:
                return {
                    "tier": 1,
                    "source": index.name,
                    "ref_file": base_name,
                    "ref_id": msg_id,
                    "ref_en": en_text,
                    **val,
                }

    for index in indexes:
        cz = try_tier2(index, base_name, norm_en)
        if cz:
            val = validate_alignment_candidate(row, cz, match_tier=2, source_game=index.name)
            if val["accepted"]:
                return {
                    "tier": 2,
                    "source": index.name,
                    "ref_file": base_name,
                    "ref_id": "?",
                    "ref_en": en_text,
                    **val,
                }

    for index in indexes:
        t3 = try_tier3(index, norm_en)
        if t3:
            cz, f_file, f_id = t3
            val = validate_alignment_candidate(row, cz, match_tier=3, source_game=index.name)
            if val["accepted"]:
                return {
                    "tier": 3,
                    "source": index.name,
                    "ref_file": f_file,
                    "ref_id": f_id,
                    "ref_en": en_text,
                    **val,
                }

    return None


def _parse_align_meta(notes: str) -> tuple[int, str]:
    tier = 2
    source = "F2"
    m = re.search(r"Tier (\d)", notes or "")
    if m:
        tier = int(m.group(1))
    m2 = re.search(r"Aligned from (\w+)", notes or "")
    if m2:
        source = m2.group(1)
    return tier, source


def reapply_alignment_fixes(db_path: Path) -> None:
    """Aplikuje postprocess_aligned_cs na existující aligned řádky a přepočítá status."""
    print("==================================================")
    print(" SONORA — RE-APLIKACE AUTO-OPRAV (aligned řádky) ")
    print("==================================================")

    rows: list[dict[str, Any]] = []
    with db_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    changed_cs = 0
    upgraded = 0
    fix_counts: dict[str, int] = {}

    for r in rows:
        status = r.get("status") or ""
        if not status.startswith("aligned_"):
            continue
        cs = r.get("cs") or ""
        en = r.get("en") or ""
        if not cs.strip():
            continue

        tier, source = _parse_align_meta(r.get("notes") or "")
        val = validate_alignment_candidate(r, cs, match_tier=tier, source_game=source)
        if not val.get("accepted") and val.get("cs") == cs:
            continue

        new_cs = val.get("cs", cs)
        auto_fixes = val.get("auto_fixes") or []
        old_status = status

        if new_cs != cs:
            changed_cs += 1
            for fx in auto_fixes:
                fix_counts[fx] = fix_counts.get(fx, 0) + 1

        r["cs"] = new_cs
        if val.get("status"):
            r["status"] = val["status"]
            if old_status == "aligned_review" and val["status"] == "aligned_confirmed":
                upgraded += 1

        issues = val.get("issues") or []
        r["warnings"] = issues
        if auto_fixes:
            r["auto_fixes"] = auto_fixes
            note = val.get("note") or r.get("notes") or ""
            if "auto-fix:" not in note:
                r["notes"] = note + f"; auto-fix: {','.join(auto_fixes)}"
            else:
                r["notes"] = note

    print(f"Upraveno CS textu:                   {changed_cs}")
    print(f"Review → confirmed:                  {upgraded}")
    if fix_counts:
        print("Aplikované opravy:")
        for name, cnt in sorted(fix_counts.items(), key=lambda x: -x[1]):
            print(f"  * {name}: {cnt}")
    print("--------------------------------------------------")

    if changed_cs or upgraded:
        backup_path = db_path.with_suffix(".jsonl.bak_reapply")
        print(f"Záloha: {backup_path.name}")
        shutil.copy2(db_path, backup_path)
        temp_file = db_path.with_suffix(".jsonl.tmp")
        with temp_file.open("w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if db_path.exists():
            db_path.unlink()
        temp_file.rename(db_path)
        print("Uloženo.")
    else:
        print("Žádné změny.")


def main() -> None:
    print("==================================================")
    print(" SONORA — PÁROVÁNÍ S F1 / F2 / NEVADA (+ pravidla) ")
    print("==================================================")

    config = load_config()
    db_path = ROOT / config.get("translated_file", "02_work/translated/sonora_translated.jsonl")
    if not db_path.exists():
        print(f"ERROR: Databazovy soubor {db_path} neexistuje.")
        return

    indexes: list[ReferenceIndex] = []
    for name, en_dir, cz_dir in REFERENCE_SOURCES:
        idx = ReferenceIndex(name, en_dir, cz_dir)
        if idx.load():
            n_files = len(idx.en_data)
            print(f"  [{name}] OK — {n_files} souborů")
            indexes.append(idx)
        else:
            print(f"  [{name}] přeskočeno (chybí {en_dir} nebo {cz_dir})")

    if not indexes:
        print("ERROR: Žádný referenční zdroj není k dispozici.")
        return

    print("Načítám databázi překladů...")
    rows: list[dict] = []
    with db_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    print(f"  Celkem v databázi: {len(rows)} řádků.")

    t1_count = t2_count = t3_count = 0
    rejected_rules = 0
    skipped_manually_translated = 0
    unmatched = 0
    total_game_rows = 0
    by_source: dict[str, int] = {}

    audit_path = ROOT / "02_work" / "translated" / "alignment_audit.tsv"
    with audit_path.open("w", encoding="utf-8") as audit_f:
        audit_f.write(
            "sonora_file\tsonora_id\tsonora_en\tsource\tref_file\tref_id\tref_en\tcs\ttier\tstatus\tissues\n"
        )

        print("\nSpouštím zarovnávací algoritmus (s QA pravidly)...")

        for r in rows:
            f_name = r.get("file", "")
            is_game = f_name.lower().startswith("game/") or str(r.get("file_category", "")).startswith("game_")
            if not is_game:
                continue

            total_game_rows += 1
            en_text = r.get("en", "")
            norm_en = en_text.strip().lower()
            if not norm_en:
                continue

            cs_text = r.get("cs", "") or ""
            status = r.get("status", "new")
            if status != "new" and cs_text.strip():
                skipped_manually_translated += 1
                continue

            base_name = os.path.basename(f_name).upper()
            msg_id = str(r.get("id", ""))

            # Kolik kandidátů by prošlo bez pravidel vs. kolik odmítlo pravidlo
            had_raw = False
            for index in indexes:
                if try_tier1(index, base_name, msg_id, norm_en) or try_tier2(index, base_name, norm_en) or try_tier3(index, norm_en):
                    had_raw = True
                    break

            match = find_best_match(r, indexes, base_name, msg_id, norm_en, en_text)

            if not match and had_raw:
                rejected_rules += 1

            if match:
                matched_cz = match["cs"]
                match_tier = match["tier"]
                source = match["source"]
                ref_file = match["ref_file"]
                ref_id = match["ref_id"]
                ref_en = match["ref_en"]
                issues = match.get("issues") or []
                auto_fixes = match.get("auto_fixes") or []

                r["cs"] = match["cs"]
                r["status"] = match["status"]
                r["notes"] = match["note"]
                if auto_fixes:
                    r["auto_fixes"] = auto_fixes
                if "warnings" in r:
                    r["warnings"] = issues

                audit_f.write(
                    f"{f_name}\t{msg_id}\t{en_text}\t{source}\t{ref_file}\t{ref_id}\t{ref_en}\t{matched_cz}\t{match_tier}\t{r['status']}\t{','.join(issues)}\n"
                )

                by_source[source] = by_source.get(source, 0) + 1
                if match_tier == 1:
                    t1_count += 1
                elif match_tier == 2:
                    t2_count += 1
                else:
                    t3_count += 1
            else:
                unmatched += 1

    print("\nZarovnávání dokončeno!")
    print("--------------------------------------------------")
    print(f"Celkem zpracovaných 'game/' řádků:    {total_game_rows}")
    print(f"Preskočeno manuálních překladů:        {skipped_manually_translated}")
    print(f"Odmítnuto pravidly (byl kandidát):     {rejected_rules}")
    print(f"Úspěšně spárováno:                     {t1_count + t2_count + t3_count}")
    print(f"  * Tier 1 (Strict ID & Text):         {t1_count}")
    print(f"  * Tier 2 (Same File, Mismatch ID):   {t2_count}")
    print(f"  * Tier 3 (Global Exact Match):       {t3_count}")
    for src, cnt in sorted(by_source.items()):
        print(f"  * Zdroj {src}:                       {cnt}")
    print(f"Nebylo možné spárovat (ponecháno):     {unmatched}")
    print("--------------------------------------------------")

    if t1_count + t2_count + t3_count > 0:
        backup_path = db_path.with_suffix(".jsonl.bak")
        print(f"Vytvářím zálohu databáze: {backup_path.name}")
        shutil.copy2(db_path, backup_path)

        print("Ukládám aktualizovanou databázi...")
        temp_file = db_path.with_suffix(".jsonl.tmp")
        with temp_file.open("w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        if temp_file.exists():
            if db_path.exists():
                db_path.unlink()
            temp_file.rename(db_path)
        print("Uloženo úspěšně!")
    else:
        print("Nebyly nalezeny žádné změny k uložení.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Párování Sonory s F1/F2/Nevada")
    parser.add_argument(
        "--reapply-fixes",
        action="store_true",
        help="Jen aplikuje auto-opravy na existující aligned řádky (bez nového párování)",
    )
    args = parser.parse_args()

    if args.reapply_fixes:
        config = load_config()
        db_path = ROOT / config.get("translated_file", "02_work/translated/sonora_translated.jsonl")
        if not db_path.exists():
            print(f"ERROR: {db_path} neexistuje.")
            sys.exit(1)
        reapply_alignment_fixes(db_path)
    else:
        main()
