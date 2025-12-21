import csv
import os
import time
from contextlib import contextmanager
from typing import Iterable, List

from core.models import DATE_FMT, ItemRecord, MoneyRecord

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - non-Windows
    msvcrt = None

_LOCK_RETRIES = 5
_LOCK_DELAY = 0.1


@contextmanager
def locked_file(path: str, mode: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fh = open(path, mode, newline="", encoding="utf-8")
    try:
        _lock_file(fh)
        yield fh
    finally:
        _unlock_file(fh)
        fh.close()


def _lock_file(fh) -> None:
    if fcntl:
        for _ in range(_LOCK_RETRIES):
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                time.sleep(_LOCK_DELAY)
    elif msvcrt:
        for _ in range(_LOCK_RETRIES):
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(_LOCK_DELAY)


def _unlock_file(fh) -> None:
    if fcntl:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
    elif msvcrt:
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


def read_items(path: str) -> List[ItemRecord]:
    if not os.path.exists(path):
        return []
    with locked_file(path, "r") as fh:
        reader = csv.DictReader(fh)
        return [ItemRecord.from_row(row, DATE_FMT) for row in reader]


def write_items(path: str, items: Iterable[ItemRecord]) -> None:
    with locked_file(path, "w") as fh:
        writer = csv.DictWriter(fh, fieldnames=ItemRecord.headers())
        writer.writeheader()
        for item in items:
            writer.writerow(item.to_row(DATE_FMT))


def read_money(path: str) -> List[MoneyRecord]:
    if not os.path.exists(path):
        return []
    with locked_file(path, "r") as fh:
        reader = csv.DictReader(fh)
        return [MoneyRecord.from_row(row, DATE_FMT) for row in reader]


def write_money(path: str, entries: Iterable[MoneyRecord]) -> None:
    with locked_file(path, "w") as fh:
        writer = csv.DictWriter(fh, fieldnames=MoneyRecord.headers())
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.to_row(DATE_FMT))
