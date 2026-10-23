import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAT2_PATH = ROOT / "tools" / "dat2.exe"
ORIGINALS_DIR = ROOT / "00_originals"
REFERENCE_DIR = ROOT / "04_reference"

GAME_FOLDERS = [
    "fallout1_cz",
    "fallout1_en",
    "fallout2_cz",
    "fallout2_en",
    "nevada_cz",
    "nevada_en",
]

def extract_msg_from_dat(dat_path: Path, target_dir: Path):
    print(f"Skenuji soubory v: {dat_path.name}")
    
    # 1. Získání seznamu souborů v DAT archivu
    try:
        result = subprocess.run(
            [str(DAT2_PATH), "l", str(dat_path)],
            capture_output=True,
            text=True,
            encoding="latin-1", # dat2 výstup může obsahovat nestandardní znaky
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Chyba při listování DAT archivu {dat_path.name}: {e}")
        return

    # 2. Filtrace pouze .msg souborů
    msg_files = []
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 4:
            file_path = parts[-1]
            if file_path.lower().endswith(".msg"):
                msg_files.append(file_path)

    if not msg_files:
        print(f"V {dat_path.name} nebyly nalezeny žádné .msg soubory.")
        return

    print(f"Nalezeno {len(msg_files)} .msg souborů k extrakci z {dat_path.name}")

    # 3. Zápis seznamu do dočasného souboru (response_file pro dat2)
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as temp_file:
        for f in msg_files:
            temp_file.write(f + "\n")
        temp_path = Path(temp_file.name)

    # 4. Extrakce vybraných souborů
    # Použijeme -d pro určení výstupní složky, ale musíme běžet v adresáři DAT souboru
    try:
        print(f"Extrahuji vybrané soubory do {target_dir.relative_to(ROOT)}...")
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Spočítáme relativní cestu z adresáře DAT souboru do cílového adresáře
        dat_dir = dat_path.parent
        rel_target = os.path.relpath(target_dir, dat_dir)
        
        # Spustíme extrakci s @response_file v patřičném adresáři
        subprocess.run(
            [str(DAT2_PATH), "x", "-d", rel_target, dat_path.name, f"@{temp_path}"],
            cwd=str(dat_dir),
            check=True,
            stdout=subprocess.DEVNULL # potlačíme tisíce řádků výpisu extrakce
        )
        print(f"Extrakce z {dat_path.name} dokončena úspěšně.")
    except subprocess.CalledProcessError as e:
        print(f"Chyba při extrakci z {dat_path.name}: {e}")
    finally:
        # Smazání dočasného souboru
        if temp_path.exists():
            temp_path.unlink()

def main():
    if not DAT2_PATH.exists():
        print(f"Chyba: dat2.exe nebyl nalezen na: {DAT2_PATH}")
        return

    print("=== START EXTRAKCE REFERENČNÍCH TEXTŮ ===")
    
    for folder in GAME_FOLDERS:
        src_folder = ORIGINALS_DIR / folder
        dest_folder = REFERENCE_DIR / folder
        
        if not src_folder.exists():
            print(f"Složka s originálem {folder} neexistuje, přeskakuji.")
            continue

        print(f"\nProhledávám složku: {folder}")
        
        # Najdeme všechny .dat (i .DAT) soubory v této složce
        dat_files = list(src_folder.glob("*.dat")) + list(src_folder.glob("*.DAT"))
        
        # Odfiltrujeme případné duplicity
        dat_files = sorted(list(set(dat_files)))
        
        if not dat_files:
            print(f"Ve složce {folder} nebyly nalezeny žádné .dat soubory.")
            continue

        for dat_file in dat_files:
            extract_msg_from_dat(dat_file, dest_folder)

    print("\n=== EXTRAKCE DOKONČENA ===")

if __name__ == "__main__":
    main()
