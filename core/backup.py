import os
import shutil
from datetime import datetime
from typing import Dict, List


def create_backup(source_path: str, backup_dir: str, policy: Dict[str, int]) -> str:
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Cannot back up missing file: {source_path}")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    base = os.path.basename(source_path)
    name, ext = os.path.splitext(base)
    backup_path = os.path.join(backup_dir, f"{name}_{timestamp}{ext or '.bak'}")
    shutil.copy2(source_path, backup_path)
    enforce_retention(base, backup_dir, policy)
    return backup_path


def enforce_retention(filename: str, backup_dir: str, policy: Dict[str, int]) -> None:
    keep_recent = int(policy.get("keep_recent", 3))
    keep_historical = int(policy.get("keep_historical", 3))
    prefix = os.path.splitext(filename)[0]

    backups = [
        os.path.join(backup_dir, f)
        for f in os.listdir(backup_dir)
        if f.startswith(prefix + "_")
    ]
    if len(backups) <= keep_recent + keep_historical:
        return

    backups_sorted = sorted(backups, key=os.path.getmtime, reverse=True)
    recent = backups_sorted[:keep_recent]
    remainder = backups_sorted[keep_recent:]

    historical = _select_historical(remainder, keep_historical)
    to_keep = set(recent + historical)

    for path in backups_sorted:
        if path not in to_keep:
            try:
                os.remove(path)
            except OSError:
                pass


def _select_historical(paths: List[str], count: int) -> List[str]:
    if count <= 0 or not paths:
        return []
    oldest_to_newest = list(reversed(sorted(paths, key=os.path.getmtime, reverse=True)))
    if len(oldest_to_newest) <= count:
        return oldest_to_newest
    step = max(1, len(oldest_to_newest) // count)
    selected = []
    for idx in range(0, len(oldest_to_newest), step):
        selected.append(oldest_to_newest[idx])
        if len(selected) == count:
            break
    return selected
