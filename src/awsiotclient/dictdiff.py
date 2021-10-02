#!/usr/bin/env python3
from typing import Any, Dict, Optional

from . import get_module_logger

logger = get_module_logger(__name__)


def dictdiff(s1: Optional[Dict[Any, Any]], s2: Optional[Dict[Any, Any]]) -> Optional[Dict[Any, Any]]:
    if not s2 or s1 == s2:
        return None
    if not s1:
        return s2  # s1 is empty.

    dst = dict()
    for k in s1.keys() | s2.keys():
        v1 = s1.get(k)
        v2 = s2.get(k)
        if v1 == v2:
            continue  # Not changed
        if v1 is None:
            logger.debug(f"Added Item ({k})  : None -> {v2}")
            dst[k] = v2  # Added Item
            continue
        if v2 is None:
            logger.debug(f"Removed Item ({k}): {v1} -> None")
            dst[k] = None  # Removed Item
            continue
        if type(v1) != type(v2):
            dst[k] = v2  # Type changed. Override.
            continue

        # here, v1 != v2 and type(v1) == type(v2)
        if isinstance(v1, dict):
            dst[k] = dictdiff(v1, v2)
        else:
            logger.debug(f"Updated Item ({k}): {v1} -> {v2}")
            dst[k] = v2  # Updated item

    return dst
