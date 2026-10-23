import os
import re
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "04_reference"
GLOSSARY_DIR = ROOT / "03_glossary"

# Priority referencí: Nevada (nejvyšší) -> Fallout 2 -> Fallout 1 (nejnižší)
GAMES_PRIORITY = ["nevada_cz", "fallout2_cz", "fallout1_cz"]

# Kódování msg souborů
# Fallout 1 & 2 CZ bývá v cp1250, EN v latin-1
def read_msg_guess(path: Path) -> str:
    encodings = ["utf-8-sig", "utf-8", "cp1250", "cp1251", "latin-1"]
    data = path.read_bytes()
    for enc in encodings:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", errors="replace")

def parse_msg(text: str) -> dict:
    entries = {}
    idx = 0
    n = len(text)
    while idx < n:
        while idx < n and text[idx].isspace():
            idx += 1
        if idx >= n:
            break
        
        if text[idx] != '{':
            while idx < n and text[idx] != '\n':
                idx += 1
            continue
        
        # ID
        start = idx + 1
        end = text.find('}', start)
        if end == -1: break
        msg_id_str = text[start:end]
        try:
            msg_id = int(msg_id_str.strip())
        except ValueError:
            idx = end + 1
            continue
        
        # Sound
        idx = end + 1
        while idx < n and text[idx].isspace():
            idx += 1
        if idx >= n or text[idx] != '{':
            continue
        start = idx + 1
        end = text.find('}', start)
        if end == -1: break
        
        # Text
        idx = end + 1
        while idx < n and text[idx].isspace():
            idx += 1
        if idx >= n or text[idx] != '{':
            continue
        start = idx + 1
        
        braces_count = 1
        i = start
        while i < n:
            if text[i] == '}':
                braces_count -= 1
                if braces_count == 0:
                    break
            elif text[i] == '{':
                braces_count += 1
            i += 1
        if i >= n: break
        
        msg_text = text[start:i]
        entries[msg_id] = msg_text.strip()
        idx = i + 1
    return entries

def find_file_case_insensitive(root: Path, rel_path_parts: list) -> Path:
    # Hledá soubor bez ohledu na velikost písmen v cestě i názvu
    current = root
    for part in rel_path_parts:
        if not current.exists():
            return None
        found = False
        for child in current.iterdir():
            if child.name.lower() == part.lower():
                current = child
                found = True
                break
        if not found:
            return None
    return current

def build_glossary_for_file(game_cz_dir: str, game_en_dir: str, rel_path_parts: list, id_filter_fn=None) -> dict:
    cz_root = REFERENCE_DIR / game_cz_dir
    en_root = REFERENCE_DIR / game_en_dir
    
    cz_file = find_file_case_insensitive(cz_root, rel_path_parts)
    en_file = find_file_case_insensitive(en_root, rel_path_parts)
    
    if not cz_file or not en_file or not cz_file.exists() or not en_file.exists():
        return {}
    
    cz_entries = parse_msg(read_msg_guess(cz_file))
    en_entries = parse_msg(read_msg_guess(en_file))
    
    glossary = {}
    for msg_id, en_text in en_entries.items():
        if not en_text:
            continue
        if id_filter_fn and not id_filter_fn(msg_id):
            continue
        
        cz_text = cz_entries.get(msg_id)
        if not cz_text:
            continue
            
        # Očistíme texty (odstraníme zalomení řádků a přebytečné mezery)
        en_clean = " ".join(en_text.split())
        cz_clean = " ".join(cz_text.split())
        
        # Filtrujeme příliš dlouhé texty, čísla, prázdné znaky atd.
        if len(en_clean) < 2 or len(en_clean) > 50:
            continue
        if re.fullmatch(r"[\d\s\-\+\.,:%/()xX]+", en_clean):
            continue
            
        # Slovníkový záznam
        glossary[en_clean.lower()] = {
            "source_en": en_clean,
            "target_cs": cz_clean,
            "origin": game_cz_dir
        }
    return glossary

def main():
    print("=== START GENERACE REFERENČNÍHO GLOSÁŘE ===")
    
    # 1. Slovník předmětů (pro_item.msg)
    # xxx00 = Název předmětu
    def item_name_filter(msg_id):
        return msg_id % 100 == 0
        
    items_glossary = {}
    # Skenujeme od nejnižší priority k nejvyšší, aby nejvyšší přepsala starší záznamy
    for game in reversed(GAMES_PRIORITY):
        cz_dir = game
        en_dir = game.replace("_cz", "_en")
        
        print(f"Skenuji předměty pro {game}...")
        game_items = build_glossary_for_file(
            cz_dir, en_dir, ["text", "english", "game", "pro_item.msg"], item_name_filter
        )
        items_glossary.update(game_items)
        
    # 2. Slovník perků, skillů, traitů a statů
    perk_skills_glossary = {}
    
    # Perky (perk.msg) - názvy jsou na sudých ID od 100 výš (100, 102, 104...)
    def perk_name_filter(msg_id):
        return msg_id >= 100 and msg_id % 2 == 0
        
    # Skilly (skill.msg) - názvy jsou na ID 100, 101... 117 atd.
    def skill_name_filter(msg_id):
        return 100 <= msg_id <= 150 # názvy skillů
        
    # Traity (trait.msg) - názvy na ID 120+
    def trait_name_filter(msg_id):
        return msg_id >= 120 and msg_id % 3 == 0
        
    # Staty (stat.msg) - názvy na ID 0-20
    def stat_name_filter(msg_id):
        return 0 <= msg_id < 50
        
    for game in reversed(GAMES_PRIORITY):
        cz_dir = game
        en_dir = game.replace("_cz", "_en")
        
        print(f"Skenuji perky, skilly, traity a staty pro {game}...")
        
        # Perky
        perk_skills_glossary.update(build_glossary_for_file(
            cz_dir, en_dir, ["text", "english", "game", "perk.msg"], perk_name_filter
        ))
        # Skilly
        perk_skills_glossary.update(build_glossary_for_file(
            cz_dir, en_dir, ["text", "english", "game", "skill.msg"], skill_name_filter
        ))
        # Traity
        perk_skills_glossary.update(build_glossary_for_file(
            cz_dir, en_dir, ["text", "english", "game", "trait.msg"], trait_name_filter
        ))
        # Staty
        perk_skills_glossary.update(build_glossary_for_file(
            cz_dir, en_dir, ["text", "english", "game", "stat.msg"], stat_name_filter
        ))

    # 3. Slovník lokací a questů (worldmap.msg, quests.msg)
    location_quests_glossary = {}
    
    for game in reversed(GAMES_PRIORITY):
        cz_dir = game
        en_dir = game.replace("_cz", "_en")
        
        print(f"Skenuji lokace a questy pro {game}...")
        
        # Lokace (worldmap.msg)
        location_quests_glossary.update(build_glossary_for_file(
            cz_dir, en_dir, ["text", "english", "game", "worldmap.msg"]
        ))
        # Questy (quests.msg)
        location_quests_glossary.update(build_glossary_for_file(
            cz_dir, en_dir, ["text", "english", "game", "quests.msg"]
        ))

    # Zápis do TSV souborů
    GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
    
    # Uložení předmětů
    items_path = GLOSSARY_DIR / "fallout_ref_items.tsv"
    with items_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["source_en", "target_cs", "origin", "category"])
        for _, item in sorted(items_glossary.items()):
            writer.writerow([item["source_en"], item["target_cs"], item["origin"], "item"])
            
    # Uložení perků a skillů
    perks_path = GLOSSARY_DIR / "fallout_ref_perks_skills.tsv"
    with perks_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["source_en", "target_cs", "origin", "category"])
        for _, item in sorted(perk_skills_glossary.items()):
            writer.writerow([item["source_en"], item["target_cs"], item["origin"], "perk_skill"])
            
    # Uložení lokací a questů
    locs_path = GLOSSARY_DIR / "fallout_ref_locations_quests.tsv"
    with locs_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["source_en", "target_cs", "origin", "category"])
        for _, item in sorted(location_quests_glossary.items()):
            writer.writerow([item["source_en"], item["target_cs"], item["origin"], "location_quest"])

    print("\n=== GENERACE DOKONČENA ===")
    print(f"Nalezeno unikátních předmětů: {len(items_glossary)} (uloženo do {items_path.relative_to(ROOT)})")
    print(f"Nalezeno unikátních perků/skillů/statů: {len(perk_skills_glossary)} (uloženo do {perks_path.relative_to(ROOT)})")
    print(f"Nalezeno unikátních lokací/questů: {len(location_quests_glossary)} (uloženo do {locs_path.relative_to(ROOT)})")

if __name__ == "__main__":
    main()
