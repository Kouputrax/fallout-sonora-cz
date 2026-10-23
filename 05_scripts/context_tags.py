# -*- coding: utf-8 -*-
"""
Odvodí kontextové značky (tags) a krátkou českou nápovědu z struktury hry.

Použití: GUI editor, enrich skript, volitelně AI prompt.
"""
from __future__ import annotations

import os
import re
from typing import Any


# COMBAT.msg — sestavené hlášky (ID bloky podle komentářů ve zdrojovém .msg)
_COMBAT_TEMPLATE_BLOCKS = (
    (509, 534, "MUŽ:HRÁČ", "Bojová hláška — mužský hráč (ty). První %s = „Ty“. Ty-forma: Byl jsi zasažen… (ne „byli“)."),
    (559, 584, "ŽENA:HRÁČ", "Bojová hláška — ženský hráč (ty). První %s = „Ty“. Ty-forma: Byla jsi zasažena…"),
    (608, 634, "MUŽ:NPC", "Bojová hláška — mužská postava (on). První %s = jméno cíle. 3. os. muž.: byl zasažen…"),
    (708, 734, "ŽENA:NPC", "Bojová hláška — ženská postava (ona). První %s = jméno cíle. 3. os. žen.: byla zasažena…"),
)

# COMBAT.msg — offset ve bloku combat flag (200/250/300/400 + offset)
_COMBAT_FLAG_HINTS = {
    0: ("STAV:KNOCKED", "Stav: omráčen / knocked out — krátký fragment do bojové hlášky."),
    1: ("STAV:DOWN", "Stav: sražen k zemi — krátký fragment."),
    10: ("STAV:HOŘÍ", "Stav hoření (on fire) — krátce „v plamenech“, ne „v palbě“ (palba = střelba)."),
    8: ("STAV:HIT", "Stav: zasažen — krátký fragment."),
    9: ("STAV:CRIT", "Stav: kritický zásah — krátký fragment."),
    6: ("STAV:BLIND", "Stav: oslepen — krátký fragment."),
}


def _parse_msg_id(row: dict) -> int | None:
    raw = row.get("id", "")
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        return None


def _basename(file_name: str) -> str:
    return os.path.basename((file_name or "").replace("\\", "/")).upper()


def _dialog_location_npc(file_name: str) -> tuple[str, str]:
    base = os.path.basename((file_name or "").replace("\\", "/"))
    stem = base.rsplit(".", 1)[0] if "." in base else base
    loc, npc = "", stem
    if len(stem) >= 3 and stem[0].isupper() and stem[1].isupper() and stem[2].isalpha():
        loc = stem[:2]
        npc = stem[2:] or stem
    return loc, npc


def _ru_gender_tags(ru: str) -> list[str]:
    if not ru:
        return []
    tags = []
    if re.search(r"говорил\b", ru, re.IGNORECASE):
        tags.append("RU:M")
    if re.search(r"говорила\b", ru, re.IGNORECASE):
        tags.append("RU:Ž")
    if re.search(r"\bвидишь\b|\bвидел\b", ru, re.IGNORECASE):
        tags.append("RU:TY")
    if re.search(r"\bвидите\b", ru, re.IGNORECASE):
        tags.append("RU:VY")
    return tags


def _ru_combat_subject_tags(ru: str, en: str) -> tuple[list[str], str]:
    """RU/EN sloveso v bojové šabloně — kdo byl zasažen (hráč vs NPC, rod)."""
    tags: list[str] = []
    hints: list[str] = []
    if re.search(r"\bполучили\b", ru, re.IGNORECASE):
        tags.append("SUBJ:HRÁČ")
        hints.append("RU plur. „получили“ → jde o hráče (ty), ne NPC jménem.")
    elif re.search(r"\bполучила\b", ru, re.IGNORECASE):
        tags.append("SUBJ:ŽENA:NPC")
        hints.append("RU „получила“ → ženská postava (ona), 3. osoba.")
    elif re.search(r"\bполучил\b", ru, re.IGNORECASE):
        tags.append("SUBJ:MUŽ:NPC")
        hints.append("RU „получил“ → mužská postava (on), 3. osoba.")
    if re.search(r"\bwere\b", en):
        tags.append("EN:WERE")
        if "SUBJ:HRÁČ" not in tags:
            hints.append("EN „were“ → šablona pro hráče (You were…), ty-forma v češtině.")
    elif re.search(r"\bwas\b", en):
        tags.append("EN:WAS")
        if not any(t.startswith("SUBJ:") for t in tags):
            hints.append("EN „was“ → šablona pro NPC (%s was…), 3. osoba podle rodu cíle.")
    if re.search(r"без\s+потери\s+здоровья", ru, re.IGNORECASE):
        hints.append("RU «без потери здоровья» = bez poškození / bez ztráty HP.")
    if re.search(r"критический\s+удар", ru, re.IGNORECASE):
        hints.append("RU «критический удар» = kritický zásah.")
    return tags, " ".join(hints)


def ru_combat_guide_cs(row: dict[str, Any], tags: list[str] | None = None) -> str:
    """
    Explicitní česká nápověda odvozená z RU textu u bojových šablon.
    Jde do AI promptu i editoru — pomáhá rozlišit „were“ (hráč) vs „was“ (NPC).
    """
    ru = (row.get("ru") or "").strip()
    en = (row.get("en") or "").strip()
    if not ru or _basename(row.get("file") or "") != "COMBAT.MSG":
        return ""

    tag_set = set(tags or row.get("context_tags") or [])
    parts: list[str] = []
    en_l = en.lower()

    if re.search(r"\bполучили\b", ru, re.IGNORECASE):
        if "MUŽ:HRÁČ" in tag_set:
            parts.append(
                "RU «получили» + ID hráč-muž → ty-forma: „Byl jsi zasažen…“, ne „byli“."
            )
        elif "ŽENA:HRÁČ" in tag_set:
            parts.append(
                "RU «получили» + ID hráč-žena → ty-forma: „Byla jsi zasažena…“."
            )
        else:
            parts.append(
                "RU «получили» (plurál) = hráč (ty), ne jméno NPC — v češtině 2. osoba."
            )
    elif re.search(r"\bполучил\b", ru, re.IGNORECASE):
        parts.append("RU «получил» = mužská postava (on), 3. os.: „byl zasažen…“.")
    elif re.search(r"\bполучила\b", ru, re.IGNORECASE):
        parts.append("RU «получила» = ženská postava (ona), 3. os.: „byla zasažena…“.")

    if re.search(r"без\s+потери\s+здоровья", ru, re.IGNORECASE):
        parts.append("RU «без потери здоровья» → „bez poškození“ (ne konstrukce „ale bez poškození zasažen“).")

    if "for no damage" in en_l:
        if "MUŽ:HRÁČ" in tag_set:
            parts.append("Vzor CS: „%s Byl jsi kriticky, ale bez poškození zasažen. Místo zásahu: %s“")
        elif "ŽENA:HRÁČ" in tag_set:
            parts.append("Vzor CS: „%s Byla jsi kriticky, ale bez zranění zasažena. Místo zásahu: %s“")
        elif "MUŽ:NPC" in tag_set:
            parts.append("Vzor CS: „%s byl kriticky zasažen, ale útok mu nezpůsobil žádné zranění. Místo zásahu: %s“")
        elif "ŽENA:NPC" in tag_set:
            parts.append("Vzor CS: „%s byla kriticky zasažena, ale útok jí nezpůsobil žádné zranění. Místo zásahu: %s“")

    return " ".join(parts)


def _combat_template_block(msg_id: int) -> tuple[list[str], str]:
    for lo, hi, tag, hint in _COMBAT_TEMPLATE_BLOCKS:
        if lo <= msg_id <= hi:
            return [tag, "BOJ:HLÁŠKA"], hint
    return [], ""


def _combat_tags(msg_id: int | None, en: str) -> tuple[list[str], str]:
    tags: list[str] = []
    hints: list[str] = []

    if msg_id is None:
        return tags, ""

    if 100 <= msg_id <= 108:
        tags.append("BOJ:UI")
        hints.append("Obecná bojová hláška rozhraní — stručně, ty-forma u hráče.")
        return tags, " ".join(hints)

    gender_block = None
    if 200 <= msg_id <= 222:
        gender_block = ("MUŽ:HRÁČ", "Fragment stavu — týká mužského hráče (ty).")
    elif 250 <= msg_id <= 272:
        gender_block = ("ŽENA:HRÁČ", "Fragment stavu — týká ženského hráče (ty).")
    elif 300 <= msg_id <= 322:
        gender_block = ("MUŽ:NPC", "Fragment stavu — týká mužské postavy (on).")
    elif 400 <= msg_id <= 422:
        gender_block = ("ŽENA:NPC", "Fragment stavu — týká ženské postavy (ona).")

    if gender_block:
        tags.extend(["BOJ", "FRAG", gender_block[0]])
        hints.append(gender_block[1])
        if 200 <= msg_id <= 222:
            offset = msg_id - 200
        elif 250 <= msg_id <= 272:
            offset = msg_id - 250
        elif 300 <= msg_id <= 322:
            offset = msg_id - 300
        else:
            offset = msg_id - 400
        flag = _COMBAT_FLAG_HINTS.get(offset)
        if flag:
            tags.append(flag[0])
            hints.append(flag[1])
        elif en.strip().lower() == "on fire":
            tags.append("STAV:HOŘÍ")
            hints.append("Stav hoření — „v plamenech“, ne „v palbě“.")
        return tags, " ".join(hints)

    if msg_id >= 1000:
        tags.append("BOJ:CÍL")
        hints.append("Název zasažené části těla — krátký popis lokace zásahu.")
        return tags, " ".join(hints)

    block_tags, block_hint = _combat_template_block(msg_id)
    if block_tags:
        tags.extend(block_tags)
        if block_hint:
            hints.append(block_hint)
        hints.append("Druhé %s = část těla v 1. pádu (hlava, levá ruka…). Ve větě použij „Místo zásahu: %s“, ne „v %s“ / „do %s“.")
        return tags, " ".join(hints)

    if msg_id >= 500:
        tags.append("BOJ:HLÁŠKA")
        hints.append("Sestavená bojová věta se zástupnými symboly %s / %d — zachovej je.")
        return tags, " ".join(hints)

    return tags, ""


def _category_tag(file_category: str) -> str:
    mapping = {
        "dialog_npc": "DIALOG:NPC",
        "dialog_scenery": "DIALOG:POPIS",
        "game_combat": "BOJ",
        "game_menus_gui": "MENU",
        "game_character_screen": "POSTAVA",
        "game_items_gear": "PŘEDMĚT",
        "game_world_proto": "POPIS:SVĚT",
        "game_quests_journal": "ÚKOL",
        "game_perks_traits_skills": "MECH",
        "game_world_travel_map": "MAPA",
        "game_critters": "POTVORA",
        "game_engine_strings": "ENGINE",
    }
    if file_category.startswith("game_"):
        return mapping.get(file_category, "HRA")
    return mapping.get(file_category, "")


def enrich_row_context(row: dict[str, Any]) -> dict[str, Any]:
    """
    Vrací {"tags": [...], "hint_cs": "..."} pro jeden řádek JSONL.
    """
    file_name = row.get("file") or ""
    en = (row.get("en") or "").strip()
    ru = (row.get("ru") or "").strip()
    file_category = row.get("file_category") or ""
    msg_id = _parse_msg_id(row)

    tags: list[str] = []
    hints: list[str] = []

    cat_tag = _category_tag(file_category)
    if cat_tag:
        tags.append(cat_tag)

    norm_path = file_name.replace("\\", "/").lower()
    if norm_path.startswith("dialog/"):
        loc, npc = _dialog_location_npc(file_name)
        if loc:
            tags.append(f"LOK:{loc}")
        if npc:
            tags.append(f"NPC:{npc}")

    if norm_path.startswith("game/") and _basename(file_name) == "COMBAT.MSG":
        ct, ch = _combat_tags(msg_id, en)
        tags.extend(ct)
        if ch:
            hints.append(ch)
        if msg_id is not None and msg_id >= 500:
            rt, rh = _ru_combat_subject_tags(ru, en)
            tags.extend(rt)
            if rh:
                hints.append(rh)

    tags.extend(_ru_gender_tags(ru))

    if en == "-":
        tags.append("NECH:-")
        hints.append("Nechat jen pomlčku „-“, nepřekládat.")

    if re.search(r"%[sd%]", en):
        tags.append("ŠABLONA")
        hints.append("Zachovej zástupné symboly %s, %d, %% beze změny.")

    en_lower = en.lower()
    if re.match(r"^you see\b", en_lower):
        tags.append("POPIS:Vidíš")
        hints.append("Popis pro hráče — začni „Vidíš…“, ty-forma, ne „Vidíte“.")

    if msg_id is not None and msg_id in (100, 101) and norm_path.startswith("dialog/"):
        if "POPIS:Vidíš" not in tags:
            tags.append("POPIS")
        hints.append("Typický popis objektu/NPC (ID 100–101).")

    if msg_id is not None and msg_id >= 200 and norm_path.startswith("dialog/"):
        tags.append("DIALOG:REPLIKA")
        hints.append("Replika v konverzaci — sleduj okolní řádky (Dialogue Flow).")

    if re.search(r"\b(no hablo|amigo|amiga|gracias|señor|hola|buenos)\b", en_lower) or "Ў" in en or "ї" in en:
        tags.append("NECH:ES")
        hints.append("Španělská vsuvka — obvykle ponechat španělsky (amigo, No hablo inglés…).")

    if en_lower == "on fire":
        if "STAV:HOŘÍ" not in tags:
            tags.append("STAV:HOŘÍ")
            hints.append("Hoření — „v plamenech“. Nepoužívat „v palbě“.")
    elif "on fire" in en_lower:
        if re.search(r"feels like.*on fire|like it'?s on fire", en_lower):
            tags.append("METAFORA")
            hints.append("Metafora bolesti/tepla — ne bojový stav „v plamenech“.")
        elif re.search(r"set .* on fire|light .* on fire|lit .* on fire", en_lower):
            tags.append("AKCE:ZAPÁLIT")
            hints.append("Zapálení něčeho — sloveso zapálit/podpálit.")
        elif re.search(r"game'?s on fire|you're on fire", en_lower):
            tags.append("SLANG")
            hints.append("Hovorový výraz (něco je skvělé) — ne doslovné hoření.")

    if re.search(r"\bcaps\b", en_lower) and file_category.startswith("game"):
        tags.append("TERM:ZATKY")
        hints.append("Měna caps → zatky, ne víčka.")

    if len(en.split()) <= 3 and not re.search(r"%[sd]", en):
        tags.append("KRÁTKÉ")

    # dedupe preserving order
    seen = set()
    unique_tags = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)

    hint_cs = " ".join(dict.fromkeys(h for h in hints if h))
    ru_guide = ru_combat_guide_cs(row, unique_tags)

    out: dict[str, Any] = {"tags": unique_tags, "hint_cs": hint_cs}
    if ru_guide:
        out["ru_guide_cs"] = ru_guide
    return out


__all__ = ["enrich_row_context", "ru_combat_guide_cs"]
