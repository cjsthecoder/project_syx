"""
Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.

This source code is part of the Syx project and is proprietary.

Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.

Use of this software requires explicit written permission from the copyright holder.
"""
"""
Route policy loader and validator.

Strict, fail-fast semantics:
- route_policy.json is required and validated on startup.
- policy is cached for process lifetime (reload on restart only).
"""


import json
import os
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class RoutePolicy:
    retrieval_multiplier: float
    max_keep: int
    min_score: float
    expansion_max_before: int
    expansion_max_after: int


EXPECTED_ROUTES = ("CHITCHAT", "DIRECT", "PROCEDURAL", "EXPLORATORY", "SYNTHESIS", "OTHER")


def _policy_path() -> str:
    base_dir = os.path.join(os.path.dirname(__file__), "..", "config")
    return os.path.abspath(os.path.join(base_dir, "route_policy.json"))


def _coerce_float(v: Any, *, field: str, route: str) -> float:
    try:
        return float(v)
    except Exception as e:
        raise ValueError(f"route_policy invalid {route}.{field}: not a float ({v!r})") from e


def _coerce_int(v: Any, *, field: str, route: str) -> int:
    # Accept ints and integral floats/strings, but reject fractional.
    try:
        if isinstance(v, bool):
            raise ValueError("bool not allowed")
        if isinstance(v, int):
            return int(v)
        fv = float(v)
        iv = int(fv)
        if abs(fv - iv) > 1e-9:
            raise ValueError("fractional value")
        return iv
    except Exception as e:
        raise ValueError(f"route_policy invalid {route}.{field}: not an int ({v!r})") from e


def load_and_validate_route_policy() -> Dict[str, RoutePolicy]:
    """
    Load backend/app/config/route_policy.json and validate expected routes.
    Raises ValueError/FileNotFoundError on invalid/missing policy (fail-fast).
    """
    path = _policy_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"route_policy.json missing at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("route_policy.json must be a JSON object")

    out: Dict[str, RoutePolicy] = {}
    for r in EXPECTED_ROUTES:
        node = data.get(r)
        if not isinstance(node, dict):
            raise ValueError(f"route_policy missing/invalid route block: {r}")
        if "retrieval_multiplier" not in node or "max_keep" not in node or "min_score" not in node:
            raise ValueError(f"route_policy route {r} missing retrieval_multiplier/max_keep/min_score")
        if "expansion" not in node or not isinstance(node.get("expansion"), dict):
            raise ValueError(f"route_policy route {r} missing/invalid expansion block")
        rm = _coerce_float(node.get("retrieval_multiplier"), field="retrieval_multiplier", route=r)
        mk = _coerce_int(node.get("max_keep"), field="max_keep", route=r)
        min_score = _coerce_float(node.get("min_score"), field="min_score", route=r)
        exp = node.get("expansion") if isinstance(node.get("expansion"), dict) else {}
        mb = _coerce_int(exp.get("max_before"), field="expansion.max_before", route=r)
        ma = _coerce_int(exp.get("max_after"), field="expansion.max_after", route=r)
        if rm < 0.0:
            raise ValueError(f"route_policy invalid {r}.retrieval_multiplier: must be >= 0")
        if mk < 0:
            raise ValueError(f"route_policy invalid {r}.max_keep: must be >= 0")
        if min_score < 0.0 or min_score > 1.0:
            raise ValueError(f"route_policy invalid {r}.min_score: must be between 0 and 1")
        if mb < 0:
            raise ValueError(f"route_policy invalid {r}.expansion.max_before: must be >= 0")
        if ma < 0:
            raise ValueError(f"route_policy invalid {r}.expansion.max_after: must be >= 0")
        out[r] = RoutePolicy(
            retrieval_multiplier=rm,
            max_keep=mk,
            min_score=min_score,
            expansion_max_before=mb,
            expansion_max_after=ma,
        )

    return out


# Strict, process-lifetime cache (reload on restart only)
_POLICY: Dict[str, RoutePolicy] = load_and_validate_route_policy()


def get_route_policy(route: str) -> RoutePolicy:
    """Return policy for route; unknown routes fall back to OTHER (stable compat)."""
    r = (route or "").strip().upper()
    if r in _POLICY:
        return _POLICY[r]
    return _POLICY["OTHER"]

