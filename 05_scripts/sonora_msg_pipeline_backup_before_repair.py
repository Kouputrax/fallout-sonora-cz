#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sonora_msg_pipeline.py

Bezpecny minimalni pipeline pro Fallout/Sonora .msg soubory:
- export:    .msg -> JSONL
- translate: JSONL -> JSONL pres Ollama nebo OpenRouter
- validate:  kontrola prelozenych zaznamu
- import:    JSONL -> .msg strom

Format Fallout .msg radku bereme prakticky:
{ID}{SOUND}{TEXT}

Skript meni pouze treti pole TEXT. ID a SOUND zachovava.
Radky, ktere parser nepozna, ponechava pri importu beze zmeny.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import requests


MSG_LINE_START_RE = re.compile(r"^\s*\{")


def read_text_guess(path: Path) -> str:
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
    if not MSG_LINE_START_RE.match(line):
        return None

    line_no_newline = line.rstrip("\r\n")
    newline = line[len(line_no_newline):]

    idx = 0
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

    tail = line_no_newline[pos:]
    if tail.strip():
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
    return "\n".join(lines[:300])


def get_translation_schema() -> Dict[str, Any]:
    return {
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


def build_messages(batch: List[Dict[str, Any]], glossary: str, schema: Dict[str, Any]) -> List[Dict[str, str]]:
    system = (
        "You are a professional Czech localization translator for Fallout: Sonora. "
        "Translate game dialogue into Czech. Use English as the current working text and Russian as meaning/gender reference. "
        "Return ONLY valid JSON matching the provided schema. "

        "ABSOLUTE FIELD RULES: "
        "The field 'cs' must contain ONLY the final Czech in-game text. "
        "Never put metadata into 'cs'. "
        "Never put these strings into 'cs': gender_warning, meaning_warning, glossary_warning, true, false, notes, JSON, id, line_no. "
        "Warnings belong only in boolean fields. Notes belong only in 'notes'. "

        "STYLE RULES: "
        "Use natural Czech suitable for classic Fallout 1/2: concise, dry, rough, post-apocalyptic. "
        "Do not use modern internet slang. "
        "Use informal second person singular when the player is addressed: Vidíš, Mluvil jsi, Mluvila jsi, not Vidíte. "
        "Avoid stiff literal translation. "
        "Never use combined gender forms like mluvil/a, udělal/a, šel/šla. "

        "GENDER RULES: "
        "Use Russian to detect gender. "
        "If RU contains 'говорил', use masculine Czech: Mluvil jsi. "
        "If RU contains 'говорила', use feminine Czech: Mluvila jsi. "
        "If RU clearly indicates gender, do not set gender_warning. "
        "Set gender_warning=true only if gender is genuinely unclear and cannot be solved naturally. "
        "Do not set gender_warning just because English 'I' has no gender. "
        "Set gender_warning only when Czech translation must choose player gender, e.g. 'Mluvil jsi/Mluvila jsi', 'Udelal jsi/Udelala jsi'. "
        "If the sentence can be translated naturally without gender, do so and set gender_warning=false. "
        "Do not write long explanations into notes. Notes must be short. "

        "SPANISH RULES: "
        "Do not translate Spanish flavor text. "
        "No hablo ingles / No hablo inglés must stay as No hablo inglés. "
        "amigo, señor, gracias and similar Spanish flavor words should usually stay Spanish. "
        "If source text contains mojibake such as inglйs or inglђs, silently fix it to inglés. "
        "Never output Cyrillic mojibake characters such as Ў in Czech text. "
        "If Spanish inverted punctuation is corrupted, use normal punctuation instead. "
        "Example: ЎBuen trabajo! -> Buen trabajo! or ¡Buen trabajo! "

        "NAMES AND TERMS: "
        "Do not translate character names. "
        "Cesareo stays Cesareo; in Czech cases use natural form, e.g. s Cesareem. "
        "Do not translate Cesareo as Caesar, Císař, Cesář, or anything similar. "
        "Hector may become Hektor only if it sounds natural in Czech Fallout style. "

        "MEANING RULES: "
        "Never change the language being discussed. Spanish means španělsky, never česky. "
        "home port = domovský přístav. Never translate it as zbrojna. "
        "settle this bay = usadit se v této/téhle zátoce. "
        "lousy idea = pitomý nápad, blbý nápad, pitomá záležitost, or hrozná kravina depending on tone. "
        "rough canvas shirt = hrubá plátěná košile. "
        "red bandana = červený šátek or červená bandana. "

        "OUTPUT RULES: "
        "Keep file, line_no and id unchanged. "
        "Preserve quotation marks style if possible. "
        "Do not add commentary outside JSON. "
        "Do not add explanations into translated text."
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
        "Translate the following Fallout: Sonora localization rows into Czech.\n"
        "Return JSON only.\n"
        "Do not change file, line_no, or id.\n"
        "The 'cs' field must contain only the final Czech in-game text, nothing else.\n"
        "Do not put warning labels or boolean values into 'cs'.\n\n"
        "Important examples:\n"
        "- EN: You see Hector. -> CS: Vidíš Hektora.\n"
        "- EN: No hablo inglйs. -> CS: No hablo inglés.\n"
        "- EN: You speak Spanish? -> CS: Mluvíš španělsky?\n"
        "- RU masculine 'говорил' -> CS: Mluvil jsi.\n"
        "- RU feminine 'говорила' -> CS: Mluvila jsi.\n"
        "- EN: Have you talked to Cesareo yet? -> CS: Mluvil jsi už s Cesareem? / Mluvila jsi už s Cesareem?\n\n"
        "JSON schema:\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n\nDATA:\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt}
    ]


def parse_json_response_text(content: str) -> Dict[str, Any]:
    text = content.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def ollama_translate_batch(batch: List[Dict[str, Any]], model: str, glossary: str, host: str) -> Dict[str, Any]:
    schema = get_translation_schema()
    messages = build_messages(batch, glossary, schema)

    url = host.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": schema,
        "options": {
            "temperature": 0,
            "top_p": 0.9,
            "repeat_penalty": 1.1
        },
        "think": False
    }

    resp = requests.post(url, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    content = data.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"Ollama vratila prazdnou odpoved: {data}")

    return parse_json_response_text(content)


def openrouter_translate_batch(
    batch: List[Dict[str, Any]],
    model: str,
    glossary: str,
    api_key: str,
    timeout: int,
    site_url: Optional[str] = None,
    app_name: Optional[str] = None,
) -> Dict[str, Any]:
    schema = get_translation_schema()
    messages = build_messages(batch, glossary, schema)

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_name:
        headers["X-Title"] = app_name

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "top_p": 0.9,
        "response_format": {"type": "json_object"},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

    if resp.status_code >= 400:
        raise RuntimeError(f"OpenRouter chyba {resp.status_code}: {resp.text[:1000]}")

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenRouter nevratil choices: {data}")

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"OpenRouter vratil prazdnou odpoved: {data}")

    result = parse_json_response_text(content)
    usage = data.get("usage") or {}
    if usage:
        result["_usage"] = usage
    return result

    
def postprocess_cs(text: str) -> str:
    if not text:
        return text

    replacements = {
        "zemřeš sám za sebe": "chcípneš",
        "Popутnýho větru. Sbohem.": "Vítr do plachet. Sbohem.",
        "Popутnýho větru": "Vítr do plachet",
        "крышками": "zátkami",
        "compaсeras": "compañeras",
        "compaсero": "compañero",
        "compaсera": "compañera",
        "Ў": "¡",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text

def translate_cmd(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    out_path = Path(args.out)
    rows = load_jsonl(input_path)
    glossary = load_glossary(args.glossary)

    candidates = [r for r in rows if not r.get("cs") and r.get("en", "").strip()]
    if args.limit:
        candidates = candidates[:args.limit]

    print(f"Provider: {args.provider}")
    print(f"Model: {args.model}")
    print(f"Zaznamu k prekladu v teto davce: {len(candidates)}")

    key_to_row = {(r["file"], r["line_no"], r["id"]): r for r in rows}

    batch_size = args.batch_size
    done = 0
    prompt_tokens_total = 0
    completion_tokens_total = 0
    total_tokens_total = 0

    api_key = None
    if args.provider == "openrouter":
        api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit(
                "Chybi OpenRouter API key. Nastav ho napr.:\n"
                '$env:OPENROUTER_API_KEY="sk-or-v1-..."\n'
                "nebo pouzij --api-key."
            )

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        print(f"Preklad batch {i // batch_size + 1}: {len(batch)} zaznamu")
        try:
            if args.provider == "ollama":
                result = ollama_translate_batch(batch, args.model, glossary, args.host)
            elif args.provider == "openrouter":
                result = openrouter_translate_batch(
                    batch=batch,
                    model=args.model,
                    glossary=glossary,
                    api_key=api_key or "",
                    timeout=args.timeout,
                    site_url=args.site_url,
                    app_name=args.app_name,
                )
            else:
                raise RuntimeError(f"Neznamy provider: {args.provider}")
        except Exception as e:
            print(f"CHYBA v batchi: {e}", file=sys.stderr)
            if args.stop_on_error:
                raise
            continue

        usage = result.get("_usage") or {}
        if usage:
            prompt_tokens_total += int(usage.get("prompt_tokens") or 0)
            completion_tokens_total += int(usage.get("completion_tokens") or 0)
            total_tokens_total += int(usage.get("total_tokens") or 0)

        for item in result.get("items", []):
            key = (item.get("file"), item.get("line_no"), item.get("id"))
            row = key_to_row.get(key)
            if not row:
                continue

            row["cs"] = postprocess_cs(item.get("cs", ""))
            row["status"] = "translated"

            # Model warnings are too noisy.
            # We keep translation only; local validate_cmd decides what needs review.
            row["warnings"] = []
            row["notes"] = ""

            done += 1

        save_jsonl(out_path, rows)
        time.sleep(args.sleep)

    print(f"Prelozeno/aktualizovano: {done}")
    print(f"Vystup: {out_path}")

    if prompt_tokens_total or completion_tokens_total or total_tokens_total:
        print("Token usage podle API:")
        print(f"  prompt_tokens:     {prompt_tokens_total}")
        print(f"  completion_tokens: {completion_tokens_total}")
        print(f"  total_tokens:      {total_tokens_total}")

        if args.input_price_per_m or args.output_price_per_m:
            estimated_usd = (
                prompt_tokens_total / 1_000_000 * args.input_price_per_m
                + completion_tokens_total / 1_000_000 * args.output_price_per_m
            )
            print(f"Odhad ceny pro tento beh: ${estimated_usd:.6f}")


def validate_cmd(args: argparse.Namespace) -> None:
    rows = load_jsonl(Path(args.input))
    errors = 0
    warnings = 0

    forbidden_patterns = [
        re.compile(r"\{[0-9]+\}\{"),
        re.compile(r"gender_warning", re.IGNORECASE),
        re.compile(r"meaning_warning", re.IGNORECASE),
        re.compile(r"glossary_warning", re.IGNORECASE),
        re.compile(r"\btrue\b", re.IGNORECASE),
        re.compile(r"\bfalse\b", re.IGNORECASE),
        re.compile(r"\bline_no\b", re.IGNORECASE),
        re.compile(r"\bnotes\b", re.IGNORECASE),
    ]

    qa_warning_patterns = [
        ("combined_gender_form", re.compile(r"\b\w+/\w+\b", re.IGNORECASE)),
        ("formal_you_vidite", re.compile(r"\bVidíte\b")),
        ("bad_home_port_zbrojna", re.compile(r"\bzbrojna\b|\bzbrojnu\b|\bzbrojny\b", re.IGNORECASE)),
        ("bad_cesareo_translation", re.compile(r"\b(Caesar|Císař|Cesář|Cisar)\b", re.IGNORECASE)),
        ("trailing_comma_after_quote", re.compile(r"[»“\"]\s*,\s*$")),
        ("cyrillic_in_cs", re.compile(r"[\u0400-\u04FF]")),
        ("bad_survive_phrase", re.compile(r"\bpřežiješ, nebo zemřeš sám\b", re.IGNORECASE)),
        ("bad_tesno_testo", re.compile(r"\btěsto\b", re.IGNORECASE)),
        ("bad_wind_phrase", re.compile(r"větrný vítr", re.IGNORECASE)),
    ]

    for r in rows:
        cs = r.get("cs", "")
        en = r.get("en", "")
        if r.get("status") != "translated":
            continue

        if any(p.search(cs) for p in forbidden_patterns):
            print(f"ERROR: {r['file']}:{r['line_no']} id={r['id']} podezrely obsah v cs poli: {cs}")
            errors += 1

        if "{" in cs or "}" in cs:
            print(f"WARN: {r['file']}:{r['line_no']} id={r['id']} obsahuje zavorky v prekladu: {cs}")
            warnings += 1

        for label, pattern in qa_warning_patterns:
            if pattern.search(cs):
                print(f"WARN: {r['file']}:{r['line_no']} id={r['id']} qa={label}: {cs}")
                warnings += 1

        if "Spanish" in en and re.search(r"\bčesky\b|\bcesky\b", cs, re.IGNORECASE):
            print(f"ERROR: {r['file']}:{r['line_no']} id={r['id']} Spanish bylo prelozeno jako cesky: {cs}")
            errors += 1

        if "No hablo" in en and "Nemluv" in cs:
            print(f"WARN: {r['file']}:{r['line_no']} id={r['id']} spanelska veta byla prelozena misto ponechani: {cs}")
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

    p = sub.add_parser("translate", help="Translate JSONL with Ollama or OpenRouter")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--glossary", required=False)

    p.add_argument("--provider", choices=["ollama", "openrouter"], default="ollama")
    p.add_argument("--model", default="deepseek-r1:8b")

    p.add_argument("--host", default="http://localhost:11434")

    p.add_argument("--api-key", default=None)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--site-url", default=None)
    p.add_argument("--app-name", default="Fallout Sonora CZ Translator")

    p.add_argument("--input-price-per-m", type=float, default=0.0)
    p.add_argument("--output-price-per-m", type=float, default=0.0)

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
