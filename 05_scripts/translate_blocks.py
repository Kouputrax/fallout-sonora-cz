import json
import sys
import argparse
import time
import requests
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent

def check_hard_brakes(en, cs):
    issues = []
    # 1. Dash Translated
    if en.strip() == "-" and cs.strip() != "-":
        issues.append("dash_translated")
    # 2. English Leftovers
    if re.search(r"\b(Library|Base|Cave|Jackals)\b", cs, re.IGNORECASE):
        issues.append("english_leftovers")
    # 3. Bad Morphology
    if re.search(r"(?i)stimpak[úu]|zátk[ui]|záti?ku", cs):
        issues.append("bad_morphology")
    # 4. Negation Check
    if re.search(r"\b(don't|not|never|no)\b", en, re.IGNORECASE):
        if not re.search(r"\bne[a-z]*\b", cs, re.IGNORECASE) and not re.search(r"\bne\b", cs, re.IGNORECASE):
            issues.append("missing_negation")
    # 5. Cyrillic
    if re.search(r"[\u0400-\u04FF]", cs):
        issues.append("cyrillic_in_cs")
    return issues

def translate_block_openrouter(unit, lines_to_translate, glossary_hints, api_key, model="anthropic/claude-3-haiku"):
    if not lines_to_translate: return {}
    prompt = "Jsi profesionální překladatel her do češtiny (RPG Fallout). Přelož následující blok konverzace.\n\n"
    if glossary_hints:
        prompt += "POVINNÝ SLOVNÍK PRO TENTO BLOK (dodržuj tyto překlady!):\n"
        for en, cs in glossary_hints:
            prompt += f"- {en} -> {cs}\n"
        prompt += "\n"
    prompt += """STYLISTICKÁ PRAVIDLA:
1. Tón hry je drsný, postapokalyptický, cynický. Obsahuje slang i sprostá slova.
2. ZACHOVEJ VŠECHNY TAGY A ZNAČKY. Pokud je v angličtině {100}{}{Text}, v češtině musí být {100}{}{Překlad}.
3. Nikdy neměň ID řádků (číslo v hranatých závorkách).
4. Překládej jako rodilý Čech. Významy musí být přirozené, ne doslovný překlad (Czenglish).
5. Krátké odpovědi hráče ("Yes.", "No.", "Who are you?") zní často jako by si postavy vykaly, pokud nemluví s dítětem nebo zvířetem.
6. ZÁKAZ PŘEKLADU ŠPANĚLŠTINY: Některé postavy používají španělská slova a fráze (např. amigo, amiga, pendejo, hombre, hola, adios). TATO SLOVA ZCELA IGNORUJ PŘI PŘEKLADU A NECH JE V ORIGINÁLNÍM ZNĚNÍ.

--- Boj a Gore ---
EN: "You critically hit him in the head, turning his skull into a blood-splattered canoe."
CS: "Kriticky jsi ho zasáhl do hlavy a udělal tak z jeho lebky kánoi plnou krve."
EN: "You hit him in the groin. He falls to the ground, grabbing his package in pure agony."
CS: "Zasáhl jsi ho do slabin. Padl na zem a v čiré agónii se chytil za své nádobíčko."
EN: "The shot blows a hole the size of a melon in his chest."
CS: "Výstřel mu udělal do hrudníku díru o velikosti melounu."
EN: "You had your armor bypassed."
CS: "Byl jsi zasažen do nechráněného místa."

--- Slang, nadávky a New Reno ---
EN: "Hey smoothskin, you looking for a good time?"
CS: "Hej hezounku, hledáš nějaký povyražení?"
EN: "Eat lead, you motherfucker!"
CS: "Žer olovo, ty zkurvysyne!"
EN: "I ain't got time for your bullshit."
CS: "Na tvoje kecy fakt nemám čas."
EN: "Get the fuck out of my face."
CS: "Zmiz mi z očí do prdele."
EN: "Son of a bitch!"
CS: "Zkurvysyne!"
EN: "You piece of shit."
CS: "Ty kuse hovna."
EN: "What the hell do you want?"
CS: "Co sakra chceš?"

--- UI, popisy a systémové hlášky ---
EN: "You see a bruised and battered man."
CS: "Vidíš pomláceného a pobitého muže."
EN: "You see Hector."
CS: "Vidíš Hektora."
EN: "You gain 500 experience points."
CS: "Získáváš 500 zkušenostních bodů."
EN: "You notice nothing out of the ordinary."
CS: "Nevšiml sis ničeho neobvyklého."
EN: "I don't speak Spanish."
CS: "Nemluvím španělsky."
EN: "bare hands"
CS: "holé ruce"
EN: "on fire"
CS: "v plamenech"
----------------------------------------
"""
    prompt += f"Context - Location: {unit.get('location')}, NPC: {unit.get('npc_name', '?')}, File: {unit.get('file')}\n"
    prompt += "Previous context (DO NOT TRANSLATE):\n"
    for c in unit.get("previous_context", []):
        prompt += f"[{c['id']}] {c['text']}\n"
    
    prompt += "\nLINES TO TRANSLATE (from EN):\n"
    for c in unit.get("en_lines", []):
        prompt += f"[{c['id']}] {c['text']}\n"
        
    prompt += "\nNext context (DO NOT TRANSLATE):\n"
    for c in unit.get("next_context", []):
        prompt += f"[{c['id']}] {c['text']}\n"
        
    prompt += """
VÝSTUPNÍ FORMÁT:
Vrať POUZE validní JSON mapující ID (jako string) na český překlad. Nevypisuj žádný text před ani za JSON.
Příklad:
{
  "200": "Hej. Nemluvím španělsky.",
  "201": "Dobře, jdeme."
}

PRAVIDLA:
1. Nesmíš vynechat žádné ID z "LINES TO TRANSLATE".
2. Nesmíš přidat žádné ID navíc.
3. Technické texty jako "-", "[BACK]", "[DONE]" překládej přesně jako "-", "[BACK]", "[DONE]" bez rozepisování.
"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }
    
    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
    if resp.status_code != 200:
        print(f"Error {resp.status_code}: {resp.text}")
        return None
        
    resp_json = resp.json()
    content = resp_json["choices"][0]["message"]["content"].strip()
    
    # Strip markdown block if present
    if content.startswith("```json"):
        content = content[7:]
    if content.endswith("```"):
        content = content[:-3]
        
    try:
        return json.loads(content.strip())
    except Exception as e:
        print(f"JSON Parse Error: {e}\nContent was: {content}")
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(ROOT/"02_work"/"translated"/"translation_units.jsonl"))
    parser.add_argument("--db", default=str(ROOT/"02_work"/"translated"/"sonora_translated.jsonl"))
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--model", default="anthropic/claude-3-haiku")
    args = parser.parse_args()
    
    # Auto-regenerate translation_units.jsonl if missing or stale
    units_path = Path(args.input)
    db_path = Path(args.db)
    if not units_path.exists() or (db_path.exists() and units_path.stat().st_mtime < db_path.stat().st_mtime):
        print("Regenerating translation_units.jsonl...")
        import subprocess
        subprocess.run([
            sys.executable, str(ROOT / "05_scripts" / "segment_blocks.py"),
            "--input", args.db,
            "--out", args.input
        ], check=True)
    
    # Load Glossary
    print("Loading Glossary...")
    glossary_terms = []
    glossary_path = ROOT / "03_glossary" / "base_terms.tsv"
    if glossary_path.exists():
        import csv
        with open(glossary_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f.read().splitlines(), delimiter="\t")
            for row in reader:
                if not row: continue
                en = (row.get("source_en") or row.get("english_cue") or "").strip()
                cz = (row.get("target_cs") or row.get("neutral_cz") or "").strip()
                if en and cz:
                    glossary_terms.append((en, cz))

    # Load DB
    print("Loading DB...")
    db_rows = {}
    tm_exact = {}
    db_order = []
    with open(args.db, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                key = f"{row['file']}||{row['id']}"
                db_rows[key] = row
                db_order.append(key)
                
                en_txt = row.get("en", "").strip()
                cs_txt = row.get("cs", "").strip()
                status = row.get("status", "")
                if en_txt and cs_txt and status in ("aligned_confirmed", "aligned_review", "translated"):
                    # Ukládáme jen pokud nemáme, nebo pokud je to lepší tier (zde zjednodušeně první)
                    if en_txt not in tm_exact:
                        tm_exact[en_txt] = cs_txt
                
    # Load units
    units = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                units.append(json.loads(line))
                
    print(f"Loaded {len(units)} units. Translating up to {args.limit}...")
    
    translated_count = 0
    skipped_count = 0
    failed_api = 0
    max_api_failures = 5
    for unit in units:
        if translated_count >= args.limit:
            break
        
        lines_to_translate = []
        auto_translated = {}
        for en_line in unit["en_lines"]:
            key = f"{unit['file']}||{en_line['id']}"
            row = db_rows.get(key)
            text = en_line["text"].strip()
            
            if row and (row.get("cs") or "").strip():
                # Už má lokální překlad, neposílat
                pass
            elif text in tm_exact:
                # TM Exact shoda napříč celou databází
                auto_translated[str(en_line["id"])] = tm_exact[text]
            else:
                lines_to_translate.append(en_line)
                
        if not lines_to_translate and not auto_translated:
            skipped_count += 1
            continue
            
        res = auto_translated.copy()
        if lines_to_translate:
            print(f"Translating block {unit['file']} ({len(lines_to_translate)} AI lines, {len(auto_translated)} TM lines)...")
            
            # Find glossary terms
            hints = []
            combined_text = " ".join([l["text"].lower() for l in lines_to_translate])
            for g_en, g_cs in glossary_terms:
                if re.search(rf"\b{re.escape(g_en.lower())}\b", combined_text):
                    hints.append((g_en, g_cs))
            
            try:
                ai_res = translate_block_openrouter(unit, lines_to_translate, hints, args.api_key, args.model)
                if ai_res:
                    res.update(ai_res)
                    failed_api = 0
                else:
                    failed_api += 1
                    print(f"API vrátilo prázdnou odpověď ({failed_api}/{max_api_failures})")
            except Exception as e:
                failed_api += 1
                print(f"ERROR translating block: {e} ({failed_api}/{max_api_failures})")
            if failed_api >= max_api_failures:
                print("Příliš mnoho chyb API — ukončuji. Zkontroluj klíč, síť a model.")
                break
            if not res:
                continue
        else:
            print(f"Translating block {unit['file']} (0 AI lines, {len(auto_translated)} TM lines)...")
            
        if res:
            # Validate IDs (against original unit)
            expected_ids = set([str(x["id"]) for x in unit["en_lines"]])
            got_ids = set(res.keys())
            
            missing = expected_ids - got_ids
            extra = got_ids - expected_ids
            
            if missing:
                print(f"WARNING: Missing IDs: {missing}")
            if extra:
                print(f"WARNING: Extra IDs: {extra}")
                # Remove extra IDs to prevent corruption
                for eid in extra:
                    del res[eid]
                
            # Apply translations
            for en_line in unit["en_lines"]:
                line_id = str(en_line["id"])
                if line_id in res:
                    cs_text = res[line_id]
                    key = f"{unit['file']}||{line_id}"
                    if key in db_rows:
                        db_rows[key]["cs"] = cs_text
                        db_rows[key]["status"] = "translated"
                        if line_id in auto_translated:
                            db_rows[key]["status"] = "aligned_review" # Auto-propagated = review
                        # Run hard brakes
                        issues = check_hard_brakes(en_line["text"], cs_text)
                        db_rows[key]["live_issues"] = issues
                        
            translated_count += 1
        time.sleep(1) # rate limit
    
    if skipped_count:
        print(f"Skipped {skipped_count} already-translated blocks.")
        
    print(f"Translated {translated_count} blocks. Saving DB...")
    with open(args.db, "w", encoding="utf-8") as f:
        for k in db_order:
            f.write(json.dumps(db_rows[k], ensure_ascii=False) + "\n")
            
    print("Done!")

if __name__ == "__main__":
    main()
