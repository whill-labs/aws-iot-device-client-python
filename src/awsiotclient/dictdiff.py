from copy import deepcopy
from typing import Any, Dict, Optional

from . import get_module_logger

logger = get_module_logger(__name__)


def dictdiff(
    s1: Optional[Dict[Any, Any]], s2: Optional[Dict[Any, Any]]
) -> Optional[Dict[Any, Any]]:
    if not s2 or s1 == s2:
        return None
    if not s1:
        return deepcopy(s2)  # s1 is empty.

    dst = dict()
    for k in s1.keys() | s2.keys():
        v1 = s1.get(k)
        v2 = s2.get(k)
        if v1 == v2:
            continue  # Not changed

        if v1 is None:
            logger.debug(f"Added Item ({k})  : None -> {v2}")
            dst[k] = deepcopy(v2)
            continue

        if v2 is None:
            logger.debug(f"Removed Item ({k}): {v1} -> None")
            dst[k] = None  # Removed Item
            continue

        if isinstance(v1, dict) and isinstance(v2, dict):
            dst[k] = dictdiff(v1, v2)
        else:
            logger.debug(f"Updated Item ({k}): {v1} -> {v2}")
            dst[k] = deepcopy(v2)  # Updated item

    return dst


def dictmerge(
    base: Optional[Dict[Any, Any]], patch: Optional[Dict[Any, Any]]
) -> Optional[Dict[Any, Any]]:
    """Apply ``patch`` to ``base`` the way the Device Shadow service does.

    Nested dicts are merged recursively and a ``None`` value deletes the key.
    This is the inverse of ``dictdiff``. Neither argument is modified.
    """
    if patch is None:
        return deepcopy(base)

    dst = deepcopy(base) if base else dict()
    for k, v in patch.items():
        if v is None:
            dst.pop(k, None)
        elif isinstance(v, dict):
            current = dst.get(k)
            dst[k] = dictmerge(current if isinstance(current, dict) else None, v)
        else:
            dst[k] = deepcopy(v)

    return dst
