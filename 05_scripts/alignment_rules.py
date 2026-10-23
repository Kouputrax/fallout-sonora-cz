# -*- coding: utf-8 -*-
"""
Pravidla pro přijetí překladu z F1 / F2 / Nevada při párování.

Používá stejný kontext jako context_tags + QA detektor z pipeline.
"""
from __future__ import annotations

import re
from typing import Any

from context_tags import enrich_row_context

try:
    from sonora_msg_pipeline import check_row_issues, postprocess_cs
except ImportError:
    check_row_issues = None  # type: ignore
    postprocess_cs = None  # type: ignore

# Tier 2 u stejného EN v jiném ID rozbíjí rod u COMBAT šablon
COMBAT_NO_CROSS_ID = {"COMBAT.MSG"}

CRITICAL_ALIGN_ISSUES = frozenset({
    "align_combat_missing_jsi",
    "align_combat_wrong_plural",
    "align_combat_npc_has_jsi",
    "align_combat_wrong_gender_npc_m",
    "align_combat_wrong_gender_npc_f",
    "align_combat_wrong_gender_player_m",
    "align_combat_wrong_gender_player_f",
})


def _basename_upper(file_name: str) -> str:
    import os
    return os.path.basename((file_name or "").replace("\\", "/")).upper()


def _combat_alignment_issues(row: dict[str, Any], candidate_cs: str) -> list[str]:
    probe = dict(row)
    probe["cs"] = candidate_cs
    ctx = enrich_row_context(probe)
    tags = set(ctx.get("tags") or [])
    cs_l = (candidate_cs or "").lower()
    issues: list[str] = []
    is_frag = "FRAG" in tags

    if "MUŽ:HRÁČ" in tags or "ŽENA:HRÁČ" in tags:
        if not is_frag and not re.search(r"\bjsi\b", cs_l):
            issues.append("align_combat_missing_jsi")
        if re.search(r"\bbyli\b", cs_l):
            issues.append("align_combat_wrong_plural")
        if "MUŽ:HRÁČ" in tags and re.search(r"\bbyla jsi\b", cs_l):
            issues.append("align_combat_wrong_gender_player_f")
        if "ŽENA:HRÁČ" in tags and re.search(r"\bbyl jsi\b", cs_l):
            issues.append("align_combat_wrong_gender_player_m")
    elif "MUŽ:NPC" in tags:
        if re.search(r"\bjsi\b", cs_l):
            issues.append("align_combat_npc_has_jsi")
        if re.search(r"\bbyla\b|\bbyla zasažena\b", cs_l):
            issues.append("align_combat_wrong_gender_npc_m")
    elif "ŽENA:NPC" in tags:
        if re.search(r"\bjsi\b", cs_l):
            issues.append("align_combat_npc_has_jsi")
        if re.search(r"\bbyl zasažen\b|\bbyl kriticky\b", cs_l):
            issues.append("align_combat_wrong_gender_npc_f")

    return issues


def postprocess_aligned_cs(row: dict[str, Any], en: str, cs: str) -> tuple[str, list[str]]:
    """
    Opravy známých chyb z F1/F2/Nevada CZ před přijetím shody.
    Vrací (opravený text, seznam aplikovaných oprav).
    """
    if not cs or not cs.strip():
        return cs, []

    original = cs
    fixes: list[str] = []

    if postprocess_cs:
        cs = postprocess_cs(cs)
        if cs != original:
            fixes.append("postprocess")

    en_l = (en or "").lower()
    ctx = enrich_row_context({**row, "en": en, "cs": cs})
    tags = set(ctx.get("tags") or [])

    def sub_fix(pattern: str, repl: str, label: str, *, flags=re.IGNORECASE) -> None:
        nonlocal cs
        new_cs, n = re.subn(pattern, repl, cs, flags=flags)
        if n:
            cs = new_cs
            if label not in fixes:
                fixes.append(label)

    # Hoření (on fire) — F2 často „v palbě“
    if "on fire" in en_l or "STAV:HOŘÍ" in tags or en_l.strip() == "on fire":
        sub_fix(r"\bv palbě\b", "v plamenech", "on_fire")
        sub_fix(r"\bv palbu\b", "v plamenech", "on_fire")

    # Domovský přístav
    if "home port" in en_l:
        sub_fix(r"\bzbrojna\b", "domovský přístav", "home_port")
        sub_fix(r"\bzbrojnu\b", "domovského přístavu", "home_port")
        sub_fix(r"\bzbrojny\b", "domovského přístavu", "home_port")

    # Zátky místo kryšek
    if re.search(r"\bcaps\b|bottle cap", en_l):
        sub_fix(r"\bkryštkami\b", "zátkami", "bottle_caps")
        sub_fix(r"\bkryštky\b", "zátky", "bottle_caps")
        sub_fix(r"\bkryštku\b", "zátce", "bottle_caps")

    # Fallout zkratky (herní UI)
    if (row.get("file") or "").lower().startswith("game/"):
        sub_fix(r"\bAB\b", "AP", "ap_abbr")
        sub_fix(r"\bAK\b", "AP", "ap_abbr")
        sub_fix(r"\bBZ\b", "HP", "hp_abbr")
        sub_fix(r"\bZB\b", "XP", "xp_abbr")
        sub_fix(r"\bOČ\b", "AC", "ac_abbr")

    # Idiomy a falešní přátelé
    if "fair winds" in en_l:
        sub_fix(r"fair winds", "vítr do plachet", "fair_winds")
    sub_fix(r"větrný vítr", "vítr do plachet", "wind_phrase")
    if "gold" in en_l:
        sub_fix(r"\bgoldem\b", "zlatem", "gold")
    sub_fix(r"\bpřežiješ, nebo zemřeš sám\b", "chcípneš", "survive_phrase")
    sub_fix(r"zemřeš sám za sebe", "chcípneš", "survive_phrase")

    # Cesareo
    if re.search(r"\bcesareo\b", en_l, re.IGNORECASE):
        sub_fix(r"\b(Caesar|Císař|Cesář|Cisar)\b", "Cesareo", "cesareo")

    # Španělština vs čeština
    if "Spanish" in en:
        sub_fix(r"\bčesky\b", "španělsky", "spanish")
        sub_fix(r"\bcesky\b", "španělsky", "spanish")

    # Tykání u hráče
    if en_l.startswith("you ") or "POPIS:Vidíš" in tags or "RU:TY" in tags:
        sub_fix(r"\bVidíte\b", "Vidíš", "informal_you")

    # Morfologie
    sub_fix(r"stimpakú", "stimpaky", "stimpak")
    sub_fix(r"stimpaku\b", "stimpaky", "stimpak")

    # COMBAT šablony — druhé %s = část těla v 1. pádu (hlava); nepoužívat „v %s“
    if "critically hit in %s" in en_l:
        if "for no damage" in en_l:
            if "MUŽ:HRÁČ" in tags:
                canonical = "%s Byl jsi kriticky, ale bez poškození zasažen. Místo zásahu: %s"
            elif "ŽENA:HRÁČ" in tags:
                canonical = "%s Byla jsi kriticky, ale bez zranění zasažena. Místo zásahu: %s"
            elif "MUŽ:NPC" in tags:
                canonical = "%s byl kriticky zasažen, ale útok mu nezpůsobil žádné zranění. Místo zásahu: %s"
            elif "ŽENA:NPC" in tags:
                canonical = "%s byla kriticky zasažena, ale útok jí nezpůsobil žádné zranění. Místo zásahu: %s"
            else:
                canonical = ""
            if canonical and cs != canonical:
                cs = canonical
                if "combat_crit_no_damage" not in fixes:
                    fixes.append("combat_crit_no_damage")
        elif re.search(r"\bv %s\b|\bdo %s\b", cs, re.IGNORECASE):
            # Špatný doslovný překlad „in %s“ — F2 používá „Místo zásahu: %s“
            new_cs = re.sub(
                r"\s+v %s\s+",
                ". Místo zásahu: %s. ",
                cs,
                count=1,
                flags=re.IGNORECASE,
            )
            new_cs = re.sub(
                r"\s+do %s\s+",
                ". Místo zásahu: %s. ",
                new_cs,
                count=1,
                flags=re.IGNORECASE,
            )
            if new_cs != cs:
                cs = new_cs
                if "combat_body_part_label" not in fixes:
                    fixes.append("combat_body_part_label")

    # Kombinované tvary — nechat první větev (nedá se spolehlivě automaticky)
    # Cyrilice / mojibake — základní
    if re.search(r"[\u0400-\u04FF]", cs):
        sub_fix(r"крышками", "zátkami", "mojibake")
        sub_fix(r"compaсero", "compañero", "mojibake")
        sub_fix(r"compaсera", "compañera", "mojibake")
        sub_fix(r"Ў", "¡", "mojibake")

    return cs, fixes


def validate_alignment_candidate(
    row: dict[str, Any],
    candidate_cs: str,
    *,
    match_tier: int,
    source_game: str,
) -> dict[str, Any]:
    """
    Vrátí:
      accepted: bool
      status: aligned_confirmed | aligned_review
      issues: seznam kódů
      note: doplněk do notes
    """
    en = row.get("en") or ""
    issues: list[str] = []

    if not candidate_cs or not candidate_cs.strip():
        return {"accepted": False, "status": "", "issues": ["empty_cs"], "note": ""}

    candidate_cs, auto_fixes = postprocess_aligned_cs(row, en, candidate_cs)

    base = _basename_upper(row.get("file", ""))
    if match_tier >= 2 and base in COMBAT_NO_CROSS_ID:
        return {
            "accepted": False,
            "status": "",
            "issues": ["combat_tier2_blocked"],
            "note": "",
        }

    if check_row_issues:
        issues.extend(check_row_issues(en, candidate_cs))

    if base == "COMBAT.MSG" or (row.get("file") or "").lower().startswith("game/"):
        issues.extend(_combat_alignment_issues(row, candidate_cs))

    critical = [i for i in issues if i in CRITICAL_ALIGN_ISSUES]
    if critical:
        return {
            "accepted": False,
            "status": "",
            "issues": issues,
            "note": f"rules: rejected ({', '.join(critical)})",
            "cs": candidate_cs,
            "auto_fixes": auto_fixes,
        }

    fix_suffix = f"; auto-fix: {','.join(auto_fixes)}" if auto_fixes else ""

    if issues or match_tier >= 2:
        return {
            "accepted": True,
            "status": "aligned_review",
            "issues": issues,
            "cs": candidate_cs,
            "auto_fixes": auto_fixes,
            "note": (
                f"[Aligned from {source_game} - Tier {match_tier}; review: {', '.join(issues[:3])}]"
                if issues
                else f"[Aligned from {source_game} - Tier {match_tier}]"
            ) + fix_suffix,
        }

    return {
        "accepted": True,
        "status": "aligned_confirmed",
        "issues": [],
        "cs": candidate_cs,
        "auto_fixes": auto_fixes,
        "note": f"[Aligned from {source_game} - Tier {match_tier}]{fix_suffix}",
    }


__all__ = [
    "COMBAT_NO_CROSS_ID",
    "postprocess_aligned_cs",
    "validate_alignment_candidate",
]
