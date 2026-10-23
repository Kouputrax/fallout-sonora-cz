from pathlib import Path

path = Path(r".\05_scripts\sonora_msg_pipeline.py")
s = path.read_text(encoding="utf-8")

if "import os" not in s:
    s = s.replace("import json\n", "import json\nimport os\n", 1)

repair_code = r'''

def detect_repair_issues(row: Dict[str, Any]) -> List[str]:
    cs = row.get("cs", "") or ""
    en = row.get("en", "") or ""
    issues: List[str] = []

    if row.get("warnings"):
        issues.append("model_warning")

    checks = [
        ("metadata_in_cs", re.compile(r"gender_warning|meaning_warning|glossary_warning|\\btrue\\b|\\bfalse\\b|\\bline_no\\b|\\bnotes\\b", re.IGNORECASE)),
        ("combined_gender_form", re.compile(r"\\b\\w+/\\w+\\b", re.IGNORECASE)),
        ("formal_you_vidite", re.compile(r"\\bVidíte\\b")),
        ("bad_home_port_zbrojna", re.compile(r"\\bzbrojna\\b|\\bzbrojnu\\b|\\bzbrojny\\b", re.IGNORECASE)),
        ("bad_cesareo_translation", re.compile(r"\\b(Caesar|Císař|Cesář|Cisar)\\b", re.IGNORECASE)),
        ("trailing_comma_after_quote", re.compile(r"[»“\\\"]\\s*,\\s*$")),
        ("cyrillic_in_cs", re.compile(r"[\\u0400-\\u04FF]")),
        ("bad_survive_phrase", re.compile(r"zemřeš sám za sebe|přežiješ, nebo zemřeš sám", re.IGNORECASE)),
        ("bad_tesno_testo", re.compile(r"\\btěsto\\b", re.IGNORECASE)),
        ("bad_wind_phrase", re.compile(r"větrný vítr", re.IGNORECASE)),
        ("bad_black_mark", re.compile(r"černá známka", re.IGNORECASE)),
        ("bad_new_reno", re.compile(r"Nové Reno", re.IGNORECASE)),
    ]

    for label, pattern in checks:
        if pattern.search(cs):
            issues.append(label)

    if "{" in cs or "}" in cs:
        issues.append("brace_in_cs")

    if "Spanish" in en and re.search(r"\\bčesky\\b|\\bcesky\\b", cs, re.IGNORECASE):
        issues.append("spanish_as_czech")

    if "No hablo" in en and "Nemluv" in cs:
        issues.append("translated_spanish_flavor")

    return sorted(set(issues))


def build_repair_messages(batch: List[Dict[str, Any]], glossary: str, schema: Dict[str, Any]) -> List[Dict[str, str]]:
    system = (
        "You are a senior Czech localization editor for Fallout: Sonora. "
        "Your task is NOT to retranslate everything freely. "
        "Repair only the Czech translation in the cs field. "
        "Use EN as source text and RU as context/gender reference. "
        "Return ONLY valid JSON matching the provided schema. "
        "Keep file, line_no and id unchanged. "
        "The cs field must contain only final Czech in-game text. "
        "Never add notes, metadata, JSON labels or explanations into cs. "
        "Never output Cyrillic characters in Czech text. "
        "Preserve placeholders like %s, %d, %% exactly. "
        "Preserve Fallout names and protected terms unless glossary says otherwise. "
        "New Reno stays New Reno, never Nové Reno. "
        "No hablo inglés stays No hablo inglés. "
        "amigo, amiga, compañero and similar Spanish flavor words may stay Spanish. "
        "Fix mojibake such as Ў, Cyrillic c in compañero, or Russian words inside Czech text. "
        "Avoid bad phrases: 'zemřeš sám za sebe', 'černá známka', 'větrný vítr'. "
    )

    rows = []
    for r in batch:
        rows.append({
            "file": r["file"],
            "line_no": r["line_no"],
            "id": r["id"],
            "en": r.get("en", ""),
            "ru": r.get("ru", ""),
            "current_cs": r.get("cs", ""),
            "issues": detect_repair_issues(r),
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

    candidates = [
        r for r in rows
        if r.get("status") == "translated"
        and r.get("cs", "").strip()
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

            new_cs = item.get("cs", "")
            pp = globals().get("postprocess_cs")
            if callable(pp):
                new_cs = pp(new_cs)

            row["cs"] = new_cs
            row["status"] = "translated"
            row["warnings"] = []
            row["notes"] = ""
            done += 1

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
'''

if "def detect_repair_issues(" not in s:
    marker = "\ndef validate_cmd(args: argparse.Namespace) -> None:\n"
    if marker not in s:
        raise SystemExit("Nenalezen marker validate_cmd. Patch zastaven.")
    s = s.replace(marker, "\n" + repair_code + marker, 1)

repair_parser = r'''
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
    p.set_defaults(func=repair_cmd)

'''

if 'sub.add_parser("repair"' not in s:
    marker = '    p = sub.add_parser("validate", help="Validate translated JSONL")'
    if marker not in s:
        raise SystemExit("Nenalezen marker validate parser. Patch zastaven.")
    s = s.replace(marker, repair_parser + marker, 1)

path.write_text(s, encoding="utf-8", newline="\n")
print("Repair command patch hotov.")
