"""Shared build and private-content tracking for the update scripts."""

import json
import os
from pathlib import Path


CONFIG_FILE = Path(__file__).with_name("update_config.json")
TRACKED_CATEGORIES = ("characters", "light_cones", "relic_sets")
_DISCOVERY_PROGRESS_KEY = "_discovery_completed"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"{CONFIG_FILE.name} does not exist. Create it beside the update scripts."
        )

    with CONFIG_FILE.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    build = config.get("build")
    if not isinstance(build, str) or not build.strip():
        raise ValueError(f"{CONFIG_FILE.name} must contain a non-empty 'build' value")

    if not isinstance(config.get("tracking_initialized"), bool):
        raise ValueError(
            f"{CONFIG_FILE.name} must contain a boolean 'tracking_initialized' value"
        )

    for category in TRACKED_CATEGORIES:
        values = config.get(category)
        if not isinstance(values, list) or not all(
            isinstance(value, (str, int)) for value in values
        ):
            raise ValueError(f"{CONFIG_FILE.name} must contain an array named '{category}'")
        config[category] = [str(value) for value in values]

    return config


def save_config(config: dict) -> None:
    temporary_path = CONFIG_FILE.with_suffix(f"{CONFIG_FILE.suffix}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as config_file:
            json.dump(config, config_file, indent=4, ensure_ascii=False)
            config_file.write("\n")
        os.replace(temporary_path, CONFIG_FILE)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def get_build_version() -> str:
    return load_config()["build"].strip()


def api_url(filename: str) -> str:
    return f"https://cdn.neonteam.dev/neonteam/{get_build_version()}/{filename}"


def begin_tracking(category: str, api_ids, local_ids) -> tuple[list[str], bool]:
    """Choose IDs for either discovery or refresh mode."""
    if category not in TRACKED_CATEGORIES:
        raise ValueError(f"Unknown tracking category: {category}")

    config = load_config()
    if config["tracking_initialized"]:
        tracked_ids = list(dict.fromkeys(config[category]))
        print(f"Refreshing {len(tracked_ids)} tracked {category.replace('_', ' ')} item(s).")
        return tracked_ids, False

    progress = config.get(_DISCOVERY_PROGRESS_KEY)
    if not isinstance(progress, list):
        for tracked_category in TRACKED_CATEGORIES:
            config[tracked_category] = []
        config[_DISCOVERY_PROGRESS_KEY] = []
        save_config(config)
        print("Started private-content discovery; cleared the previous tracked IDs.")

    local_id_set = {str(value) for value in local_ids}
    missing_ids = [str(value) for value in api_ids if str(value) not in local_id_set]
    print(
        f"Discovery found {len(missing_ids)} missing "
        f"{category.replace('_', ' ')} item(s)."
    )
    return missing_ids, True


def finish_tracking(
    category: str, processed_ids, discovery: bool, completed: bool = True
) -> None:
    if not discovery:
        return

    config = load_config()
    existing = config[category]
    config[category] = list(
        dict.fromkeys([*existing, *(str(value) for value in processed_ids)])
    )

    progress = config.get(_DISCOVERY_PROGRESS_KEY, [])
    if completed and category not in progress:
        progress.append(category)

    if all(tracked_category in progress for tracked_category in TRACKED_CATEGORIES):
        config["tracking_initialized"] = True
        config.pop(_DISCOVERY_PROGRESS_KEY, None)
        print("Private-content discovery completed; tracking_initialized is now true.")
    else:
        config[_DISCOVERY_PROGRESS_KEY] = progress

    save_config(config)
