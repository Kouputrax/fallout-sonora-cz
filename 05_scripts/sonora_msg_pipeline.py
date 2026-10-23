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
import csv
import time
from datetime import datetime
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








def load_glossary_tsv_file(p: Path) -> List[Tuple[str, str]]:
    terms = []
    if not p.exists():
        return terms
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        reader = csv.DictReader(content.splitlines(), delimiter="\t")
        for row in reader:
            if not row:
                continue
            en = (row.get("source_en") or row.get("english_cue") or row.get("source") or "").strip()
            cz = (row.get("target_cs") or row.get("neutral_cz") or row.get("target") or "").strip()
            if en and cz:
                terms.append((en, cz))
    except Exception:
        try:
            for line in content.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    en = parts[0].strip()
                    cz = parts[1].strip()
                    # Skip header line
                    if en.lower() in ("source_en", "english_cue", "source") and cz.lower() in ("target_cs", "neutral_cz", "target"):
                        continue
                    terms.append((en, cz))
        except Exception:
            pass
    return terms


def load_all_glossaries(glossary_path: Optional[str]) -> List[Tuple[str, str, str]]:
    terms = []
    seen = set()
    
    g_dir = Path("03_glossary")
    if glossary_path:
        p = Path(glossary_path)
        if p.is_dir():
            g_dir = p
        elif p.is_file():
            g_dir = p.parent
            
    # 1. Načtení base  protected terms (core)
    core_files = ["protected_terms.tsv", "base_terms.tsv"]
    for f_name in core_files:
        p = g_dir / f_name
        for en, cz in load_glossary_tsv_file(p):
            if en.lower() not in seen:
                seen.add(en.lower())
                terms.append((en, cz, "core"))
                
    # 2. Načtení referenčních a doplňkových glosářů (lazy matched)
    ref_files = [
        "fallout_ref_perks_skills.tsv",
        "fallout_ref_items.tsv",
        "fallout_ref_locations_quests.tsv",
        "style_slang.tsv"
    ]
    for f_name in ref_files:
        p = g_dir / f_name
        for en, cz in load_glossary_tsv_file(p):
            if en.lower() not in seen:
                seen.add(en.lower())
                terms.append((en, cz, p.stem))
                
    return terms



def load_glossary_tsv_file_extended(p: Path) -> List[Dict[str, Any]]:
    terms = []
    if not p.exists():
        return terms
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        reader = csv.DictReader(content.splitlines(), delimiter="\t")
        for row in reader:
            if not row:
                continue
            en = (row.get("source_en") or row.get("english_cue") or row.get("source") or "").strip()
            cz = (row.get("target_cs") or row.get("neutral_cz") or row.get("target") or "").strip()
            if en and cz:
                origin = row.get("origin", "").strip()
                category = row.get("category", "").strip()
                
                # Fallback pro origin
                if not origin:
                    if p.stem in ["protected_terms", "base_terms"]:
                        origin = "core"
                    elif "nevada" in p.stem:
                        origin = "nevada_cz"
                    elif "fallout2" in p.stem:
                        origin = "fallout2_cz"
                    elif "fallout1" in p.stem:
                        origin = "fallout1_cz"
                    else:
                        origin = p.stem
                
                # Fallback pro category
                if not category:
                    if "item" in p.stem:
                        category = "item"
                    elif "location" in p.stem or "quest" in p.stem:
                        category = "location_quest"
                    elif "perk" in p.stem or "skill" in p.stem:
                        category = "perk_skill"
                    else:
                        category = "general"
                        
                terms.append({
                    "en": en,
                    "cs": cz,
                    "origin": origin,
                    "category": category
                })
    except Exception:
        try:
            for line in content.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    en = parts[0].strip()
                    cz = parts[1].strip()
                    origin = parts[2].strip() if len(parts) > 2 else ""
                    category = parts[3].strip() if len(parts) > 3 else ""
                    
                    if not origin:
                        if p.stem in ["protected_terms", "base_terms"]:
                            origin = "core"
                        else:
                            origin = p.stem
                    if not category:
                        category = "general"
                        
                    terms.append({
                        "en": en,
                        "cs": cz,
                        "origin": origin,
                        "category": category
                    })
        except Exception:
            pass
    return terms



def load_all_glossaries_extended(glossary_path: Optional[str]) -> List[Dict[str, Any]]:
    terms = []
    
    g_dir = Path("03_glossary")
    if glossary_path:
        p = Path(glossary_path)
        if p.is_dir():
            g_dir = p
        elif p.is_file():
            g_dir = p.parent
            
    # 1. Načtení base  protected terms (core)
    core_files = ["protected_terms.tsv", "base_terms.tsv"]
    for f_name in core_files:
        p = g_dir / f_name
        for item in load_glossary_tsv_file_extended(p):
            terms.append(item)
                
    # 2. Načtení referenčních a doplňkových glosářů
    ref_files = [
        "fallout_ref_perks_skills.tsv",
        "fallout_ref_items.tsv",
        "fallout_ref_locations_quests.tsv",
        "style_slang.tsv"
    ]
    for f_name in ref_files:
        p = g_dir / f_name
        for item in load_glossary_tsv_file_extended(p):
            terms.append(item)
                
    return terms



def get_glossary_for_batch(batch: List[Dict[str, Any]], all_terms: List[Tuple[str, str, str]]) -> str:
    batch_terms = []
    combined_texts = " ".join([r.get("en", "") for r in batch]).lower()
    
    for en, cz, category in all_terms:
        if category == "core":
            batch_terms.append((en, cz, category))
        else:
            if en.lower() in combined_texts:
                batch_terms.append((en, cz, category))
                
    lines = ["source\ttarget\tcategory"]
    for en, cz, cat in batch_terms:
        lines.append(f"{en}\t{cz}\t{cat}")
    return "\n".join(lines)




def load_glossary(path) -> str:
    terms = load_all_glossaries(path)
    lines = ["source\ttarget\tcategory"]
    for en, cz, cat in terms:
        lines.append(f"{en}\t{cz}\t{cat}")
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


LOCALIZATION_RULES = (
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
    "New Reno stays New Reno, never Nové Reno. "
    "Hector may become Hektor only if it sounds natural in Czech Fallout style. "
    "Preserve Fallout names and protected terms unless glossary says otherwise. "

    "MEANING RULES: "
    "Never change the language being discussed. Spanish means španělsky, never česky. "
    "home port = domovský přístav. Never translate it as zbrojna. "
    "settle this bay = usadit se v této/téhle zátoce. "
    "lousy idea = pitomý nápad, blbý nápad, pitomá záležitost, or hrozná kravina depending on tone. "
    "rough canvas shirt = hrubá plátěná košile. "
    "red bandana = červený šátek or červená bandana. "
    "on fire = hoření / v plamenech (stav postavy), not v palbě (under fire). "
    "Preserve placeholders like %s, %d, %% exactly. "
    "Avoid bad phrases: 'zemřeš sám za sebe', 'černá známka', 'větrný vítr'. "
    "If the English source has words in ALL CAPS (e.g. WARNING, DANGER, STOP), "
    "keep the Czech translation of those words in ALL CAPS too. "

    "OUTPUT RULES: "
    "Keep file, line_no and id unchanged. "
    "Preserve quotation marks style if possible. "
    "Do not add commentary outside JSON. "
    "Do not add explanations into translated text. "
    "If context_tags or hint_cs are provided for a row, follow hint_cs for meaning; never copy tags into cs."
)

REPAIR_ISSUE_HINTS: Dict[str, str] = {
    "forbidden_brace_format": "Odstraň poškozené závorky typu {0}{ z cs.",
    "metadata_in_cs": "Odstraň metadata (gender_warning, notes, true/false…) z cs — patří jen do JSON polí.",
    "brace_in_cs": "Závorky { } v cs jsou podezřelé — oprav nebo odstraň, pokud nejsou v EN.",
    "combined_gender_form": "Nepoužívej kombinované tvary (mluvil/a) — vyber mužský nebo ženský tvar podle RU.",
    "formal_you_vidite": "Použij neformální tykání: Vidíš, ne Vidíte.",
    "bad_home_port_zbrojna": "home port = domovský přístav, ne zbrojna.",
    "bad_cesareo_translation": "Cesareo nesmí být Caesar/Císař — ponech Cesareo (např. s Cesareem).",
    "trailing_comma_after_quote": "Odstraň čárku za uzavírací uvozovkou na konci věty.",
    "cyrillic_in_cs": "Odstraň cyrilici a mojibake z českého textu.",
    "dash_translated": "EN je jen '-' — cs musí zůstat '-'.",
    "english_leftovers": "Odstraň anglická slova (Library, Base, Cave, Jackals) z českého textu.",
    "bad_morphology": "Oprav morfologii: stimpak/stimpaky, zátky/zátku (ne stimpakú, kryštky).",
    "glossary_violation": "Dodrž glosář — EN termín musí mít správný český ekvivalent ze glossary_tsv.",
    "missing_negation": "EN obsahuje negaci (not/never/no) — cs musí mít odpovídající ne-/žádn-/nic-.",
    "bad_survive_phrase": "Nepoužívej 'přežiješ, nebo zemřeš sám' ani 'zemřeš sám za sebe'.",
    "bad_tesno_testo": "těsné/těsná ≠ těsto — oprav podle EN meaning.",
    "bad_wind_phrase": "Nepoužívej 'větrný vítr' — fair winds = vítr do plachet / ať ti vítr vane do zad.",
    "bad_on_fire_translation": "on fire = hoření/v plamenech, ne v palbě.",
    "bad_goldem_translation": "gold = zlato/zlatý, ne goldem.",
    "bad_krystky_translation": "bottle caps = zátky, ne kryšky/kryštky.",
    "bad_fair_winds": "fair winds nesmí zůstat anglicky — přelož idiom (vítr do plachet).",
    "spanish_as_czech": "Spanish = španělsky, nikdy česky.",
    "translated_spanish_flavor": "No hablo inglés musí zůstat španělsky, ne Nemluvím…",
    "bad_ap_ab_abbreviation": "Action Points = AP, ne AB/AK.",
    "bad_hp_bz_abbreviation": "Hit Points = HP, ne BZ.",
    "bad_xp_zb_abbreviation": "Experience = XP, ne ZB.",
    "bad_ac_oc_abbreviation": "Armor Class = AC, ne OČ.",
    "caps_mismatch": "Slova psaná VELKÝMI v EN musí mít odpovídající VELKÁ písmena v cs.",
}


def build_messages(batch: List[Dict[str, Any]], glossary: str, schema: Dict[str, Any]) -> List[Dict[str, str]]:
    system = (
        "You are a professional Czech localization translator for Fallout: Sonora. "
        "Translate game dialogue into Czech. Use English as the current working text and Russian as meaning/gender reference. "
        "Return ONLY valid JSON matching the provided schema. "
        + LOCALIZATION_RULES
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
                "context_tags": r.get("context_tags") or [],
                "hint_cs": r.get("hint_cs") or "",
                "ru_guide_cs": r.get("ru_guide_cs") or "",
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
        "- EN: %s were critically hit in %s for no damage -> CS: %s Byl jsi kriticky, ale bez poškození zasažen. Místo zásahu: %s (body part is nominative: hlava, not do hlavy)\n"
        "- EN: Have you talked to Cesareo yet? -> CS: Mluvil jsi už s Cesareem? / Mluvila jsi už s Cesareem?\n"
        "- Use ru_guide_cs when present — it disambiguates EN were/was via Russian verb forms.\n\n"
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

    try:
        from file_categories import get_file_category
        from context_tags import enrich_row_context
    except ImportError:
        get_file_category = None
        enrich_row_context = None

    if enrich_row_context and get_file_category:
        by_file: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            f_name = r.get("file", "")
            by_file.setdefault(f_name, []).append(r)
        file_cats = {f: get_file_category(f, fr) for f, fr in by_file.items()}
        for r in rows:
            r["file_category"] = file_cats.get(r.get("file", ""), r.get("file_category", "dialog_scenery"))
            ctx = enrich_row_context(r)
            r["context_tags"] = ctx["tags"]
            r["hint_cs"] = ctx["hint_cs"]
            if ctx.get("ru_guide_cs"):
                r["ru_guide_cs"] = ctx["ru_guide_cs"]

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






GLOSSARY_TERMS = []
def load_glossary_for_server():
    global GLOSSARY_TERMS
    try:
        base_terms = load_all_glossaries(None)
        for row in base_terms:
            en = row[0].strip()
            cz = row[1].strip()
            origin = row[2].strip() if len(row) > 2 else ""
            if en and cz and origin == "core":
                GLOSSARY_TERMS.append((en, cz))
    except Exception as e:
        print("Chyba nacitani glosare:", e)

load_glossary_for_server()

def check_row_issues(en, cs):

    if not cs or not cs.strip():
        return []
    issues = []
    
    # Zakázané vzory (Forbidden)
    if re.search(r"\{[0-9]+\}\{", cs):
        issues.append("forbidden_brace_format")
    if re.search(r"gender_warning|meaning_warning|glossary_warning|\btrue\b|\bfalse\b|\bline_no\b|\bnotes\b", cs, re.IGNORECASE):
        issues.append("metadata_in_cs")
    if "{" in cs or "}" in cs:
        issues.append("brace_in_cs")
        
    # QA varování (Warnings)
    if re.search(r"\b\w+/\w+\b", cs):
        issues.append("combined_gender_form")
    if re.search(r"\bVidíte\b", cs):
        issues.append("formal_you_vidite")
    if re.search(r"\bzbrojna\b|\bzbrojnu\b|\bzbrojny\b", cs, re.IGNORECASE):
        issues.append("bad_home_port_zbrojna")
    if re.search(r"\b(Caesar|Císař|Cesář|Cisar)\b", cs, re.IGNORECASE):
        issues.append("bad_cesareo_translation")
    if re.search(r"[»“\"]\s*,\s*$", cs):
        issues.append("trailing_comma_after_quote")
    if re.search(r"[\u0400-\u04FF]", cs):
        issues.append("cyrillic_in_cs")

    # Haiku Hard Brakes
    if en.strip() == "-" and cs.strip() != "-":
        issues.append("dash_translated")
    if re.search(r"\b(Library|Base|Cave|Jackals)\b", cs, re.IGNORECASE):
        issues.append("english_leftovers")
    if re.search(r"(?i)stimpak[úu]|zátk[ui]|záti?ku", cs):
        issues.append("bad_morphology")
    
    # Glossary Violation
    for en_term, cs_term in GLOSSARY_TERMS:
        if re.search(rf"\b{re.escape(en_term)}\b", en, re.IGNORECASE):
            # Check prefix (min 4 chars) to avoid inflection false positives
            stem_len = min(4, len(cs_term))
            cs_stem = cs_term[:stem_len].lower()
            if cs_stem not in cs.lower():
                issues.append("glossary_violation")
                break
                
    # Negation check (neplatí pro „for no damage“ / „no damage“ — jiný význam)
    if re.search(r"\b(don't|not|never|no)\b", en, re.IGNORECASE):
        if not re.search(r"\bfor\s+no\s+damage\b|\bno\s+damage\b", en, re.IGNORECASE):
            if not re.search(r"\b(ne\w*|žádn\w*|nic\w*|nikd\w*|niko\w*|nijak\w*)\b", cs, re.IGNORECASE):
                issues.append("missing_negation")

    if re.search(r"\bpřežiješ, nebo zemřeš sám\b", cs, re.IGNORECASE):
        issues.append("bad_survive_phrase")
    if re.search(r"\btěsto\b", cs, re.IGNORECASE):
        issues.append("bad_tesno_testo")
    if re.search(r"větrný vítr", cs, re.IGNORECASE):
        issues.append("bad_wind_phrase")
        
    # False Friends (ChatGPT návrhy)
    if "on fire" in en.lower() and re.search(r"\bpalbě\b|\bpalbu\b", cs, re.IGNORECASE):
        issues.append("bad_on_fire_translation")
    if "gold" in en.lower() and re.search(r"\bgoldem\b", cs, re.IGNORECASE):
        issues.append("bad_goldem_translation")
    if re.search(r"\bkryštkami\b|\bkryštky\b", cs, re.IGNORECASE):
        issues.append("bad_krystky_translation")
    if "fair winds" in en.lower() and "fair winds" in cs.lower():
        issues.append("bad_fair_winds")
        
    # Spanish pravidla
    if "Spanish" in en and re.search(r"\bčesky\b|\bcesky\b", cs, re.IGNORECASE):
        issues.append("spanish_as_czech")
    if "No hablo" in en and "Nemluv" in cs:
        issues.append("translated_spanish_flavor")
        
    # Fallout mechanics abbreviations
    if re.search(r"\b(AB|AK)\b", cs):
        issues.append("bad_ap_ab_abbreviation")
    if re.search(r"\b(BZ)\b", cs):
        issues.append("bad_hp_bz_abbreviation")
    if re.search(r"\b(ZB)\b", cs):
        issues.append("bad_xp_zb_abbreviation")
    if re.search(r"\b(OČ)\b", cs):
        issues.append("bad_ac_oc_abbreviation")

    # CAPS preservation: pokud EN má slova CELÁ VELKÝMI (min 2 znaky),
    # CS by měla také obsahovat velká písmena (buď originál nebo překlad)
    en_caps_words = re.findall(r"\b[A-Z]{2,}\b", en)
    # Filtrujeme běžné zkratky, které mají vlastní pravidla (AP, HP, XP, AC)
    skip_abbrevs = {"AP", "HP", "XP", "AC", "AB", "AK", "BZ", "ZB", "OK", "ID", "PC", "NPC", "DJ", "TV", "NCR"}
    en_caps_words = [w for w in en_caps_words if w not in skip_abbrevs]
    if en_caps_words:
        # CS by měla mít aspoň jedno slovo celé velkými (2+ znaky)
        cs_caps_words = re.findall(r"\b[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]{2,}\b", cs)
        cs_caps_words = [w for w in cs_caps_words if w not in skip_abbrevs]
        if not cs_caps_words:
            issues.append("caps_mismatch")

    return issues

def detect_repair_issues(row: Dict[str, Any]) -> List[str]:
    cs = row.get("cs", "") or ""
    en = row.get("en", "") or ""
    return check_row_issues(en, cs)


def build_repair_messages(batch: List[Dict[str, Any]], glossary: str, schema: Dict[str, Any]) -> List[Dict[str, str]]:
    system = (
        "You are a senior Czech localization editor for Fallout: Sonora. "
        "Your task is NOT to retranslate everything freely. "
        "Repair only the Czech translation in the cs field. "
        "Use EN as source text and RU as context/gender reference. "
        "Return ONLY valid JSON matching the provided schema. "
        "Each row lists detected issues and issue_fix_hints — fix exactly those problems while keeping good parts of current_cs. "
        + LOCALIZATION_RULES
    )

    rows = []
    for r in batch:
        issues = detect_repair_issues(r)
        rows.append({
            "file": r["file"],
            "line_no": r["line_no"],
            "id": r["id"],
            "en": r.get("en", ""),
            "ru": r.get("ru", ""),
            "context_tags": r.get("context_tags") or [],
            "hint_cs": r.get("hint_cs") or "",
            "current_cs": r.get("cs", ""),
            "issues": issues,
            "issue_fix_hints": [REPAIR_ISSUE_HINTS.get(i, i) for i in issues],
        })

    payload = {
        "glossary_tsv": glossary,
        "rows": rows,
    }

    prompt = (
        "Repair the following Czech Fallout: Sonora localization rows.\\n"
        "Only fix the Czech cs translation. Do not change file, line_no, or id.\\n"
        "Return JSON only.\\n\\n"
        "JSON schema:\\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\\n\\nDATA:\\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def openrouter_repair_batch(
    batch: List[Dict[str, Any]],
    model: str,
    glossary: str,
    api_key: str,
    timeout: int,
    site_url: Optional[str] = None,
    app_name: Optional[str] = None,
) -> Dict[str, Any]:
    schema = get_translation_schema()
    messages = build_repair_messages(batch, glossary, schema)

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


def repair_cmd(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    out_path = Path(args.out)
    rows = load_jsonl(input_path)
    glossary = load_glossary(args.glossary)

    try:
        from file_categories import get_file_category
        from context_tags import enrich_row_context
    except ImportError:
        get_file_category = None
        enrich_row_context = None

    if enrich_row_context and get_file_category:
        by_file: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            f_name = r.get("file", "")
            by_file.setdefault(f_name, []).append(r)
        file_cats = {f: get_file_category(f, fr) for f, fr in by_file.items()}
        for r in rows:
            r["file_category"] = file_cats.get(r.get("file", ""), r.get("file_category", "dialog_scenery"))
            ctx = enrich_row_context(r)
            r["context_tags"] = ctx["tags"]
            r["hint_cs"] = ctx["hint_cs"]

    candidates = [
        r for r in rows
        if r.get("cs", "").strip()
        and detect_repair_issues(r)
    ]

    if args.limit:
        candidates = candidates[:args.limit]

    print(f"Provider: openrouter")
    print(f"Model: {args.model}")
    print(f"Radku k oprave: {len(candidates)}")

    if not candidates:
        save_jsonl(out_path, rows)
        print(f"Nic k oprave. Vystup zkopirovan: {out_path}")
        return

    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit(
            "Chybi OpenRouter API key. Nastav ho napr.:\\n"
            '$env:OPENROUTER_API_KEY="sk-or-v1-..."\\n'
            "nebo pouzij --api-key."
        )

    key_to_row = {(r["file"], r["line_no"], r["id"]): r for r in rows}

    done = 0
    prompt_tokens_total = 0
    completion_tokens_total = 0
    total_tokens_total = 0

    for i in range(0, len(candidates), args.batch_size):
        batch = candidates[i:i + args.batch_size]
        print(f"Repair batch {i // args.batch_size + 1}: {len(batch)} zaznamu")

        try:
            result = openrouter_repair_batch(
                batch=batch,
                model=args.model,
                glossary=glossary,
                api_key=api_key,
                timeout=args.timeout,
                site_url=args.site_url,
                app_name=args.app_name,
            )
        except Exception as e:
            print(f"CHYBA v repair batchi: {e}", file=sys.stderr)
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

            new_cs = postprocess_cs(item.get("cs", ""))

            row["cs"] = new_cs
            row["status"] = "translated"
            row["repaired"] = True  # mark that this row was fixed by repair_cmd
            row["warnings"] = []
            row["notes"] = ""
            done += 1
            # Progress output
            if getattr(args, "verbose", False):
                total_c = len(candidates)
                pct = (done / total_c) * 100 if total_c else 0
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Opraveno {done}/{total_c} ({pct:.1f}%)")

        save_jsonl(out_path, rows)
        time.sleep(args.sleep)

    print(f"Opraveno/aktualizovano: {done}")
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
            print(f"Odhad ceny pro tento repair beh: ${estimated_usd:.6f}")

VALIDATE_ERROR_ISSUES = frozenset({
    "metadata_in_cs",
    "forbidden_brace_format",
    "spanish_as_czech",
})


def validate_cmd(args: argparse.Namespace) -> None:
    rows = load_jsonl(Path(args.input))
    errors = 0
    warnings = 0
    repairable = 0

    for r in rows:
        cs = r.get("cs", "") or ""
        en = r.get("en", "") or ""
        if not cs.strip():
            continue

        issues = check_row_issues(en, cs)
        if not issues:
            continue

        if any(i in VALIDATE_ERROR_ISSUES for i in issues):
            repairable += 1

        for issue in issues:
            hint = REPAIR_ISSUE_HINTS.get(issue, issue)
            if issue in VALIDATE_ERROR_ISSUES:
                print(f"ERROR: {r['file']}:{r['line_no']} id={r['id']} qa={issue}: {hint} | {cs}")
                errors += 1
            else:
                print(f"WARN: {r['file']}:{r['line_no']} id={r['id']} qa={issue}: {hint} | {cs}")
                warnings += 1

        if r.get("warnings"):
            print(f"REVIEW: {r['file']}:{r['line_no']} id={r['id']} warnings={r.get('warnings')} notes={r.get('notes')}")
            warnings += 1

    print(f"Validace hotova. Errors={errors}, warnings/review={warnings}, opravitelnych={repairable}")
    if errors and not getattr(args, "warn_only", False):
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


    p = sub.add_parser("repair", help="Repair rows flagged by local QA validation")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--glossary", required=False)
    p.add_argument("--model", default="qwen/qwen3-235b-a22b-2507")
    p.add_argument("--api-key", default=None)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--site-url", default=None)
    p.add_argument("--app-name", default="Fallout Sonora CZ Repair")
    p.add_argument("--input-price-per-m", type=float, default=0.0)
    p.add_argument("--output-price-per-m", type=float, default=0.0)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--sleep", type=float, default=0.5)
    p.add_argument("--stop-on-error", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Zobrazovat prubezny progres pri opravnem behu")
    p.set_defaults(func=repair_cmd)

    p = sub.add_parser("validate", help="Validate translated JSONL")
    p.add_argument("--input", required=True)
    p.add_argument("--warn-only", action="store_true",
                   help="Jen vypis — neukonci proces chybovym kodem (pred repair)")
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
