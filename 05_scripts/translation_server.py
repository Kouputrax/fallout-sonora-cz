#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
translation_server.py

Lokální odlehčený REST server pro správu překladu Fallout: Sonora CZ.
Napsáno v čistém Pythonu bez externích závislostí (využívá http.server).
Spouští se na portu 8000.
"""

import os
import sys
import re
import json
import time
import threading
import subprocess
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

# Přidání cesty k 05_scripts
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "05_scripts"))

from file_categories import get_file_category, dialog_area_codes_from_paths
from context_tags import enrich_row_context

try:
    import sonora_msg_pipeline
except ImportError:
    # Pro případ, že by se import nezdařil přímo
    import sys
    sys.path.append(str(Path(__file__).resolve().parent))
    import sonora_msg_pipeline

# Globální proměnné pro stav pipeline procesu na pozadí
pipeline_proc = None
pipeline_logs = []
pipeline_action = ""
pipeline_lock = threading.Lock()

def load_jsonl(path):
    rows = []
    if not path.exists(): return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def save_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# --- GLOBALS ---
GLOSSARY_TERMS = []
def load_glossary_for_server():
    global GLOSSARY_TERMS
    try:
        import csv
        for f_name in ["protected_terms.tsv", "base_terms.tsv"]:
            p = ROOT / "03_glossary" / f_name
            if p.exists():
                content = p.read_text(encoding="utf-8", errors="replace")
                reader = csv.DictReader(content.splitlines(), delimiter="\t")
                for row in reader:
                    if not row: continue
                    en = (row.get("source_en") or row.get("english_cue") or row.get("source") or "").strip()
                    cz = (row.get("target_cs") or row.get("neutral_cz") or row.get("target") or "").strip()
                    if en and cz:
                        if en.lower() in ("source_en", "english_cue", "source") and cz.lower() in ("target_cs", "neutral_cz", "target"):
                            continue
                        GLOSSARY_TERMS.append((en, cz))
    except Exception as e:
        print("Chyba nacitani glosare pro server:", e)

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
                
    # Negation check (neplatí pro „for no damage“ / „no damage“)
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


class TranslationCache:
    def __init__(self, filepath):
        self.filepath = Path(filepath)
        self.lock = threading.Lock()
        self.rows = []
        self.mtime = 0
        self.files = []
        self.locations = []

        self.total_count = 0
        self.translated_count = 0
        self.issue_count = 0
        
        self.reload_if_needed()

    def reload_if_needed(self):
        with self.lock:
            if not self.filepath.exists():
                self.rows = []
                self.mtime = 0
                self.files = []
                self.locations = []
                self.total_count = 0
                self.translated_count = 0
                self.issue_count = 0
                return
            
            current_mtime = self.filepath.stat().st_mtime
            if current_mtime > self.mtime:
                print(f"Načítám soubor překladů {self.filepath}...")
                rows = []
                unique_files = set()
                translated = 0
                issues = 0
                
                with self.filepath.open("r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            r = json.loads(line)
                            rows.append(r)
                            if r.get("file"):
                                unique_files.add(r["file"])
                            
                            cs = r.get("cs", "") or ""
                            if cs.strip():
                                translated += 1
                                if check_row_issues(r.get("en", ""), cs):
                                    issues += 1
                
                # Seskupení pro kategorizaci souborů
                by_file = {}
                for r in rows:
                    f_name = r.get("file", "")
                    if f_name not in by_file:
                        by_file[f_name] = []
                    by_file[f_name].append(r)

                file_categories = {}
                for f_name, f_rows in by_file.items():
                    file_categories[f_name] = get_file_category(f_name, f_rows)

                for r in rows:
                    r["file_category"] = file_categories.get(r.get("file", ""), "dialog_scenery")
                    ctx = enrich_row_context(r)
                    r["context_tags"] = ctx["tags"]
                    r["hint_cs"] = ctx["hint_cs"]

                self.locations = dialog_area_codes_from_paths(unique_files)

                self.rows = rows
                self.files = sorted(list(unique_files))
                self.total_count = len(rows)
                self.translated_count = translated
                self.issue_count = issues
                self.mtime = current_mtime
                print(f"Úspěšně načteno {self.total_count} řádků. Přeloženo: {self.translated_count}, QA chyb: {self.issue_count}.")

    def force_reload(self):
        """Vynutí znovunačtení dat z disku (resetuje mtime)."""
        self.mtime = 0
        self.reload_if_needed()

    def get_status(self):
        self.reload_if_needed()
        with self.lock:
            return {
                "total": self.total_count,
                "translated": self.translated_count,
                "untranslated": self.total_count - self.translated_count,
                "issues": self.issue_count,
                "files_count": len(self.files)
            }

    def get_files(self):
        self.reload_if_needed()
        with self.lock:
            return self.files

    def get_locations(self):
        self.reload_if_needed()
        with self.lock:
            return self.locations

    def query_rows(self, page=1, limit=50, status="all", search_query="", file_filter="", category_filter="", location_filter=""):
        self.reload_if_needed()
        with self.lock:
            filtered = []
            loc_f = (location_filter or "").strip().upper()

            for r in self.rows:
                # Filtr oblasti (prefix názvu souboru dialogu — např. AC)
                if loc_f:
                    fn = r.get("file") or ""
                    if not fn.replace("\\", "/").lower().startswith("dialog/"):
                        continue
                    bname = os.path.basename(fn)
                    if len(bname) < 2 or bname[:2].upper() != loc_f:
                        continue

                # 0. Filtr kategorie (game vs dialog vs dialog_npc vs dialog_scenery nebo konkrétní game_*)
                if category_filter:
                    row_cat = r.get("file_category", "dialog_scenery")
                    if category_filter == "game":
                        if not row_cat.startswith("game"):
                            continue
                    elif category_filter == "dialog":
                        if row_cat not in ("dialog_npc", "dialog_scenery"):
                            continue
                    elif category_filter in ("dialog_npc", "dialog_scenery"):
                        if row_cat != category_filter:
                            continue
                    else:
                        # Pro specifické podkategorie typu game_combat atd.
                        if row_cat != category_filter:
                            continue

                # 1. Filtr souboru
                if file_filter and r.get("file") != file_filter:
                    continue
                
                cs = r.get("cs", "") or ""
                
                # 2. Filtr stavu
                row_status = r.get("status", "new")
                if status == "untranslated":
                    if cs.strip():
                        continue
                elif status == "translated":
                    # Jen řádky s CS textem bez stavu převzetí z Fallout 2 aligneru
                    if not cs.strip():
                        continue
                    if row_status in ("aligned_confirmed", "aligned_review"):
                        continue
                elif status in ("aligned_confirmed", "aligned_review"):
                    if row_status != status:
                        continue
                elif status == "tier2":
                    if row_status != "aligned_review" or "Tier 2" not in r.get("notes", ""):
                        continue
                elif status == "tier3":
                    if row_status != "aligned_review" or "Tier 3" not in r.get("notes", ""):
                        continue
                elif status == "issue":
                    if not cs.strip():
                        continue
                    if not check_row_issues(r.get("en", ""), cs):
                        continue
                
                # 3. Filtr hledání
                if search_query:
                    sq = search_query.lower()
                    if (sq not in r.get("en", "").lower() and 
                        sq not in r.get("ru", "").lower() and 
                        sq not in r.get("cs", "").lower() and 
                        sq not in r.get("id", "").lower()):
                        continue
                
                # Obohatit o live QA issues pro frontend
                row_copy = r.copy()
                row_copy["live_issues"] = check_row_issues(r.get("en", ""), cs)
                filtered.append(row_copy)
            
            total_filtered = len(filtered)
            start = (page - 1) * limit
            end = start + limit
            sliced = filtered[start:end]
            
            pages = (total_filtered + limit - 1) // limit if limit > 0 else 1
            
            return {
                "rows": sliced,
                "total_filtered": total_filtered,
                "page": page,
                "pages": pages
            }

    def get_dialog_context(self, file_name, line_no, context_window=4):
        self.reload_if_needed()
        with self.lock:
            file_rows = [r for r in self.rows if r.get("file") == file_name]
            file_rows.sort(key=lambda r: r.get("line_no", 0))
            
            target_idx = -1
            for idx, r in enumerate(file_rows):
                if r.get("line_no") == line_no:
                    target_idx = idx
                    break
            
            if target_idx == -1:
                return []
                
            start_idx = max(0, target_idx - context_window)
            end_idx = min(len(file_rows), target_idx + context_window + 1)
            
            context_rows = []
            for r in file_rows[start_idx:end_idx]:
                row_copy = r.copy()
                row_copy["live_issues"] = check_row_issues(r.get("en", ""), r.get("cs", "") or "")
                context_rows.append(row_copy)
                
            return context_rows

    def save_row(self, file_name, line_no, id_val, cs_text):
        self.reload_if_needed()
        with self.lock:
            found = False
            for r in self.rows:
                if r.get("file") == file_name and r.get("line_no") == line_no and r.get("id") == id_val:
                    r["cs"] = cs_text
                    r["status"] = "translated"
                    r["warnings"] = []
                    r["notes"] = ""
                    found = True
                    break
            
            if found:
                # Zápis zpět do JSONL souboru
                temp_file = self.filepath.with_suffix(".jsonl.tmp")
                with temp_file.open("w", encoding="utf-8", newline="\n") as f:
                    for r in self.rows:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                
                if temp_file.exists():
                    if self.filepath.exists():
                        self.filepath.unlink()
                    temp_file.rename(self.filepath)
                
                # Přepočet statistik na základě změny
                translated = 0
                issues = 0
                for r in self.rows:
                    cs = r.get("cs", "") or ""
                    if cs.strip():
                        translated += 1
                        if check_row_issues(r.get("en", ""), cs):
                            issues += 1
                self.translated_count = translated
                self.issue_count = issues
                self.mtime = self.filepath.stat().st_mtime
                return True
            return False


# Načtení základní konfigurace
def load_config():
    cfg_path = ROOT / "05_scripts" / "pipeline_config.json"
    default_config = {
        "provider": "ollama",
        "ollama_host": "http://localhost:11434",
        "ollama_model": "qwen3:8b",
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
    if cfg_path.exists():
        try:
            with cfg_path.open("r", encoding="utf-8") as f:
                cfg = json.load(f)
                for k, v in default_config.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except Exception:
            pass
    return default_config


def save_config(cfg):
    cfg_path = ROOT / "05_scripts" / "pipeline_config.json"
    try:
        with cfg_path.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Chyba při zápisu konfigurace: {e}")
        return False


def load_env_api_key():
    env_path = ROOT / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k.strip() == "OPENROUTER_API_KEY":
                        return v.strip().strip("'\"")
        except Exception:
            pass
    return os.environ.get("OPENROUTER_API_KEY", "")


def save_env_api_key(key):
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
        os.environ["OPENROUTER_API_KEY"] = key
        return True
    except Exception as e:
        print(f"Chyba při zápisu do .env: {e}")
        return False


# Inicializace cache překladů
config = load_config()
translated_filepath = ROOT / config["translated_file"]
translation_cache = TranslationCache(translated_filepath)


# Spouštění procesů na pozadí
def run_pipeline_subprocess(cmd_args, action_name):
    global pipeline_proc, pipeline_logs, pipeline_action
    with pipeline_lock:
        if pipeline_proc is not None:
            return False # Již běží jiná akce
        pipeline_action = action_name
        pipeline_logs = [f"=== SPUŠTĚNÍ AKCE: {action_name.upper()} ===\n", f"Příkaz: {' '.join(cmd_args)}\n\n"]
        
    def worker():
        global pipeline_proc, pipeline_logs
        try:
            # Nastavíme kódování výstupu na UTF-8
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            
            # Předat API klíč do prostředí z .env
            api_key = load_env_api_key()
            if api_key:
                env["OPENROUTER_API_KEY"] = api_key
            
            proc = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                cwd=str(ROOT)
            )
            
            with pipeline_lock:
                pipeline_proc = proc
                
            for line in proc.stdout:
                with pipeline_lock:
                    pipeline_logs.append(line)
                    if len(pipeline_logs) > 5000:
                        pipeline_logs.pop(0)
                        
            proc.wait()
            with pipeline_lock:
                pipeline_logs.append(f"\n=== AKCE DOKONČENA s kódem: {proc.returncode} ===\n")
        except Exception as e:
            with pipeline_lock:
                pipeline_logs.append(f"\nCHYBA PŘI BĚHU PROCESU: {e}\n")
        finally:
            with pipeline_lock:
                pipeline_proc = None
                
    threading.Thread(target=worker, daemon=True).start()
    return True


class TranslationRequestHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        # Přidání CORS hlaviček pro pohodlí při vývoji
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        # REST API Endpoints
        if path == "/api/status":
            self.handle_api_status()
        elif path == "/api/rows":
            self.handle_api_rows(query)
        elif path == "/api/files":
            self.handle_api_files()
        elif path == "/api/config":
            self.handle_api_get_config()
        elif path == "/api/glossary":
            self.handle_api_glossary()
        elif path == "/api/pipeline_status":
            self.handle_api_pipeline_status()
        elif path == "/api/pipeline_steps":
            self.handle_api_pipeline_steps()
        elif path == "/api/benchmark_results":
            self.handle_api_benchmark_results()
        elif path == "/api/dialog_context":
            self.handle_api_dialog_context(query)
        # Statické soubory
        else:
            self.handle_static_files(path)

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # Získání těla požadavku
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        
        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            self.send_json_response({"error": "Neplatný JSON formát těla požadavku"}, 400)
            return

        if path == "/api/save":
            self.handle_api_save(body)
        elif path == "/api/translate_row":
            self.handle_api_translate_row(body)
        elif path == "/api/config":
            self.handle_api_save_config(body)
        elif path == "/api/pipeline_run":
            self.handle_api_pipeline_run(body)
        elif path == "/api/row_flag":
            self.handle_api_row_flag(body)
        elif path == "/api/pipeline_kill":
            self.handle_api_pipeline_kill()
        elif path == "/api/reload":
            self.handle_api_reload()
        else:
            self.send_json_response({"error": "Neznámý API endpoint"}, 404)

    def send_json_response(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def handle_static_files(self, path):
        # Vyčistit cestu a zajistit bezpečné servírování z 05_scripts/gui
        gui_root = ROOT / "05_scripts" / "gui"
        
        if path == "/" or path == "":
            file_path = gui_root / "index.html"
        else:
            # Odstranění úvodního lomítka a ochrana proti directory traversal
            clean_path = path.lstrip("/")
            file_path = (gui_root / clean_path).resolve()
            if not str(file_path).startswith(str(gui_root.resolve())):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"403 Forbidden")
                return

        if file_path.exists() and file_path.is_file():
            self.send_response(200)
            
            # Detekce Content-Type
            if file_path.suffix == ".html":
                self.send_header("Content-Type", "text/html; charset=utf-8")
            elif file_path.suffix == ".css":
                self.send_header("Content-Type", "text/css; charset=utf-8")
            elif file_path.suffix == ".js":
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
            elif file_path.suffix == ".json":
                self.send_header("Content-Type", "application/json; charset=utf-8")
            elif file_path.suffix in [".png", ".jpg", ".jpeg", ".gif"]:
                self.send_header("Content-Type", f"image/{file_path.suffix[1:]}")
            else:
                self.send_header("Content-Type", "application/octet-stream")
                
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
        else:
            # Pokud soubor neexistuje, vrátíme index.html (pro SPA routing, pokud by byl potřeba)
            alt_index = gui_root / "index.html"
            if alt_index.exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(alt_index.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"404 Not Found")

    # REST API Handler implementace
    def handle_api_status(self):
        stats = translation_cache.get_status()
        cfg = load_config()
        key = load_env_api_key()
        
        stats["provider"] = cfg.get("provider", "ollama")
        stats["ollama_model"] = cfg.get("ollama_model", "")
        stats["openrouter_model"] = cfg.get("openrouter_model", "")
        stats["has_openrouter_key"] = bool(key)
        
        self.send_json_response(stats)

    def handle_api_rows(self, query):
        try:
            page = int(query.get("page", [1])[0])
            limit = int(query.get("limit", [50])[0])
            status = query.get("status", ["all"])[0]
            search = query.get("search", [""])[0]
            file_filter = query.get("file", [""])[0]
            category = query.get("category", [""])[0]
            location = query.get("location", [""])[0]
        except ValueError:
            self.send_json_response({"error": "Neplatné query parametry"}, 400)
            return

        res = translation_cache.query_rows(page, limit, status, search, file_filter, category, location)
        self.send_json_response(res)

    def handle_api_dialog_context(self, query):
        file_name = query.get("file", [""])[0]
        try:
            line_no = int(query.get("line_no", [0])[0])
            context_window = int(query.get("window", [4])[0])
        except (ValueError, TypeError):
            self.send_json_response({"error": "Neplatné query parametry pro kontext (line_no nebo window)"}, 400)
            return

        if not file_name or line_no <= 0:
            self.send_json_response({"error": "Chybí povinné query parametry 'file' a 'line_no'"}, 400)
            return

        res = translation_cache.get_dialog_context(file_name, line_no, context_window)
        self.send_json_response({"context": res})

    def handle_api_files(self):
        files = translation_cache.get_files()
        locations = translation_cache.get_locations()
        self.send_json_response({"files": files, "locations": locations})

    def handle_api_get_config(self):
        cfg = load_config()
        key = load_env_api_key()
        cfg["openrouter_api_key_masked"] = (key[:6] + "..." + key[-4:]) if len(key) > 10 else ""
        cfg["has_openrouter_key"] = bool(key)
        self.send_json_response(cfg)

    def handle_api_row_flag(self, body):
        file_path = body.get("file")
        row_id = body.get("id")
        flagged = body.get("flagged", False)
        
        if not file_path or not row_id:
            self.send_json_response({"error": "Chybí file nebo id"}, 400)
            return
            
        translation_cache.reload_if_needed()
        success = False
        with translation_cache.lock:
            for r in translation_cache.rows:
                if r.get("file") == file_path and str(r.get("id")) == str(row_id):
                    r["flagged"] = flagged
                    success = True
                    break
                    
            if success:
                # Atomický zápis přes tmp soubor
                temp_file = translation_cache.filepath.with_suffix(".jsonl.tmp")
                with temp_file.open("w", encoding="utf-8", newline="\n") as f:
                    for r in translation_cache.rows:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                if temp_file.exists():
                    if translation_cache.filepath.exists():
                        translation_cache.filepath.unlink()
                    temp_file.rename(translation_cache.filepath)
                translation_cache.mtime = translation_cache.filepath.stat().st_mtime
        
        if success:
            self.send_json_response({"status": "ok"})
        else:
            self.send_json_response({"error": "Řádek nebyl nalezen"}, 404)

    def handle_api_save_config(self, body):
        cfg = load_config()
        
        # Aktualizujeme parametry z body
        for k in ["provider", "ollama_host", "ollama_model", "openrouter_model", "openrouter_repair_model"]:
            if k in body:
                cfg[k] = body[k]
                
        save_success = save_config(cfg)
        
        # API klíč se ukládá samostatně do .env
        key_success = True
        if "openrouter_api_key" in body and body["openrouter_api_key"]:
            key = body["openrouter_api_key"]
            if key != "KEEP_EXISTING":
                key_success = save_env_api_key(key)
                
        if save_success and key_success:
            self.send_json_response({"success": True, "message": "Konfigurace byla úspěšně uložena."})
        else:
            self.send_json_response({"error": "Nepodařilo se uložit konfiguraci nebo API klíč."}, 500)

    def handle_api_glossary(self):
        try:
            # Načtení glosářů pomocí metod z sonora_msg_pipeline s podporou multi-origin
            all_terms = sonora_msg_pipeline.load_all_glossaries_extended(str(ROOT / config["glossary_dir"]))
            self.send_json_response({"glossary": all_terms})
        except Exception as e:
            self.send_json_response({"error": f"Nepodařilo se načíst glosáře: {e}"}, 500)

    def handle_api_save(self, body):
        file_name = body.get("file")
        line_no = body.get("line_no")
        id_val = body.get("id")
        cs_text = body.get("cs")

        if not all([file_name, line_no is not None, id_val is not None, cs_text is not None]):
            self.send_json_response({"error": "Chybí povinná pole v požadavku (file, line_no, id, cs)"}, 400)
            return

        success = translation_cache.save_row(file_name, int(line_no), str(id_val), cs_text)
        if success:
            self.send_json_response({"success": True, "message": "Řádek byl úspěšně uložen."})
        else:
            self.send_json_response({"error": "Řádek nebyl nalezen v databázi překladů."}, 404)

    def handle_api_translate_row(self, body):
        file_name = body.get("file")
        line_no = body.get("line_no")
        id_val = body.get("id")

        if not all([file_name, line_no is not None, id_val is not None]):
            self.send_json_response({"error": "Chybí povinné identifikátory řádku"}, 400)
            return

        # Vyhledání řádku v načtených datech
        rows = translation_cache.rows
        target_row = None
        for r in rows:
            if r.get("file") == file_name and r.get("line_no") == int(line_no) and r.get("id") == str(id_val):
                target_row = r.copy() # Make a copy to avoid mutating cache rows with temporary context fields
                break

        if not target_row:
            self.send_json_response({"error": "Řádek nebyl nalezen."}, 404)
            return

        # Získání kontextu rozhovoru (pokud je to soubor dialogů)
        if file_name.startswith("dialog/"):
            target_row["dialogue_context"] = translation_cache.get_dialog_context(file_name, int(line_no), context_window=4)

        try:
            from file_categories import get_file_category
            from context_tags import enrich_row_context
            target_row["file_category"] = get_file_category(
                file_name, target_row.get("en", "")
            )
            ctx = enrich_row_context(target_row)
            target_row["context_tags"] = ctx["tags"]
            target_row["hint_cs"] = ctx["hint_cs"]
            if ctx.get("ru_guide_cs"):
                target_row["ru_guide_cs"] = ctx["ru_guide_cs"]
        except ImportError:
            pass

        # Načtení glosářů a příprava překladu
        cfg = load_config()
        glossary_dir_path = str(ROOT / cfg["glossary_dir"])
        
        try:
            all_terms = sonora_msg_pipeline.load_all_glossaries(glossary_dir_path)
            # Vygenerovat glosář specificky pro tento jeden řádek
            glossary_tsv = sonora_msg_pipeline.get_glossary_for_batch([target_row], all_terms)
            
            provider = cfg.get("provider", "ollama")
            model = cfg.get("ollama_model" if provider == "ollama" else "openrouter_model")
            
            print(f"Spouštím AI překlad řádku přes {provider.upper()} (model: {model})...")
            
            if provider == "ollama":
                host = cfg.get("ollama_host", "http://localhost:11434")
                res = sonora_msg_pipeline.ollama_translate_batch([target_row], model, glossary_tsv, host)
            else:
                api_key = load_env_api_key()
                if not api_key:
                    self.send_json_response({"error": "Chybí OpenRouter API klíč v konfiguraci."}, 400)
                    return
                res = sonora_msg_pipeline.openrouter_translate_batch(
                    batch=[target_row],
                    model=model,
                    glossary=glossary_tsv,
                    api_key=api_key,
                    timeout=60
                )
                
            items = res.get("items", [])
            if not items:
                self.send_json_response({"error": f"Model nevrátil žádný překlad: {res}"}, 500)
                return
                
            cs_translated = items[0].get("cs", "")
            cs_processed = sonora_msg_pipeline.postprocess_cs(cs_translated)
            
            self.send_json_response({
                "success": True, 
                "cs": cs_processed,
                "note": items[0].get("notes", "")
            })
            
        except Exception as e:
            self.send_json_response({"error": f"AI překlad selhal: {str(e)}"}, 500)

    def handle_api_pipeline_run(self, body):
        action = body.get("action")
        if not action:
            self.send_json_response({"error": "Chybí parametr 'action'"}, 400)
            return

        cfg = load_config()
        
        # Sestavení příkazové řádky pro subprocess
        pipeline_script = str(ROOT / "05_scripts" / "sonora_msg_pipeline.py")
        cmd = [sys.executable, pipeline_script]
        
        if action == "export":
            director = str(ROOT / "05_scripts" / "pipeline_director.py")
            cmd = [sys.executable, director, "--steps", "export,sync"]
        elif action == "prepare":
            director = str(ROOT / "05_scripts" / "pipeline_director.py")
            cmd = [sys.executable, director, "--prepare"]
        elif action == "translate":
            limit = str(body.get("limit", 50))
            batch_sz = str(body.get("batch_size", 10))
            provider = cfg["provider"]
            director = str(ROOT / "05_scripts" / "pipeline_director.py")

            if provider == "openrouter":
                api_key = load_env_api_key()
                if not api_key:
                    self.send_json_response({"error": "Chybí OpenRouter API klíč v konfiguraci."}, 400)
                    return
                # Dialogy: blokový překlad s kontextem (segment_blocks + translate_blocks)
                translate_script = str(ROOT / "05_scripts" / "translate_blocks.py")
                cmd = [
                    sys.executable, translate_script,
                    "--api-key", api_key,
                    "--model", cfg.get("openrouter_model", "anthropic/claude-3-haiku"),
                    "--limit", limit,
                ]
            else:
                cmd = [
                    sys.executable, director, "--steps", "translate",
                    "--limit", limit, "--batch-size", batch_sz,
                ]
                
        elif action == "validate":
            director = str(ROOT / "05_scripts" / "pipeline_director.py")
            cmd = [sys.executable, director, "--steps", "validate"]
        elif action == "repair":
            limit = str(body.get("limit", 0))
            batch_sz = str(body.get("batch_size", 10))
            api_key = load_env_api_key()
            if not api_key:
                self.send_json_response({"error": "Chybí OpenRouter API klíč pro opravný běh."}, 400)
                return
            director = str(ROOT / "05_scripts" / "pipeline_director.py")
            cmd = [
                sys.executable, director, "--fix",
                "--limit", limit, "--batch-size", batch_sz,
            ]
                
        elif action == "import":
            director = str(ROOT / "05_scripts" / "pipeline_director.py")
            cmd = [sys.executable, director, "--steps", "import"]
        elif action == "benchmark":
            bench_script = str(ROOT / "05_scripts" / "benchmark" / "run_benchmark.py")
            cmd = [sys.executable, bench_script]
            selected_models = body.get("models", [])
            if selected_models:
                cfg = load_config()
                resolved_models = []
                for m in selected_models:
                    if m == "ollama/default":
                        resolved_models.append(f"ollama/{cfg.get('ollama_model', 'qwen2.5:7b')}")
                    else:
                        resolved_models.append(m)
                cmd.extend(["--models"] + resolved_models)
        elif action == "reset_ai" or action == "reset_f2" or action == "reset_all":
            cfg = load_config()
            trans_path = ROOT / cfg["translated_file"]
            if action == "reset_all":
                director = str(ROOT / "05_scripts" / "pipeline_director.py")
                cmd = [sys.executable, director, "--reset"]
                success = run_pipeline_subprocess(cmd, action)
                if success:
                    self.send_json_response({"success": True, "message": "Plný reset spuštěn (záloha + vynulování DB)."})
                else:
                    self.send_json_response({"error": "Na pozadí již běží jiná akce pipeline."}, 409)
                return
            if not trans_path.exists():
                self.send_json_response({"error": "Databáze překladů neexistuje."}, 404)
                return
            
            rows = load_jsonl(trans_path)
            deleted = 0
            for r in rows:
                status = r.get("status")
                if action == "reset_ai" and status in ["translated", "issue"]:
                    r["cs"] = ""
                    r["status"] = "new"
                    r["notes"] = ""
                    deleted += 1
                elif action == "reset_f2" and status == "aligned_review":
                    r["cs"] = ""
                    r["status"] = "new"
                    r["notes"] = ""
                    deleted += 1
            
            save_jsonl(trans_path, rows)
            self.send_json_response({"success": True, "message": f"Operace dokončena. Vymazáno {deleted} řádků."})
            return
        else:
            self.send_json_response({"error": f"Neznámá akce pipeline: {action}"}, 400)
            return

        success = run_pipeline_subprocess(cmd, action)
        if success:
            self.send_json_response({"success": True, "message": f"Akce '{action}' byla spuštěna na pozadí."})
        else:
            self.send_json_response({"error": "Na pozadí již běží jiná akce pipeline."}, 409)

    def handle_api_pipeline_steps(self):
        try:
            from pipeline_director import STEPS, PREPARE_STEPS, FIX_STEPS
            self.send_json_response({
                "steps": [{"id": k, "label": d} for k, d in STEPS],
                "prepare": PREPARE_STEPS,
                "fix": FIX_STEPS,
                "recommended_order": [k for k, _ in STEPS],
            })
        except ImportError:
            self.send_json_response({
                "steps": [],
                "prepare": ["sync", "align", "enrich"],
                "fix": ["enrich", "validate", "repair", "validate"],
                "recommended_order": [],
            })

    def handle_api_pipeline_status(self):
        global pipeline_proc, pipeline_logs, pipeline_action
        with pipeline_lock:
            running = pipeline_proc is not None
            logs_str = "".join(pipeline_logs)
            action_name = pipeline_action
            
        self.send_json_response({
            "is_running": running,
            "action": action_name,
            "logs": logs_str
        })

    def handle_api_pipeline_kill(self):
        global pipeline_proc
        with pipeline_lock:
            if pipeline_proc is not None:
                try:
                    pipeline_proc.kill()
                    pipeline_logs.append("\n=== PROCES BYL UŽIVATELEM PŘERUŠEN ===\n")
                    self.send_json_response({"success": True, "message": "Proces byl úspěšně ukončen."})
                except Exception as e:
                    self.send_json_response({"error": f"Nepodařilo se ukončit proces: {e}"}, 500)
            else:
                self.send_json_response({"error": "Žádný proces zrovna neběží."}, 400)

    def handle_api_reload(self):
        """Vynuti znovunacteni prekladove databaze z disku."""
        translation_cache.force_reload()
        stats = translation_cache.get_status()
        self.send_json_response({"success": True, "message": "Data znovu nactena.", **stats})

    def handle_api_benchmark_results(self):
        bench_dir = ROOT / "02_work" / "benchmark"
        test_set_path = bench_dir / "test_set.jsonl"
        
        if not test_set_path.exists():
            self.send_json_response({"error": "Test set not found"}, 404)
            return
            
        test_rows = load_jsonl(test_set_path)
        
        models_data = {}
        model_names = []
        for f in bench_dir.glob("results_*.jsonl"):
            m_name = f.stem.replace("results_", "")
            model_names.append(m_name)
            m_rows = load_jsonl(f)
            models_data[m_name] = {r.get("en",""): r.get("cs","") for r in m_rows}
            
        results = []
        for tr in test_rows:
            en = tr.get("en","")
            row_data = {"en": en, "outputs": {}}
            for m in model_names:
                row_data["outputs"][m] = models_data[m].get(en, "")
            results.append(row_data)
            
        self.send_json_response({
            "models": model_names,
            "rows": results
        })


def run_server(port=8000):
    server_address = ("", port)
    # Použijeme ThreadingHTTPServer, aby server zvládal dotazy na status, i když zrovna spouští AI překlad řádku
    httpd = ThreadingHTTPServer(server_address, TranslationRequestHandler)
    print(f"==================================================")
    print(f" PŘEKLÁDACÍ SERVER PRO FALLOUT: SONORA CZ BĚŽÍ!")
    print(f" Otevřete v prohlížeči: http://localhost:{port}")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nUkončuji server...")
        httpd.server_close()
        sys.exit(0)


if __name__ == "__main__":
    # Načtení klíče na startu pro ověření env proměnných
    load_env_api_key()
    run_server(8000)

