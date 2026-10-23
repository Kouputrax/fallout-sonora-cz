#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_director.py — jednoduchý řídicí skript pro správné pořadí kroků překladu.

Doporučená posloupnost:
  1. export   — vytáhnout texty z .msg do export JSONL
  2. sync     — sloučit export do pracovní databáze (zachovat cs, status, poznámky)
  3. align    — převzít shody z Fallout 2 CZ (herní řádky)
  4. enrich   — doplnit context_tags / hint_cs
  5. translate — AI překlad jen prázdných řádků (čte pracovní DB!)
  6. validate — QA kontrola (stejná pravidla jako repair detektor)
  7. fix      — enrich + validate + repair + validate (kompletní QA oprava)
  8. import   — zpět do .msg
  reset       — záloha + vynulovat celou pracovní DB (čistý start)

Příklady:
  python pipeline_director.py --list
  python pipeline_director.py --reset
  python pipeline_director.py --prepare
  python pipeline_director.py --fix --limit 50
  python pipeline_director.py --steps export,sync
  python pipeline_director.py --steps translate --limit 50
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "05_scripts"

DEFAULT_CONFIG = {
    "provider": "ollama",
    "ollama_host": "http://localhost:11434",
    "ollama_model": "qwen2.5:7b",
    "openrouter_model": "anthropic/claude-3-haiku",
    "openrouter_repair_model": "qwen/qwen3-235b-a22b-2507",
    "en_root": "01_sources/sonora_en",
    "ru_root": "01_sources/sonora_ru",
    "export_file": "02_work/export/sonora_export.jsonl",
    "translated_file": "02_work/translated/sonora_translated.jsonl",
    "glossary_dir": "03_glossary",
    "output_root": "06_output/czech_text",
}

STEPS = [
    ("export", "Export .msg -> JSONL (export soubor)"),
    ("sync", "Sloucit export do pracovni databaze (zachovat preklady)"),
    ("align", "Parovani s F1/F2/Nevada CZ (herni radky + pravidla)"),
    ("enrich", "Doplnit kontextove znacky a napovedy"),
    ("translate", "AI preklad neprelozenych radku"),
    ("validate", "Kontrola QA (stejna pravidla jako repair)"),
    ("fix", "QA oprava: tagy -> validace -> repair -> re-validace"),
    ("import", "Sestavit finalni .msg soubory"),
    ("reset", "Zaloha + vynulovat celou pracovni DB (cisty start)"),
]

PREPARE_STEPS = ["sync", "align", "enrich"]
FIX_STEPS = ["enrich", "validate", "repair", "validate"]
DEFAULT_AFTER_EXPORT = ["export", "sync"]


def load_config() -> dict[str, Any]:
    cfg_path = SCRIPTS / "pipeline_config.json"
    cfg = DEFAULT_CONFIG.copy()
    if cfg_path.exists():
        try:
            with cfg_path.open("r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def save_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def row_key(r: dict) -> tuple:
    return (r.get("file"), r.get("line_no"), str(r.get("id")))


def step_sync(cfg: dict) -> dict:
    """Slouci cerstvy export do pracovni DB — cs/status/notes zustanou."""
    export_path = ROOT / cfg["export_file"]
    work_path = ROOT / cfg["translated_file"]

    if not export_path.exists():
        raise SystemExit(f"Chybi export: {export_path} (nejdriv spust krok export)")

    export_rows = load_jsonl(export_path)
    work_rows = load_jsonl(work_path)
    index = {row_key(r): r for r in work_rows}

    added = 0
    updated_en = 0
    for r in export_rows:
        k = row_key(r)
        if k not in index:
            index[k] = r
            added += 1
        else:
            ex = index[k]
            if ex.get("en") != r.get("en"):
                ex["en"] = r.get("en")
                updated_en += 1
            if r.get("ru"):
                ex["ru"] = r.get("ru")
            if r.get("sound") is not None:
                ex["sound"] = r.get("sound", "")

    merged = list(index.values())
    save_jsonl(work_path, merged)
    stats = {"added": added, "updated_en": updated_en, "total": len(merged), "path": str(work_path)}
    print(f"SYNC: +{added} novych, {updated_en} zmen EN, celkem {len(merged)} radku -> {work_path.name}")
    return stats


def run_py(script: Path, args: list[str]) -> int:
    cmd = [sys.executable, str(script)] + args
    print(f"\n>>> {' '.join(cmd)}")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(cmd, cwd=str(ROOT), env=env).returncode


def run_pipeline(args: list[str]) -> int:
    return run_py(SCRIPTS / "sonora_msg_pipeline.py", args)


def step_export(cfg: dict) -> int:
    return run_pipeline([
        "export",
        "--en-root", str(ROOT / cfg["en_root"]),
        "--ru-root", str(ROOT / cfg["ru_root"]),
        "--out", str(ROOT / cfg["export_file"]),
    ])


def step_align(_cfg: dict) -> int:
    return run_py(SCRIPTS / "align_classic_translations.py", [])


def step_enrich(cfg: dict) -> int:
    work = ROOT / cfg["translated_file"]
    if not work.exists():
        print("ENRICH: pracovni DB neexistuje, preskoceno.")
        return 0
    return run_py(SCRIPTS / "enrich_context_tags.py", ["--input", str(work), "--no-backup"])


def step_translate(cfg: dict, limit: int, batch_size: int) -> int:
    work = ROOT / cfg["translated_file"]
    if not work.exists():
        raise SystemExit(f"Chybi pracovni DB: {work} (nejdriv export + sync)")

    provider = cfg.get("provider", "ollama")
    args = [
        "translate",
        "--input", str(work),
        "--out", str(work),
        "--glossary", str(ROOT / cfg["glossary_dir"]),
        "--provider", provider,
        "--limit", str(limit),
        "--batch-size", str(batch_size),
    ]
    if provider == "ollama":
        args += ["--model", cfg.get("ollama_model", "qwen2.5:7b"), "--host", cfg.get("ollama_host", "http://localhost:11434")]
    else:
        args += ["--model", cfg.get("openrouter_model", "anthropic/claude-3-haiku")]
    return run_pipeline(args)


def step_validate(cfg: dict, *, warn_only: bool = False) -> int:
    args = ["validate", "--input", str(ROOT / cfg["translated_file"])]
    if warn_only:
        args.append("--warn-only")
    return run_pipeline(args)


def step_repair(cfg: dict, limit: int, batch_size: int) -> int:
    import os
    key = os.environ.get("OPENROUTER_API_KEY", "")
    args = [
        "repair",
        "--input", str(ROOT / cfg["translated_file"]),
        "--out", str(ROOT / cfg["translated_file"]),
        "--glossary", str(ROOT / cfg["glossary_dir"]),
        "--model", cfg.get("openrouter_repair_model", "qwen/qwen3-235b-a22b-2507"),
        "--limit", str(limit),
        "--batch-size", str(batch_size),
    ]
    if key:
        args += ["--api-key", key]
    return run_pipeline(args)


def step_fix(cfg: dict, limit: int, batch_size: int) -> int:
    """Kompletni QA oprava: tagy, scan, repair, re-scan."""
    print("FIX: enrich -> validate (scan) -> repair -> validate (kontrola)")
    chain: list[tuple[str, Callable[[], int]]] = [
        ("enrich", lambda: step_enrich(cfg)),
        ("validate", lambda: step_validate(cfg, warn_only=True)),
        ("repair", lambda: step_repair(cfg, limit, batch_size)),
        ("validate", lambda: step_validate(cfg, warn_only=False)),
    ]
    last_code = 0
    for name, fn in chain:
        print(f"\n--- FIX / {name.upper()} ---")
        code = int(fn() or 0)
        last_code = code
        if name == "repair" and code != 0:
            print(f"FIX: repair skoncil chybou (kod {code}).")
            return code
    return last_code


def clean_work_row(r: dict) -> dict:
    row = dict(r)
    row["cs"] = ""
    row["status"] = "new"
    for key in ("notes", "context_tags", "hint_cs", "repaired", "warnings", "file_category"):
        row.pop(key, None)
    return row


def step_reset(cfg: dict) -> dict:
    """Záloha pracovní DB a vynulování všech překladů včetně F2."""
    work_path = ROOT / cfg["translated_file"]
    export_path = ROOT / cfg["export_file"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if work_path.exists():
        backup = work_path.with_name(f"{work_path.stem}_backup_{ts}{work_path.suffix}")
        shutil.copy2(work_path, backup)
        print(f"RESET: zaloha -> {backup.name}")

    if export_path.exists():
        rows = [clean_work_row(r) for r in load_jsonl(export_path)]
        source = "export"
    elif work_path.exists():
        rows = [clean_work_row(r) for r in load_jsonl(work_path)]
        source = "work"
    else:
        raise SystemExit("RESET: chybi export i pracovni DB — nejdriv spust export")

    save_jsonl(work_path, rows)
    stats = {"total": len(rows), "source": source, "path": str(work_path)}
    print(f"RESET: vynulovano {len(rows)} radku (zdroj: {source}) -> {work_path.name}")
    return stats


def step_import(cfg: dict) -> int:
    return run_pipeline([
        "import",
        "--source-root", str(ROOT / cfg["en_root"]),
        "--translated", str(ROOT / cfg["translated_file"]),
        "--out-root", str(ROOT / cfg["output_root"]),
    ])


def expand_steps(steps: list[str]) -> list[str]:
    """repair samostatne = alias pro fix (plny QA retezec)."""
    out: list[str] = []
    for s in steps:
        s = s.strip().lower()
        if s == "repair":
            out.extend(["fix"])
        else:
            out.append(s)
    return out


def run_steps(
    steps: list[str],
    cfg: dict,
    *,
    limit: int = 50,
    batch_size: int = 10,
) -> int:
    def do_sync():
        step_sync(cfg)
        return 0

    def do_reset():
        step_reset(cfg)
        return 0

    handlers: dict[str, Callable[[], int]] = {
        "export": lambda: step_export(cfg),
        "sync": do_sync,
        "align": lambda: step_align(cfg),
        "enrich": lambda: step_enrich(cfg),
        "translate": lambda: step_translate(cfg, limit, batch_size),
        "validate": lambda: step_validate(cfg, warn_only=False),
        "fix": lambda: step_fix(cfg, limit, batch_size),
        "import": lambda: step_import(cfg),
        "reset": do_reset,
    }

    steps = expand_steps(steps)

    print("=" * 60)
    print(" PIPELINE DIRECTOR — plan kroku:")
    for i, s in enumerate(steps, 1):
        desc = next((d for k, d in STEPS if k == s), s)
        print(f"  {i}. {s} — {desc}")
    print("=" * 60)

    last_code = 0
    for s in steps:
        s = s.strip().lower()
        if s not in handlers:
            print(f"Neznamy krok: {s}")
            return 1
        print(f"\n--- KROK: {s.upper()} ---")
        result = handlers[s]()
        if isinstance(result, dict):
            continue
        last_code = int(result or 0)
        if last_code != 0 and s not in ("validate",):
            print(f"Krok {s} skoncil chybou (kod {last_code}).")
            return last_code
    print("\nDirector: vsechny kroky dokonceny.")
    return last_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Rizeni poradi kroku prekladove pipeline.")
    parser.add_argument("--list", action="store_true", help="Vypsat doporucene kroky")
    parser.add_argument("--prepare", action="store_true", help="sync + align + enrich")
    parser.add_argument("--fix", action="store_true", help="enrich + validate + repair + validate")
    parser.add_argument("--reset", action="store_true", help="zaloha + vynulovat celou pracovni DB")
    parser.add_argument("--steps", type=str, default="", help="Kroky oddelene carkou, napr. export,sync,translate")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()

    if args.list:
        print("Doporucene poradi kroku:\n")
        for i, (key, desc) in enumerate(STEPS, 1):
            print(f"  {i}. {key:10} — {desc}")
        print("\nTypicky beh: export -> sync -> align -> enrich -> translate -> validate -> fix -> import")
        print("Priprava pred prekladem: --prepare  (= sync, align, enrich)")
        print("QA oprava: --fix  (= enrich, validate, repair, validate)")
        print("Cisty start: --reset  (= zaloha + vynulovat preklady vcetne F2)")
        return

    cfg = load_config()

    if args.reset:
        steps = ["reset"]
    elif args.prepare:
        steps = PREPARE_STEPS.copy()
    elif args.fix:
        steps = ["fix"]
    elif args.steps:
        steps = [x.strip() for x in args.steps.split(",") if x.strip()]
    else:
        parser.print_help()
        return

    code = run_steps(steps, cfg, limit=args.limit, batch_size=args.batch_size)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
