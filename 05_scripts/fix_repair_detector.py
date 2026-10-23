from pathlib import Path
import re

path = Path(r".\05_scripts\sonora_msg_pipeline.py")
s = path.read_text(encoding="utf-8")

new_func = r'''
def detect_repair_issues(row: Dict[str, Any]) -> List[str]:
    cs = row.get("cs", "") or ""
    en = row.get("en", "") or ""
    issues: List[str] = []

    checks = [
        ("metadata_in_cs", re.compile(r"gender_warning|meaning_warning|glossary_warning|\btrue\b|\bfalse\b|\bline_no\b|\bnotes\b", re.IGNORECASE)),
        ("formal_you_vidite", re.compile(r"\bVidíte\b")),
        ("bad_home_port_zbrojna", re.compile(r"\bzbrojna\b|\bzbrojnu\b|\bzbrojny\b", re.IGNORECASE)),
        ("bad_cesareo_translation", re.compile(r"\b(Caesar|Císař|Cesář|Cisar)\b", re.IGNORECASE)),
        ("trailing_comma_after_quote", re.compile(r"[»“\"]\s*,\s*$")),
        ("cyrillic_in_cs", re.compile(r"[\u0400-\u04FF]")),
        ("bad_survive_phrase", re.compile(r"zemřeš sám za sebe|přežiješ, nebo zemřeš sám", re.IGNORECASE)),
        ("bad_tesno_testo", re.compile(r"\btěsto\b", re.IGNORECASE)),
        ("bad_wind_phrase", re.compile(r"větrný vítr", re.IGNORECASE)),
        ("bad_black_mark", re.compile(r"černá známka", re.IGNORECASE)),
        ("bad_new_reno", re.compile(r"Nové Reno", re.IGNORECASE)),
    ]

    for label, pattern in checks:
        if pattern.search(cs):
            issues.append(label)

    if "{" in cs or "}" in cs:
        issues.append("brace_in_cs")

    if "Spanish" in en and re.search(r"\bčesky\b|\bcesky\b", cs, re.IGNORECASE):
        issues.append("spanish_as_czech")

    if "No hablo" in en and "Nemluv" in cs:
        issues.append("translated_spanish_flavor")

    return sorted(set(issues))
'''

pattern = r"def detect_repair_issues\(row: Dict\[str, Any\]\) -> List\[str\]:.*?\n\ndef build_repair_messages"
replacement = new_func + "\n\ndef build_repair_messages"

s2, n = re.subn(pattern, lambda m: replacement, s, count=1, flags=re.DOTALL)

if n != 1:
    raise SystemExit(f"Nepodarilo se najit a nahradit detect_repair_issues. Pocet nahrad: {n}")

path.write_text(s2, encoding="utf-8", newline="\n")
print("detect_repair_issues opraven.")
