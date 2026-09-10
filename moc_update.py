#!/usr/bin/env python3
"""
Pulls MoC (Memory of Chaos) data from the private-build API into a
brand-new moc.json — like challenge_peaks.json, this doesn't exist in the
real StarRailRes repo. Also downloads icons for any monster referenced by
the confirmed group's tierce floor into icon/monster/, tracked in the same
challenge_peak_monsters.json registry used by the challenge peak script.

Only ever looks at the 2 highest-numbered MoC groups in the API response.
For each confirmed group, only the floor with has_tierce_mode=true is used
— that's the one with 3 selectable nodes (top/bot/tierce). Asks for
confirmation per missing group.

Run this from the StarRailRes repo root (same folder as index_new/).
"""

import io
import json
import os
import re
from collections import Counter

import urllib.request

from PIL import Image

MOC_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/moc.json"
MONSTERS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/monsters.json"
STAGES_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/stages.json"
TEXTMAPS_URL = "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/textmaps.json"

MOC_PATH = os.path.join("index_new", "en", "moc.json")
# Shared with import_challenge_peaks.py — same registry, same icon folder.
MONSTERS_PATH = os.path.join("index_new", "en", "challenge_peak_monsters.json")
ICON_DIR = os.path.join("icon", "monster")

CANDIDATE_GROUP_COUNT = 2
BATTLE_CYCLE_COUNT = 30

DESC_PLACEHOLDER = re.compile(r'<unbreak>#(\d+)(?:\[i\])?(%)?</unbreak>')
COLOR_TAG = re.compile(r'<color=[^>]*>(.*?)</color>')

NODE_NAMES = ("Node 1", "Node 2", "Node 3")


def fetch_json(url: str):
    print(f"Fetching {url} ...")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def load_json_or_empty(path: str) -> dict:
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
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        rounded = round(float(value), 6)
        return int(rounded) if rounded == int(rounded) else rounded
    return value


def resolve_text(hash_value, textmap_en: dict) -> str:
    key = str(hash_value)
    return textmap_en.get(key, key)


def strip_color_tags(text: str) -> str:
    return COLOR_TAG.sub(r'\1', text)


def format_value(value, has_percent: bool) -> str:
    if has_percent or (isinstance(value, (int, float)) and value < 1):
        return f"{clean_number(value * 100)}%"
    return str(clean_number(value))


def format_description(text: str, params: list) -> str:
    text = strip_color_tags(text)

    def replace_match(match: re.Match) -> str:
        index = int(match.group(1)) - 1
        has_percent = match.group(2) == '%'
        if 0 <= index < len(params):
            return format_value(params[index], has_percent)
        return match.group(0)

    return DESC_PLACEHOLDER.sub(replace_match, text)


def build_wave_monsters(waves: list, level: int) -> list:
    """No spawn_config exists for MoC (always empty in the API) — amount is
    derived by counting duplicate monster ids within each wave instead."""
    result = []
    for wave in waves:
        counts = Counter(mid for mid in wave if mid != 0)
        result.append([
            {"monster_id": mid, "amount": count, "level": level}
            for mid, count in counts.items()
        ])
    return result


def build_node(name: str, monster_ids: list, stage_id: int, level: int, turbulence_maze_buff_id: int, stages_api: dict) -> dict:
    battle_blessings = []
    battle_blessings.append({"level": 1, "id": turbulence_maze_buff_id})

    stage = stages_api.get(str(stage_id))
    invasion_config = stage.get("invasion_config") if stage else None
    if invasion_config:
        maze_buff_id = invasion_config.get("maze_buff_id")
        if maze_buff_id is not None:
            battle_blessings.append({"level": 1, "id": maze_buff_id})


    return {
        "name": name,
        "stage_id": stage_id,
        "battle_config": {
            "battle_type": "MOC",
            "blessings": battle_blessings,
            "custom_stats": [],
            "monsters": build_wave_monsters(monster_ids, level),
            "stage_id": stage_id,
            "path_resonance_id": 0,
            "cycle_count": BATTLE_CYCLE_COUNT,
        },
    }


def find_tierce_floor(group: dict):
    return next((f for f in group["floors"] if f.get("has_tierce_mode")), None)


def build_moc_entry(group: dict, textmap_en: dict, stages_api: dict):
    tierce_floor = find_tierce_floor(group)
    if tierce_floor is None:
        return None

    turbulence_maze_buff_id = tierce_floor["turbulence_maze_buff_id"]
    turbulence_description = format_description(
        resolve_text(tierce_floor["turbulence_desc"], textmap_en),
        tierce_floor.get("turbulence_desc_params") or []
    )

    level = tierce_floor["level"]
    nodes = [
        build_node(NODE_NAMES[0], tierce_floor["monster_ids_top"], tierce_floor["stage_id_top"],
                   level, turbulence_maze_buff_id, stages_api),
        build_node(NODE_NAMES[1], tierce_floor["monster_ids_bot"], tierce_floor["stage_id_bot"],
                   level, turbulence_maze_buff_id, stages_api),
        build_node(NODE_NAMES[2], tierce_floor["monster_ids_tierce"], tierce_floor["stage_id_tierce"],
                   level, turbulence_maze_buff_id, stages_api),
    ]

    return {
        "id": group["id"],
        "name": resolve_text(group["name"], textmap_en),
        "begin_time": group.get("begin_time", ""),
        "end_time": group.get("end_time", ""),
        # No separate name hash exists for the turbulence buff in this API
        # (unlike challenge peak's blessings) — description only.
        "turbulence": {
            "id": turbulence_maze_buff_id,
            "description": turbulence_description,
        },
        "nodes": nodes,
    }


def collect_monster_ids(tierce_floor: dict) -> set:
    ids = set()
    for waves in (tierce_floor["monster_ids_top"], tierce_floor["monster_ids_bot"], tierce_floor["monster_ids_tierce"]):
        for wave in waves:
            for mid in wave:
                if mid != 0:
                    ids.add(int(mid))
    return ids


def download_monster_icons(monster_ids: set, monsters_api: dict, registry: dict) -> None:
    os.makedirs(ICON_DIR, exist_ok=True)

    for mid in sorted(monster_ids):
        mid_str = str(mid)
        target_path = os.path.join(ICON_DIR, f"{mid_str}.png")
        relative_path = f"icon/monster/{mid_str}.png"

        if mid_str in registry and os.path.exists(target_path):
            continue

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
    moc_api = fetch_json(MOC_URL)
    textmaps = fetch_json(TEXTMAPS_URL)
    textmap_en = textmaps.get("EN", {})

    stages_api = fetch_json(STAGES_URL)

    moc = load_json_or_empty(MOC_PATH)
    monsters_registry = load_json_or_empty(MONSTERS_PATH)

    candidate_ids = sorted(moc_api.keys(), key=int, reverse=True)[:CANDIDATE_GROUP_COUNT]
    missing_ids = [gid for gid in candidate_ids if gid not in moc]

    if not missing_ids:
        print(f"No new MoC groups found among the latest {CANDIDATE_GROUP_COUNT} — everything is already present.")
        return

    added = []
    referenced_monster_ids = set()

    for gid in missing_ids:
        group = moc_api[gid]
        display_name = resolve_text(group["name"], textmap_en)

        if not confirm(f"Do you wanna update with {display_name} - {gid}?"):
            print(f"Skipping {display_name} ({gid}).")
            continue

        entry = build_moc_entry(group, textmap_en, stages_api)
        if entry is None:
            print(f"WARNING: {display_name} ({gid}) has no floor with has_tierce_mode=true, skipping.")
            continue

        moc[gid] = entry
        referenced_monster_ids |= collect_monster_ids(find_tierce_floor(group))
        added.append(f"{display_name} ({gid})")

    if not added:
        print("No MoC groups were added.")
        return

    save_json(MOC_PATH, moc)

    if referenced_monster_ids:
        monsters_api = fetch_json(MONSTERS_URL)
        download_monster_icons(referenced_monster_ids, monsters_api, monsters_registry)
        save_json(MONSTERS_PATH, monsters_registry)

    print(f"Added {len(added)} MoC group(s): {', '.join(added)}")


if __name__ == "__main__":
    main()