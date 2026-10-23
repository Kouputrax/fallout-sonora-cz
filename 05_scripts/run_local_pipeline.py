#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
run_local_pipeline.py

Integrovaný lokální spouštěč překladu pro Fallout: Sonora CZ.
Poskytuje jednoduché, přehledné interaktivní menu v češtině,
které kompletně stíní uživatele od nutnosti pamatovat si
nebo psát složité PowerShell CLI příkazy.
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from typing import Dict, Any

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_SCRIPT = ROOT / "05_scripts" / "sonora_msg_pipeline.py"
CONFIG_FILE = ROOT / "05_scripts" / "pipeline_config.json"

def load_env_file() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    os.environ[k] = v
        except Exception as e:
            print(f"Varování: Chyba při načítání .env souboru: {e}")

def save_env_file(key: str) -> None:
    env_path = ROOT / ".env"
    try:
        lines = []
        replaced = False
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("OPENROUTER_API_KEY"):
                    lines.append(f"OPENROUTER_API_KEY={key}")
                    replaced = True
                else:
                    lines.append(line)
        if not replaced:
            lines.append(f"OPENROUTER_API_KEY={key}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("API klíč byl úspěšně trvale uložen do souboru .env.")
    except Exception as e:
        print(f"Chyba při zápisu do .env: {e}")


DEFAULT_CONFIG = {
    "provider": "ollama",
    "ollama_host": "http://localhost:11434",
    "ollama_model": "qwen2.5:7b",
    "openrouter_model": "qwen/qwen-2.5-72b-instruct",
    "openrouter_repair_model": "qwen/qwen3-235b-a22b-2507",
    "en_root": "01_sources/sonora_en",
    "ru_root": "01_sources/sonora_ru",
    "export_file": "02_work/export/sonora_export.jsonl",
    "translated_file": "02_work/translated/sonora_translated.jsonl",
    "repaired_file": "02_work/translated/sonora_translated_repaired.jsonl",
    "glossary_dir": "03_glossary",
    "output_root": "06_output/czech_text"
}

def load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                cfg = json.load(f)
                # Sloučit s výchozími pro případ chybějících polí
                for k, v in DEFAULT_CONFIG.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except Exception as e:
            print(f"Varování: Nepodařilo se načíst konfiguraci: {e}. Používám výchozí.")
    return DEFAULT_CONFIG.copy()

def save_config(cfg: Dict[str, Any]) -> None:
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Chyba při ukládání konfigurace: {e}")

def run_command(args: list) -> bool:
    cmd = [sys.executable, str(PIPELINE_SCRIPT)] + args
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode == 0
    except Exception as e:
        print(f"Chyba při spuštění příkazu: {e}")
        return False

def show_status(cfg: Dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("      AKTIVNÍ STAV PROJEKTU A PIPELINE (Fallout Sonora CZ)")
    print("=" * 60)
    
    # 1. Kontrola souborů
    en_path = ROOT / cfg["en_root"]
    ru_path = ROOT / cfg["ru_root"]
    export_path = ROOT / cfg["export_file"]
    trans_path = ROOT / cfg["translated_file"]
    rep_path = ROOT / cfg["repaired_file"]
    
    print(f" Zdroj EN:      {cfg['en_root']} -> {'[OK]' if en_path.exists() else '[CHYBÍ - vložte originální EN .msg soubory]'}")
    print(f" Zdroj RU:      {cfg['ru_root']} -> {'[OK]' if ru_path.exists() else '[CHYBÍ - doporučeno pro gender kontext]'}")
    
    if export_path.exists():
        lines = 0
        try:
            with export_path.open("r", encoding="utf-8") as f:
                lines = sum(1 for _ in f)
            print(f" Export:        {cfg['export_file']} -> [OK] ({lines} řádků k překladu)")
        except Exception:
            print(f" Export:        {cfg['export_file']} -> [POŠKOZEN]")
    else:
        print(f" Export:        {cfg['export_file']} -> [CHYBÍ - spusťte Export (Volba 1)]")

    if trans_path.exists():
        translated = 0
        total = 0
        try:
            with trans_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        total += 1
                        row = json.loads(line)
                        if row.get("cs"):
                            translated += 1
            percent = (translated / total * 100) if total > 0 else 0
            print(f" Překlad:       {cfg['translated_file']} -> [OK] (Přeloženo {translated}/{total} - {percent:.1f}%)")
        except Exception:
            print(f" Překlad:       {cfg['translated_file']} -> [KONTROLA NUTNÁ / PRÁZDNÝ]")
    else:
        print(f" Překlad:       {cfg['translated_file']} -> [CHYBÍ - přeložte zkušební dávku nebo plný soubor]")

    # 2. Glosáře
    g_dir = ROOT / cfg["glossary_dir"]
    if g_dir.exists():
        tsv_files = list(g_dir.glob("*.tsv"))
        print(f" Glosáře:       {cfg['glossary_dir']} -> [OK] (Nalezeno {len(tsv_files)} slovníků)")
    else:
        print(f" Glosáře:       {cfg['glossary_dir']} -> [CHYBÍ]")

    # 3. Model a Provider
    print("-" * 60)
    print(f" AKTIVNÍ NASTAVENÍ AI:")
    print(f" Výchozí Provider: {cfg['provider'].upper()}")
    if cfg["provider"] == "ollama":
        print(f"   Ollama Host:    {cfg['ollama_host']}")
        print(f"   Ollama Model:   {cfg['ollama_model']}")
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        key_status = "Nastaven v $env:OPENROUTER_API_KEY" if api_key else "CHYBÍ v $env:OPENROUTER_API_KEY"
        print(f"   OpenRouter Key: {key_status}")
        print(f"   Překlad Model:  {cfg['openrouter_model']}")
    print(f"   Opravný Model:  {cfg['openrouter_repair_model']} (vždy přes OpenRouter)")
    print("=" * 60)

def change_settings(cfg: Dict[str, Any]) -> None:
    print("\n" + "-" * 50)
    print("           NASTAVENÍ PŘEKLADAČE A MODELŮ")
    print("-" * 50)
    print(f"[1] Změnit providera (aktuálně: {cfg['provider']})")
    print(f"[2] Nastavit Ollama Host (aktuálně: {cfg['ollama_host']})")
    print(f"[3] Nastavit Ollama Model (aktuálně: {cfg['ollama_model']})")
    print(f"[4] Nastavit OpenRouter Model (aktuálně: {cfg['openrouter_model']})")
    print(f"[5] Zadat/Zkontrolovat OpenRouter API klíč")
    print("[0] Návrat do hlavního menu")
    
    volba = input("\nVyberte možnost: ").strip()
    if volba == "1":
        p = input("Zadejte 'ollama' nebo 'openrouter': ").strip().lower()
        if p in ["ollama", "openrouter"]:
            cfg["provider"] = p
            print(f"Provider změněn na {p}.")
        else:
            print("Neplatná volba.")
    elif volba == "2":
        h = input(f"Zadejte hosta [{cfg['ollama_host']}]: ").strip()
        if h:
            cfg["ollama_host"] = h
    elif volba == "3":
        m = input(f"Zadejte název lokálního modelu v Ollamě [{cfg['ollama_model']}]: ").strip()
        if m:
            cfg["ollama_model"] = m
    elif volba == "4":
        m = input(f"Zadejte název modelu v OpenRouteru [{cfg['openrouter_model']}]: ").strip()
        if m:
            cfg["openrouter_model"] = m
    elif volba == "5":
        key = input("Zadejte OpenRouter API klíč (sk-or-v1-...): ").strip()
        if key:
            os.environ["OPENROUTER_API_KEY"] = key
            ulozit = input("Chcete tento klíč trvale uložit do souboru .env v projektu? (a/n) [výchozí: a]: ").strip().lower()
            if ulozit in ["a", "ano", "y", "yes", ""]:
                save_env_file(key)
            else:
                print("API klíč byl nastaven pouze pro tuto běžící relaci.")
    elif volba == "0":
        return
    else:
        print("Neplatná volba.")
    save_config(cfg)

def main_menu():
    load_env_file()
    cfg = load_config()
    
    while True:
        show_status(cfg)
        print("                 HLAVNÍ MENU PIPELINE")
        print("-" * 60)
        print(" [1] EXPORT + SYNC - export .msg a sloučení do pracovní databáze")
        print(" [1.5] SPÁROVAT S F1/F2/NEVADA - (součást Přípravy, s QA pravidly)")
        print(" [P] PŘÍPRAVA - sync + F2 + kontextové značky (před překladem)")
        print(" [2] TEST OLLAMA - rychlý překlad 10 řádků přes lokální Ollamu")
        print(" [3] TEST OPENROUTER - rychlý překlad 10 řádků přes OpenRouter API")
        print(" [4] SPUSTIT PŘEKLAD - přeložit další dávku pomocí aktivního nastavení")
        print(" [5] VALIDACE - zkontrolovat přeložený text na chyby a glosář")
        print(" [6] OPRAVNÝ BĚH (REPAIR) - automaticky opravit chyby pomocí AI")
        print(" [7] IMPORT - složit přeložené řádky zpět do souborové struktury .msg")
        print(" [8] ZMĚNIT NASTAVENÍ / AI MODELY")
        print(" [9] SPRÁVCE DATABÁZE - reset AI překladů nebo F2 zarovnání")
        print(" [B] BENCHMARK MODELŮ - Otestuje top 5 modelů na těžkých řádcích a porovná je")
        print(" [0] UCONČIT")
        print("-" * 60)
        
        volba = input("Zadejte vaši volbu (0-9, P, B): ").strip().upper()
        
        if volba == "1":
            print("\n>>> Spouštím EXPORT + SYNC...")
            director = ROOT / "05_scripts" / "pipeline_director.py"
            subprocess.run([sys.executable, str(director), "--steps", "export,sync"], check=False)
            input("\nStiskněte Enter pro pokračování...")

        elif volba == "P":
            print("\n>>> Spouštím PŘÍPRAVU (sync + F2 + tagy)...")
            director = ROOT / "05_scripts" / "pipeline_director.py"
            subprocess.run([sys.executable, str(director), "--prepare"], check=False)
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "1.5":
            print("\n>>> Spouštím PÁROVÁNÍ S FALLOUT 2 (Alignment)...")
            # Tímto spustíme oddělený skript pro zarovnání
            align_script = ROOT / "05_scripts" / "align_classic_translations.py"
            if align_script.exists():
                try:
                    subprocess.run([sys.executable, str(align_script)], check=False)
                except Exception as e:
                    print(f"Chyba při spuštění zarovnávání: {e}")
            else:
                print(f"Chyba: Skript {align_script} nebyl nalezen.")
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "2":
            print("\n>>> Spouštím zkušební překlad (10 řádků) přes lokální Ollamu...")
            run_command([
                "translate",
                "--input", cfg["translated_file"],
                "--out", cfg["translated_file"],
                "--glossary", cfg["glossary_dir"],
                "--provider", "ollama",
                "--model", cfg["ollama_model"],
                "--host", cfg["ollama_host"],
                "--limit", "10",
                "--batch-size", "10"
            ])
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "3":
            print("\n>>> Spouštím zkušební překlad (10 řádků) přes OpenRouter...")
            run_command([
                "translate",
                "--input", cfg["translated_file"],
                "--out", cfg["translated_file"],
                "--glossary", cfg["glossary_dir"],
                "--provider", "openrouter",
                "--model", cfg["openrouter_model"],
                "--limit", "10",
                "--batch-size", "10"
            ])
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "4":
            limit = input("Zadejte maximální počet řádků k překladu (ponechte prázdné pro 50, zadejte 0 pro vše): ").strip()
            if not limit:
                limit_val = "50"
            elif limit == "0":
                limit_val = "999999" # Velké číslo zastupující "vše"
            else:
                limit_val = limit
                
            batch_sz = input("Velikost dávky (batch size, doporučeno 10): ").strip()
            batch_sz = batch_sz if batch_sz else "10"
            
            cat_input = input("Zadejte kategorii k překladu (viz file_categories.py: např. game_combat, game_character_screen; dialog_npc; prázdné=vše): ").strip()
            
            print(f"\n>>> Spouštím překlad s providerem {cfg['provider'].upper()} (limit: {limit_val} řádků, batch: {batch_sz})...")
            
            args = [
                "translate",
                "--input", cfg["translated_file"],
                "--out", cfg["translated_file"],
                "--glossary", cfg["glossary_dir"],
                "--provider", cfg["provider"],
                "--limit", limit_val,
                "--batch-size", batch_sz
            ]
            
            if cat_input:
                args += ["--category", cat_input]
            
            if cfg["provider"] == "ollama":
                args += ["--model", cfg["ollama_model"], "--host", cfg["ollama_host"]]
            else:
                args += ["--model", cfg["openrouter_model"]]
                
            run_command(args)
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "5":
            print("\n>>> Spouštím VALIDACI (director)...")
            director = ROOT / "05_scripts" / "pipeline_director.py"
            subprocess.run([sys.executable, str(director), "--steps", "validate"], check=False)
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "6":
            print("\n>>> Spouštím QA OPRAVU (director --fix)...")
            print("Řetězec: tagy → validace → repair → re-validace")
            limit = input("Limit řádků k opravě (ponechte prázdné pro vše): ").strip()
            limit_val = limit if limit else "0"
            director = ROOT / "05_scripts" / "pipeline_director.py"
            subprocess.run([
                sys.executable, str(director), "--fix",
                "--limit", limit_val,
            ], check=False)
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "7":
            print("\n>>> Spouštím IMPORT přeložených textů zpět do souborů .msg...")
            run_command([
                "import",
                "--source-root", cfg["en_root"],
                "--translated", cfg["translated_file"],
                "--out-root", cfg["output_root"]
            ])
            print(f"\nHotovo! Výsledné české soubory .msg byly uloženy do: {cfg['output_root']}")
            print("Tyto soubory můžete zkopírovat do vaší testovací instalace Fallout Sonora.")
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "8":
            change_settings(cfg)
            
        elif volba == "9":
            trans_path = ROOT / cfg["translated_file"]
            if not trans_path.exists():
                print("Chyba: Soubor s překlady neexistuje.")
            else:
                print("\nVyberte, co chcete smazat:")
                print("1. Jenom AI překlady (vymaže chyby po Ollamě/OpenRouteru)")
                print("2. Pouze pochybná zarovnání z F2 (Tier 2 a Tier 3)")
                sub = input("Volba (1/2): ").strip()
                
                rows = []
                deleted = 0
                if sub == "1":
                    potvrzeni = input("Smazat AI překlady? (a/n): ").strip().lower()
                    if potvrzeni in ["a", "ano", "y", "yes"]:
                        with trans_path.open("r", encoding="utf-8") as f:
                            for line in f:
                                if line.strip():
                                    r = json.loads(line)
                                    if r.get("status") in ["translated", "issue"]:
                                        r["cs"] = ""
                                        r["status"] = "new"
                                        r["notes"] = ""
                                        deleted += 1
                                    rows.append(r)
                elif sub == "2":
                    potvrzeni = input("Smazat pochybná F2 zarovnání (Tier 2 a 3)? (a/n): ").strip().lower()
                    if potvrzeni in ["a", "ano", "y", "yes"]:
                        with trans_path.open("r", encoding="utf-8") as f:
                            for line in f:
                                if line.strip():
                                    r = json.loads(line)
                                    # Tier 1 je aligned_confirmed, Tier 2/3 je aligned_review
                                    if r.get("status") == "aligned_review":
                                        r["cs"] = ""
                                        r["status"] = "new"
                                        r["notes"] = ""
                                        deleted += 1
                                    rows.append(r)
                else:
                    print("Operace zrušena.")
                
                if deleted > 0:
                    print("Promazávám databázi...")
                    with trans_path.open("w", encoding="utf-8", newline="\n") as f:
                        for r in rows:
                            f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    print(f"Hotovo! Uvedeno {deleted} řádků zpět do stavu 'new'.")
                
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "B":
            print("\n>>> Spouštím BENCHMARK AI MODELŮ...")
            bench_script = ROOT / "05_scripts" / "benchmark" / "run_benchmark.py"
            if bench_script.exists():
                try:
                    subprocess.run([sys.executable, str(bench_script)], check=False)
                    report_file = ROOT / "06_output" / "benchmark_report.md"
                    if report_file.exists():
                        print(f"\nSkvělé! Report z benchmarku byl uložen do: {report_file}")
                        print("Podívejte se do něj, abyste zjistili, který model si vedl nejlépe.")
                except Exception as e:
                    print(f"Chyba při spuštění benchmarku: {e}")
            else:
                print(f"Chyba: Skript {bench_script} nebyl nalezen.")
            input("\nStiskněte Enter pro pokračování...")
            
        elif volba == "0":
            print("\nDěkujeme za použití Sonora CZ AI Toolkitu! Hodně štěstí s překladem.")
            sys.exit(0)
            
        else:
            print("\nNeplatná volba. Zadejte prosím číslo od 0 do 9 nebo B.")
            input("\nStiskněte Enter...")

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nSpouštěč ukončen uživatelem.")
        sys.exit(0)
