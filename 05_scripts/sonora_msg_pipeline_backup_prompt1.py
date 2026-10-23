#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sonora_msg_pipeline.py

Bezpecny minimalni pipeline pro Fallout/Sonora .msg soubory:
- export:   .msg -> JSONL
- translate: JSONL -> JSONL pres Ollama
- validate: kontrola prelozenych zaznamu
- import:   JSONL -> .msg strom

Format Fallout .msg radku bereme prakticky:
{ID}{SOUND}{TEXT}

Skript meni pouze treti pole TEXT. ID a SOUND zachovava.
Radky, ktere parser nepozna, ponechava pri importu beze zmeny.

Autor: startovni sablona pro lokalizacni workflow.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import requests


MSG_LINE_START_RE = re.compile(r"^\s*\{")


def read_text_guess(path: Path) -> str:
    """
    Zkusi nacist soubor bez toho, aby spadl na kodovani.

    Fallout mod soubory mohou byt ruzne kodovane. Pro prvni prototyp pouzivame:
    utf-8-sig -> utf-8 -> cp1251 -> cp1250 -> latin-1

    Poznamka:
    Pri finalnim vydani bude potreba kodovani sjednotit podle toho,
    co hra/fission/sfall skutecne pouziva pro dany language pack.
    """
    encodings = ["utf-8-sig", "utf-8", "cp1251", "cp1250", "latin-1"]
    data = path.read_bytes()
    for enc in encodings:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", errors="replace")


def write_text_utf8(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def parse_brace_group(line: str, start: int) -> Optional[Tuple[str, int]]:
    """
    Vrati obsah jedne skupiny { ... } a index za zaviraci zavorkou.
    Neumi vnorene zavorky. Pro Fallout .msg je to obvykle spravne.
    """
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


def parse_msg_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Pokusi se rozparsovat radek typu:
    {123}{}{Hello}

    Vraci:
    {
      "id": "123",
      "sound": "",
      "text": "Hello",
      "prefix": "",
      "suffix": "\n"
    }
    """
    if not MSG_LINE_START_RE.match(line):
        return None

    line_no_newline = line.rstrip("\r\n")
    newline = line[len(line_no_newline):]

    idx = 0
    # prefix pred prvni zavorkou, typicky mezery
    while idx < len(line_no_newline) and line_no_newline[idx].isspace():
        idx += 1
    prefix = line_no_newline[:idx]

    g1 = parse_brace_group(line_no_newline, idx)
    if not g1:
        return None
    msg_id, pos = g1

    g2 = parse_brace_group(line_no_newline, pos)
    if not g2:
        return None
    sound, pos = g2

    g3 = parse_brace_group(line_no_newline, pos)
    if not g3:
        return None
    text, pos = g3

    # Po treti skupine tolerujeme jen mezery.
    tail = line_no_newline[pos:]
    if tail.strip():
        # Radek muze mit komentar nebo specialni bordel. Nechame ho jako neparsovany.
        return None

    return {
        "id": msg_id,
        "sound": sound,
        "text": text,
        "prefix": prefix,
        "suffix": newline,
    }


def build_msg_line(parsed: Dict[str, Any], new_text: str) -> str:
    prefix = parsed.get("prefix", "")
    suffix = parsed.get("suffix", "\n")
    return f"{prefix}{{{parsed['id']}}}{{{parsed['sound']}}}{{{new_text}}}{suffix}"


def iter_msg_files(root: Path) -> List[Path]:
    return sorted([p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".msg"])


def export_cmd(args: argparse.Namespace) -> None:
    en_root = Path(args.en_root)
    ru_root = Path(args.ru_root) if args.ru_root else None
    out = Path(args.out)

    if not en_root.exists():
        raise SystemExit(f"EN root neexistuje: {en_root}")

    rows = []
    total_lines = 0
    parsed_lines = 0

    for en_file in iter_msg_files(en_root):
        rel = en_file.relative_to(en_root).as_posix()
        en_lines = read_text_guess(en_file).splitlines(keepends=True)

        ru_lines = []
        if ru_root:
            ru_file = ru_root / rel
            if ru_file.exists():
                ru_lines = read_text_guess(ru_file).splitlines(keepends=True)

        for line_no, en_line in enumerate(en_lines, start=1):
            total_lines += 1
            p_en = parse_msg_line(en_line)
            if not p_en:
                continue
            parsed_lines += 1

            ru_text = ""
            if ru_lines and line_no <= len(ru_lines):
                p_ru = parse_msg_line(ru_lines[line_no - 1])
                if p_ru and p_ru.get("id") == p_en.get("id"):
                    ru_text = p_ru.get("text", "")

            rows.append({
                "file": rel,
                "line_no": line_no,
                "id": p_en["id"],
                "sound": p_en["sound"],
                "en": p_en["text"],
                "ru": ru_text,
                "cs": "",
                "status": "new",
                "warnings": [],
                "notes": ""
            })

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Export hotov: {out}")
    print(f"MSG souboru: {len(iter_msg_files(en_root))}")
    print(f"Radku celkem: {total_lines}")
    print(f"Parsovanych MSG radku: {parsed_lines}")
    print(f"Exportovanych zaznamu: {len(rows)}")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def save_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_glossary(path: Optional[str]) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    lines = []
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        lines.append(raw)
    return "\n".join(lines[:300])  # prvni prototyp: nechceme obri prompt


def ollama_translate_batch(batch: List[Dict[str, Any]], model: str, glossary: str, host: str) -> Dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "line_no": {"type": "integer"},
                        "id": {"type": "string"},
                        "cs": {"type": "string"},
                        "gender_warning": {"type": "boolean"},
                        "meaning_warning": {"type": "boolean"},
                        "glossary_warning": {"type": "boolean"},
                        "notes": {"type": "string"}
                    },
                    "required": ["file", "line_no", "id", "cs", "gender_warning", "meaning_warning", "glossary_warning", "notes"]
                }
            }
        },
        "required": ["items"]
    }

    system = (
        "Jsi lokalizacni asistent pro Fallout: Sonora. "
        "Vracej pouze JSON podle schematu. "
        "Prekladej do cestiny. Zachovej jmena, tagy, promenne a technicke znacky. "
        "Pouzij styl ceskeho Fallout 1/2 a Fallout Nevada: strucny, surovy, ne moderni internetovy slang. "
        "EN je aktualni pracovni text. RU je vyznamova kontrola, pokud existuje. "
        "Pokud si EN a RU odporuji, nastav meaning_warning=true. "
        "Pokud je problem s rodem hrace nebo NPC, nastav gender_warning=true."
    )

    user_payload = {
        "glossary_tsv": glossary,
        "rows": [
            {
                "file": r["file"],
                "line_no": r["line_no"],
                "id": r["id"],
                "en": r.get("en", ""),
                "ru": r.get("ru", ""),
            }
            for r in batch
        ]
    }

    prompt = (
        "Preloz nasledujici zaznamy do cestiny.\n"
        "Nemen file, line_no ani id.\n"
        "Vrat JSON podle tohoto schematu:\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n\nDATA:\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )

    url = host.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "format": schema,
        "options": {
            "temperature": 0
        },
        "think": False
    }

    resp = requests.post(url, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    content = data.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"Ollama vratila prazdnou odpoved: {data}")
    return json.loads(content)


def translate_cmd(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    out_path = Path(args.out)
    rows = load_jsonl(input_path)
    glossary = load_glossary(args.glossary)

    candidates = [r for r in rows if not r.get("cs") and r.get("en", "").strip()]
    if args.limit:
        candidates = candidates[:args.limit]

    print(f"Zaznamu k prekladu v teto davce: {len(candidates)}")

    # Mapa pro rychlou aktualizaci
    key_to_row = {(r["file"], r["line_no"], r["id"]): r for r in rows}

    batch_size = args.batch_size
    done = 0

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        print(f"Preklad batch {i // batch_size + 1}: {len(batch)} zaznamu")
        try:
            result = ollama_translate_batch(batch, args.model, glossary, args.host)
        except Exception as e:
            print(f"CHYBA v batchi: {e}", file=sys.stderr)
            if args.stop_on_error:
                raise
            continue

        for item in result.get("items", []):
            key = (item.get("file"), item.get("line_no"), item.get("id"))
            row = key_to_row.get(key)
            if not row:
                continue
            row["cs"] = item.get("cs", "")
            row["status"] = "translated"
            warnings = []
            if item.get("gender_warning"):
                warnings.append("gender")
            if item.get("meaning_warning"):
                warnings.append("meaning")
            if item.get("glossary_warning"):
                warnings.append("glossary")
            row["warnings"] = warnings
            row["notes"] = item.get("notes", "")
            done += 1

        save_jsonl(out_path, rows)
        time.sleep(args.sleep)

    print(f"Prelozeno/aktualizovano: {done}")
    print(f"Vystup: {out_path}")


def validate_cmd(args: argparse.Namespace) -> None:
    rows = load_jsonl(Path(args.input))
    errors = 0
    warnings = 0

    forbidden_patterns = [
        re.compile(r"\{[0-9]+\}\{"),  # model omylem vratil cely msg radek
    ]

    for r in rows:
        cs = r.get("cs", "")
        if r.get("status") == "translated":
            if any(p.search(cs) for p in forbidden_patterns):
                print(f"ERROR: {r['file']}:{r['line_no']} id={r['id']} vypada jako cely MSG radek v cs poli")
                errors += 1
            if "{" in cs or "}" in cs:
                # Neni vzdy chyba, ale pro prvni prototyp radeji zkontrolovat.
                print(f"WARN: {r['file']}:{r['line_no']} id={r['id']} obsahuje zavorky v prekladu: {cs}")
                warnings += 1
            if r.get("warnings"):
                print(f"REVIEW: {r['file']}:{r['line_no']} id={r['id']} warnings={r.get('warnings')} notes={r.get('notes')}")
                warnings += 1

    print(f"Validace hotova. Errors={errors}, warnings/review={warnings}")
    if errors:
        sys.exit(1)


def import_cmd(args: argparse.Namespace) -> None:
    source_root = Path(args.source_root)
    translated_path = Path(args.translated)
    out_root = Path(args.out_root)

    rows = load_jsonl(translated_path)
    # Pouzijeme jen radky, ktere maji preklad.
    trans_by_file_line = {}
    for r in rows:
        if r.get("cs"):
            trans_by_file_line[(r["file"], r["line_no"], r["id"])] = r["cs"]

    changed_files = 0
    changed_lines = 0

    for src_file in iter_msg_files(source_root):
        rel = src_file.relative_to(source_root).as_posix()
        lines = read_text_guess(src_file).splitlines(keepends=True)
        new_lines = []
        file_changed = False

        for line_no, line in enumerate(lines, start=1):
            parsed = parse_msg_line(line)
            if not parsed:
                new_lines.append(line)
                continue

            key = (rel, line_no, parsed["id"])
            if key in trans_by_file_line:
                new_lines.append(build_msg_line(parsed, trans_by_file_line[key]))
                file_changed = True
                changed_lines += 1
            else:
                new_lines.append(line)

        out_file = out_root / rel
        write_text_utf8(out_file, "".join(new_lines))
        if file_changed:
            changed_files += 1

    print(f"Import hotov: {out_root}")
    print(f"Zmenenych souboru: {changed_files}")
    print(f"Zmenenych radku: {changed_lines}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fallout Sonora .msg AI localization helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("export", help=".msg -> JSONL")
    p.add_argument("--en-root", required=True)
    p.add_argument("--ru-root", required=False)
    p.add_argument("--out", required=True)
    p.set_defaults(func=export_cmd)

    p = sub.add_parser("translate", help="Translate JSONL with Ollama")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--glossary", required=False)
    p.add_argument("--model", default="deepseek-r1:8b")
    p.add_argument("--host", default="http://localhost:11434")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--sleep", type=float, default=0.5)
    p.add_argument("--stop-on-error", action="store_true")
    p.set_defaults(func=translate_cmd)

    p = sub.add_parser("validate", help="Validate translated JSONL")
    p.add_argument("--input", required=True)
    p.set_defaults(func=validate_cmd)

    p = sub.add_parser("import", help="JSONL -> .msg tree")
    p.add_argument("--source-root", required=True)
    p.add_argument("--translated", required=True)
    p.add_argument("--out-root", required=True)
    p.set_defaults(func=import_cmd)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
