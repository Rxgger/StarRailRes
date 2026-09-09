#!/usr/bin/env python3
"""
Pulls challenge peak data (one of the endgame modes) from the private-build
API into a brand-new challenge_peaks.json (this doesn't exist in the real
StarRailRes repo — it's specific to this project). Also downloads icons for
any monster referenced by the confirmed peak groups into icon/monster/, and
tracks them in a small challenge_peak_monsters.json registry.

Only ever looks at the 2 highest-numbered peak groups in the API response
(e.g. groups 9 and 10) — older groups are irrelevant rotations we don't
want cluttering the local file. Asks for confirmation per missing group.

Run this from the StarRailRes repo root (same folder as index_new/).
"""

import io
import json
import os
import re
import sys
import urllib.request

from PIL import Image

CHALLENGE_PEAK_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/challenge-peak.json"
MONSTERS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/monsters.json"
TEXTMAPS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/textmaps.json"

CHALLENGE_PEAKS_PATH = os.path.join("index_new", "en", "challenge_peaks.json")
MONSTERS_PATH = os.path.join("index_new", "en", "challenge_peak_monsters.json")
ICON_DIR = os.path.join("icon", "monster")

# Only the N highest-numbered peak groups in the API are ever considered —
# older rotations aren't worth carrying around locally.
CANDIDATE_GROUP_COUNT = 2

DESC_PLACEHOLDER = re.compile(r'<unbreak>#(\d+)(?:\[i\])?(%)?</unbreak>')
COLOR_TAG = re.compile(r'<color=[^>]*>(.*?)</color>')


def fetch_json(url: str):
    print(f"Fetching {url} ...")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def load_json_or_empty(path: str) -> dict:
    """Unlike the other import scripts, this file is brand new and may not
    exist on disk yet at all — that's expected, not an error."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


def clean_number(value):
    """Round away float32->float64 conversion noise and turn whole numbers
    into plain ints, matching the other import scripts' convention."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        rounded = round(float(value), 6)
        return int(rounded) if rounded == int(rounded) else rounded
    return value


def resolve_text(hash_value, textmap_en: dict) -> str:
    key = str(hash_value)
    return textmap_en.get(key, key)


def format_value(value, has_percent: bool) -> str:
    # Even without an explicit "%" on the <unbreak> tag, a raw value under 1
    # is meant to be read as a percentage (e.g. 0.06 -> "6%"), not a literal
    # decimal — values of 1 or more are left as plain numbers.
    if has_percent or (isinstance(value, (int, float)) and value < 1):
        return f"{clean_number(value * 100)}%"
    return str(clean_number(value))


def strip_color_tags(text: str) -> str:
    """Removes <color=#f29e38ff>...</color>-style styling tags, keeping the
    text inside them."""
    return COLOR_TAG.sub(r'\1', text)


def format_description(text: str, params: list) -> str:
    """Substitutes <unbreak>#1[i]%</unbreak>-style placeholders with the
    corresponding value from desc_params (a flat list of numbers here,
    unlike the relic set data where each param was itself an object), and
    strips <color=...> styling tags entirely."""
    text = strip_color_tags(text)

    def replace_match(match: re.Match) -> str:
        index = int(match.group(1)) - 1
        has_percent = match.group(2) == '%'
        if 0 <= index < len(params):
            return format_value(params[index], has_percent)
        return match.group(0)

    return DESC_PLACEHOLDER.sub(replace_match, text)


def resolve_buffs(raw_buffs: list, textmap_en: dict) -> list:
    """Shared shape for monster_tag_maze_buffs and boss_maze_buffs — both
    are {id, name (hash), desc (hash), desc_params}."""
    resolved = []
    for buff in raw_buffs:
        name = resolve_text(buff["name"], textmap_en)
        desc = resolve_text(buff["desc"], textmap_en)
        resolved.append({
            "id": buff["id"],
            "name": name,
            "description": format_description(desc, buff.get("desc_params") or []),
        })
    return resolved


def build_monsters_by_wave(spawn_config: list, monster_level: int) -> list:
    """spawn_config is a list of waves; each wave is a dict keyed by
    monster_id (string) with its own count. This already has everything
    processed_output.json's battle_config.monsters needs — no reason to
    also cross-reference the separate monster_ids array."""
    waves = []
    for wave in spawn_config:
        waves.append([
            {"monster_id": int(mid), "amount": info["count"], "level": monster_level}
            for mid, info in wave.items()
        ])
    return waves


def build_peak_entry(peak: dict, textmap_en: dict) -> dict:
    monster_level = peak["monster_level"]
    monsters_by_wave = build_monsters_by_wave(peak["spawn_config"], monster_level)

    blessings_raw = peak.get("monster_tag_maze_buffs") or []
    blessings_display = resolve_buffs(blessings_raw, textmap_en)
    battle_blessings = [{"level": 1, "id": b["id"]} for b in blessings_raw]

    is_boss = bool(peak.get("is_boss"))
    boss_buffs = resolve_buffs(peak.get("boss_maze_buffs") or [], textmap_en) if is_boss else []

    return {
        "peak_id": peak["peak_id"],
        "name": resolve_text(peak["name"], textmap_en),
        "stage_id": peak["stage_id"],
        "monster_level": monster_level,
        "is_boss": is_boss,
        "blessings": blessings_display,
        "boss_buffs": boss_buffs,
        # Ready to be spliced straight into rygger-data.json's battle
        # config, unmodified, once the app side picks a fight.
        "battle_config": {
            "battle_type": "DEFAULT",
            "blessings": battle_blessings,
            "custom_stats": [],
            "monsters": monsters_by_wave,
            "stage_id": peak["stage_id"],
            "path_resonance_id": 0,
            "cycle_count": 0,
        },
    }


def collect_monster_ids(group: dict) -> set:
    ids = set()
    for peak in group["peaks"]:
        for wave in peak["spawn_config"]:
            for mid in wave:
                ids.add(int(mid))
    return ids


def download_monster_icons(monster_ids: set, monsters_api: dict, registry: dict) -> None:
    os.makedirs(ICON_DIR, exist_ok=True)

    for mid in sorted(monster_ids):
        mid_str = str(mid)
        target_path = os.path.join(ICON_DIR, f"{mid_str}.png")
        relative_path = f"icon/monster/{mid_str}.png"

        if mid_str in registry and os.path.exists(target_path):
            continue  # already fetched in a previous run

        monster = monsters_api.get(mid_str)
        icon_url = monster.get("icon") if monster else None
        if not icon_url:
            print(f"WARNING: no icon found for monster {mid_str}, skipping.")
            continue

        print(f"Downloading icon for monster {mid_str} ...")
        req = urllib.request.Request(
            icon_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req) as response:
            raw_bytes = response.read()

        image = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
        image.save(target_path, "PNG")

        registry[mid_str] = {"icon": relative_path}


def confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def main():
    challenge_peak_api = fetch_json(CHALLENGE_PEAK_URL)
    textmaps = fetch_json(TEXTMAPS_URL)
    textmap_en = textmaps.get("EN", {})

    challenge_peaks = load_json_or_empty(CHALLENGE_PEAKS_PATH)
    monsters_registry = load_json_or_empty(MONSTERS_PATH)

    candidate_ids = sorted(challenge_peak_api.keys(), key=int, reverse=True)[:CANDIDATE_GROUP_COUNT]
    missing_ids = [gid for gid in candidate_ids if gid not in challenge_peaks]

    if not missing_ids:
        print(f"No new challenge peak groups found among the latest {CANDIDATE_GROUP_COUNT} "
              "— everything is already present.")
        return

    added = []
    referenced_monster_ids = set()

    for gid in missing_ids:
        group = challenge_peak_api[gid]
        display_name = resolve_text(group["name"], textmap_en)

        if not confirm(f"Do you wanna update with {display_name} - {gid}?"):
            print(f"Skipping {display_name} ({gid}).")
            continue

        challenge_peaks[gid] = {
            "id": group["id"],
            "name": display_name,
            "peaks": [build_peak_entry(peak, textmap_en) for peak in group["peaks"]],
        }
        referenced_monster_ids |= collect_monster_ids(group)
        added.append(f"{display_name} ({gid})")

    if not added:
        print("No challenge peak groups were added.")
        return

    save_json(CHALLENGE_PEAKS_PATH, challenge_peaks)

    if referenced_monster_ids:
        monsters_api = fetch_json(MONSTERS_URL)
        download_monster_icons(referenced_monster_ids, monsters_api, monsters_registry)
        save_json(MONSTERS_PATH, monsters_registry)

    print(f"Added {len(added)} challenge peak group(s): {', '.join(added)}")


if __name__ == "__main__":
    main()