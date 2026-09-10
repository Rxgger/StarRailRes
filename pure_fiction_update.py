#!/usr/bin/env python3
"""
Pulls Pure Fiction data from the private-build API into a brand-new
pure_fictions.json. Also downloads icons for any monster referenced by the
confirmed Pure Fiction tierce floor into icon/monster/, tracked in the same
challenge_peak_monsters.json registry used by the other import scripts.

Only ever looks at the 2 highest-numbered Pure Fiction groups in the API
response. For each confirmed group, only the floor with
has_tierce_mode=true is used — that's the one with 3 selectable nodes
(top/bot/tierce). Asks for confirmation per missing group.

Run this from the StarRailRes repo root (same folder as index_new/).
"""

import io
import json
import os
import re
import urllib.request
from collections import Counter

from PIL import Image


PURE_FICTION_URL = (
    "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/pure-fictions.json"
)
MONSTERS_URL = (
    "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/monsters.json"
)
STAGES_URL = (
    "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/stages.json"
)
TEXTMAPS_URL = (
    "https://cdn.neonteam.dev/neonteam/4.5.53-16399740/textmaps.json"
)

PURE_FICTIONS_PATH = os.path.join("index_new", "en", "pure_fictions.json")

# Shared with moc_update.py / challenge_peak_update.py.
MONSTERS_PATH = os.path.join(
    "index_new", "en", "challenge_peak_monsters.json"
)
ICON_DIR = os.path.join("icon", "monster")

CANDIDATE_GROUP_COUNT = 2
BATTLE_CYCLE_COUNT = 4

DESC_PLACEHOLDER = re.compile(
    r"<unbreak>#(\d+)(?:\[i\])?(%)?</unbreak>"
)
COLOR_TAG = re.compile(r"<color=[^>]*>(.*?)</color>")

NODE_NAMES = ("Node 1", "Node 2", "Node 3")


def fetch_json(url: str):
    print(f"Fetching {url} ...")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
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
    """Round away float32->float64 conversion noise."""
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
    return COLOR_TAG.sub(r"\1", text)


def format_value(value, has_percent: bool) -> str:
    # Match the MoC/challenge peak behavior:
    # values below 1 are percentages even when the source tag does not
    # explicitly contain '%'.
    if has_percent or (
        isinstance(value, (int, float)) and value < 1
    ):
        return f"{clean_number(value * 100)}%"

    return str(clean_number(value))


def format_description(text: str, params: list) -> str:
    """Resolve textmap text and substitute <unbreak> placeholders."""
    text = strip_color_tags(text)

    def replace_match(match: re.Match) -> str:
        index = int(match.group(1)) - 1
        has_percent = match.group(2) == "%"

        if 0 <= index < len(params):
            return format_value(params[index], has_percent)

        return match.group(0)

    return DESC_PLACEHOLDER.sub(replace_match, text)


def resolve_blessings(raw_blessings: list, textmap_en: dict) -> list:
    """
    Pure Fiction blessings have the same shape as the blessing/buff objects
    handled by the other import scripts:
        id, name, desc, desc_params
    """
    resolved = []

    for blessing in raw_blessings:
        name = resolve_text(blessing["name"], textmap_en)
        desc = resolve_text(blessing["desc"], textmap_en)

        resolved.append(
            {
                "id": blessing["id"],
                "name": name,
                "description": format_description(
                    desc, blessing.get("desc_params") or []
                ),
            }
        )

    return resolved


def resolve_fever_buffs(raw_buffs: list, textmap_en: dict) -> list:
    """
    fever_buff_info does not expose an id in the supplied Pure Fiction API.
    Resolve its name/desc and substitute desc_params.
    """
    resolved = []

    for buff in raw_buffs:
        name = resolve_text(buff["name"], textmap_en)
        desc = resolve_text(buff["desc"], textmap_en)

        resolved.append(
            {
                "name": name,
                "description": format_description(
                    desc, buff.get("desc_params") or []
                ),
            }
        )

    return resolved


def build_wave_monsters(
    spawn_configs: list, monster_level: int
) -> list:
    """
    Pure Fiction supplies spawn_configs for each node. Each wave is a dict
    keyed by monster id, with count information, so use those counts directly.
    """
    waves = []

    for wave in spawn_configs:
        waves.append(
            [
                {
                    "monster_id": int(mid),
                    "amount": info["count"],
                    "level": monster_level,
                }
                for mid, info in wave.items()
            ]
        )

    return waves


def build_node(
    name: str,
    monster_ids: list,
    spawn_configs: list,
    stage_id: int,
    level: int,
    maze_buff_id: int,
    stages_api: dict,
) -> dict:
    battle_blessings = []

    # Pure Fiction's main maze/fever blessing.
    if maze_buff_id is not None:
        battle_blessings.append(
            {
                "level": 1,
                "id": maze_buff_id,
            }
        )

    # A stage may carry an additional invasion blessing.
    stage = stages_api.get(str(stage_id))
    invasion_config = stage.get("invasion_config") if stage else None

    if invasion_config:
        invasion_maze_buff_id = invasion_config.get("maze_buff_id")

        if invasion_maze_buff_id is not None:
            battle_blessings.append(
                {
                    "level": 1,
                    "id": invasion_maze_buff_id,
                }
            )

    # spawn_configs are authoritative for the battle waves. monster_ids is
    # retained as an argument so the node mapping follows the MoC structure.
    # If an API response unexpectedly lacks spawn configs, fall back to the
    # same duplicate-counting approach used by moc_update.py.
    if spawn_configs:
        monsters = build_wave_monsters(spawn_configs, level)
    else:
        counts_by_wave = []

        for wave in monster_ids:
            counts = Counter(mid for mid in wave if mid != 0)
            counts_by_wave.append(
                [
                    {
                        "monster_id": mid,
                        "amount": count,
                        "level": level,
                    }
                    for mid, count in counts.items()
                ]
            )

        monsters = counts_by_wave

    return {
        "name": name,
        "stage_id": stage_id,
        "battle_config": {
            "battle_type": "PF",
            "blessings": battle_blessings,
            "custom_stats": [],
            "monsters": monsters,
            "stage_id": stage_id,
            "path_resonance_id": 0,
            "cycle_count": BATTLE_CYCLE_COUNT,
        },
    }


def find_tierce_floor(group: dict):
    return next(
        (
            floor
            for floor in group["floors"]
            if floor.get("has_tierce_mode")
        ),
        None,
    )


def build_pure_fiction_entry(
    group: dict, textmap_en: dict, stages_api: dict
):
    tierce_floor = find_tierce_floor(group)

    if tierce_floor is None:
        return None

    level = tierce_floor["level"]
    maze_buff_id = group.get("maze_buff_id")

    nodes = [
        build_node(
            NODE_NAMES[0],
            tierce_floor["monster_ids_top"],
            tierce_floor.get("spawn_configs_top") or [],
            tierce_floor["stage_id_top"],
            level,
            maze_buff_id,
            stages_api,
        ),
        build_node(
            NODE_NAMES[1],
            tierce_floor["monster_ids_bot"],
            tierce_floor.get("spawn_configs_bot") or [],
            tierce_floor["stage_id_bot"],
            level,
            maze_buff_id,
            stages_api,
        ),
        build_node(
            NODE_NAMES[2],
            tierce_floor["monster_ids_tierce"],
            tierce_floor.get("spawn_configs_tierce") or [],
            tierce_floor["stage_id_tierce"],
            level,
            maze_buff_id,
            stages_api,
        ),
    ]

    return {
        "id": group["id"],
        "name": resolve_text(group["name"], textmap_en),
        "begin_time": group.get("begin_time", ""),
        "end_time": group.get("end_time", ""),
        "blessings": resolve_blessings(
            group.get("blessings") or [], textmap_en
        ),
        "fever_buff_info": resolve_fever_buffs(
            group.get("fever_buff_info") or [], textmap_en
        ),
        "nodes": nodes,
    }


def collect_monster_ids(tierce_floor: dict) -> set:
    ids = set()

    # Use all three monster-id lists, matching MoC's collection behavior.
    for waves in (
        tierce_floor["monster_ids_top"],
        tierce_floor["monster_ids_bot"],
        tierce_floor["monster_ids_tierce"],
    ):
        for wave in waves:
            for mid in wave:
                if mid != 0:
                    ids.add(int(mid))

    return ids


def download_monster_icons(
    monster_ids: set, monsters_api: dict, registry: dict
) -> None:
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
            print(
                f"WARNING: no icon found for monster {mid_str}, skipping."
            )
            continue

        print(f"Downloading icon for monster {mid_str} ...")

        req = urllib.request.Request(
            icon_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64)"
                )
            },
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
    pure_fiction_api = fetch_json(PURE_FICTION_URL)

    textmaps = fetch_json(TEXTMAPS_URL)
    textmap_en = textmaps.get("EN", {})

    stages_api = fetch_json(STAGES_URL)

    pure_fictions = load_json_or_empty(PURE_FICTIONS_PATH)
    monsters_registry = load_json_or_empty(MONSTERS_PATH)

    # Only consider the 2 highest-numbered groups, exactly like MoC.
    candidate_ids = sorted(
        pure_fiction_api.keys(),
        key=int,
        reverse=True,
    )[:CANDIDATE_GROUP_COUNT]

    missing_ids = [
        gid for gid in candidate_ids
        if gid not in pure_fictions
    ]

    if not missing_ids:
        print(
            f"No new Pure Fiction groups found among the latest "
            f"{CANDIDATE_GROUP_COUNT} — everything is already present."
        )
        return

    added = []
    referenced_monster_ids = set()

    for gid in missing_ids:
        group = pure_fiction_api[gid]
        display_name = resolve_text(group["name"], textmap_en)

        if not confirm(
            f"Do you wanna update with {display_name} - {gid}?"
        ):
            print(f"Skipping {display_name} ({gid}).")
            continue

        entry = build_pure_fiction_entry(
            group,
            textmap_en,
            stages_api,
        )

        if entry is None:
            print(
                f"WARNING: {display_name} ({gid}) has no floor with "
                "has_tierce_mode=true, skipping."
            )
            continue

        pure_fictions[gid] = entry

        tierce_floor = find_tierce_floor(group)
        referenced_monster_ids |= collect_monster_ids(tierce_floor)

        added.append(f"{display_name} ({gid})")

    if not added:
        print("No Pure Fiction groups were added.")
        return

    save_json(PURE_FICTIONS_PATH, pure_fictions)

    if referenced_monster_ids:
        monsters_api = fetch_json(MONSTERS_URL)

        download_monster_icons(
            referenced_monster_ids,
            monsters_api,
            monsters_registry,
        )

        save_json(MONSTERS_PATH, monsters_registry)

    print(
        f"Added {len(added)} Pure Fiction group(s): "
        f"{', '.join(added)}"
    )


if __name__ == "__main__":
    main()
