# -*- coding: utf-8 -*-
"""
Logické třídění řádků překladu podle cesty souboru (dialog/game .msg struktura Sonora / Nevada).

Použití v translation_server GUI a nástrojích nad JSONL.
"""
from __future__ import annotations

import os


def dialog_area_codes_from_paths(file_paths) -> list[str]:
    """
    Dvoupísmenný kód mapové oblasti z názvu souboru dialogu (např. AC z ACAnti.msg).
    Nebere Z-* skriptové soubory ani OBJ_ prefix (to jsou výchozí interakce, ne město).
    """
    locs: set[str] = set()
    for fp in file_paths:
        if not fp:
            continue
        norm = fp.replace("\\", "/").lower()
        if not norm.startswith("dialog/"):
            continue
        base = os.path.basename(fp)
        upper = base.upper()
        if len(base) < 3 or upper.startswith("OBJ_"):
            continue
        if not (base[0].isupper() and base[1].isupper()):
            continue
        # Heuristika: Z* má v Sonorse typicky řádky kontejnerů/popupů jednotné přes více lokací
        if upper.startswith("Z"):
            continue
        locs.add(base[:2].upper())
    return sorted(locs)


def get_file_category(file_name, file_rows=None):
    """
    Vrací slug kategorie používaný v API a řádcích (`file_category`).

    Herní skupiny odpovídají typickému použití v engine (chargen, Pip-Boy, databáze světa, boj …).
    """
    if file_rows is None:
        file_rows = []

    if not file_name:
        return "dialog_scenery"

    if file_name.lower().startswith("game/"):
        base = os.path.basename(file_name).upper()
        # Tvorba / výběr postavy + vstupní obrazovky
        if base in ("EDITOR.MSG", "SCRNAME.MSG", "SCRNSET.MSG"):
            return "game_character_screen"
        # Herní nabídky, Pip-Boy, ukládání, nastavení, inventář
        if base in (
            "INTRFACE.MSG",
            "OPTIONS.MSG",
            "PIPBOY.MSG",
            "LSGAME.MSG",
            "INVENTRY.MSG",
        ):
            return "game_menus_gui"
        if base in ("COMBAT.MSG", "COMBATAI.MSG", "CMBATAI2.MSG"):
            return "game_combat"
        if base in ("PRO_ITEM.MSG", "ITEM.MSG"):
            return "game_items_gear"
        if base in ("PRO_CRIT.MSG",):
            return "game_critters"
        # Databázové řádky „co je X“ pro mapové objekty (You see proto…)
        if base in ("PRO_SCEN.MSG", "PRO_TILE.MSG", "PRO_WALL.MSG", "PRO_MISC.MSG", "PROTO.MSG"):
            return "game_world_proto"
        if base in ("QUESTS.MSG",):
            return "game_quests_journal"
        if base in ("WORLDMAP.MSG", "MAP.MSG"):
            return "game_world_travel_map"
        if base in ("PERK.MSG", "SKILL.MSG", "STAT.MSG", "TRAIT.MSG", "SKILLDEX.MSG"):
            return "game_perks_traits_skills"
        if base in ("SCRIPT.MSG", "DBOX.MSG", "MISC.MSG", "CUSTOM.MSG"):
            return "game_engine_strings"
        return "game_unknown"

    base_name = os.path.basename(file_name)
    base_upper = base_name.upper()

    if base_upper.startswith("OBJ_") or base_upper.startswith("Z") or "SIGN" in base_upper:
        return "dialog_scenery"

    # Lokace + NPC vzor (ACBoss, BHShop…)
    if len(base_name) >= 3 and base_name[0].isupper() and base_name[1].isupper() and base_name[2].isalpha():
        return "dialog_npc"

    for r in file_rows:
        try:
            if int(r.get("id", "0")) >= 200:
                return "dialog_npc"
        except ValueError:
            pass

    return "dialog_scenery"


__all__ = ["get_file_category", "dialog_area_codes_from_paths"]
