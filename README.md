# Sonora CZ AI Toolkit - startovni verze

Cil:
- Bezpecne vytahnout Fallout/Sonora `.msg` texty.
- Prekladat pouze textove pole, ne ID a ne strukturu souboru.
- Pouzit Ollama/DeepSeek jako lokalniho prekladatele nebo kontrolora.
- Vratit preklad zpet do `.msg` bez rozbiti formatu.

Zakladni pravidlo:
NIKDY neprekladej primo originalni soubory. Vzdy pracuj s kopii.

Doporucena cesta na Windows:
C:\AI_TRANSLATE_SONORA\

Doporucena struktura je soucasti tohoto balicku.

## 1. Instalace Python balicku

```powershell
cd C:\AI_TRANSLATE_SONORA
py -m pip install -r requirements.txt
```

## 2. Kontrola Ollamy

```powershell
ollama list
ollama run deepseek-r1:8b
```

Ollama API musi bezet na:
http://localhost:11434

## 3. Export Sonora textu

Priklad:

```powershell
py .\05_scripts\sonora_msg_pipeline.py export `
  --en-root ".\01_sources\sonora_en" `
  --ru-root ".\01_sources\sonora_ru" `
  --out ".\02_work\export\sonora_export.jsonl"
```

## 4. Preklad maleho testu

```powershell
py .\05_scripts\sonora_msg_pipeline.py translate `
  --input ".\02_work\export\sonora_export.jsonl" `
  --out ".\02_work\translated\sonora_translated_test.jsonl" `
  --glossary ".\03_glossary\base_terms.tsv" `
  --limit 20 `
  --model "deepseek-r1:8b"
```

## 5. Validace

```powershell
py .\05_scripts\sonora_msg_pipeline.py validate `
  --input ".\02_work\translated\sonora_translated_test.jsonl"
```

## 6. Import zpet do .msg

```powershell
py .\05_scripts\sonora_msg_pipeline.py import `
  --source-root ".\01_sources\sonora_en" `
  --translated ".\02_work\translated\sonora_translated_test.jsonl" `
  --out-root ".\06_output\czech_text"
```

## 7. Co potom?

Vysledek z `06_output/czech_text` musis rucne vlozit do testovaci kopie hry podle jeji jazykove struktury.
Nejprve testuj jeden maly dialogovy soubor. Ne celou hru.

## Bezpecnost

- Nevydavej ven puvodni soubory Falloutu, Falloutu 2, Nevady ani Sonory, pokud k tomu nemas prava.
- Tento toolkit je jen technicka pomucka pro praci s lokalnimi kopiemi textu.
