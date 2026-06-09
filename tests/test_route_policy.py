"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""

"""
Unit tests for app.core.route_policy.

Covers the numeric coercers, the strict load/validate routine (every
fail-fast branch), and the case-insensitive get_route_policy fallback. The
loader's file path is monkeypatched to a temp file so tests never touch the
real route_policy.json.
"""

import json

import pytest
from app.core import route_policy as RP

# --- _coerce_float / _coerce_int ------------------------------------------


def test_coerce_float_ok_and_error():
    assert RP._coerce_float("1.5", field="f", route="OTHER") == 1.5
    with pytest.raises(ValueError, match="not a float"):
        RP._coerce_float("abc", field="f", route="OTHER")


def test_coerce_int_accepts_int_integral_float_and_string():
    assert RP._coerce_int(3, field="f", route="OTHER") == 3
    assert RP._coerce_int(4.0, field="f", route="OTHER") == 4
    assert RP._coerce_int("5", field="f", route="OTHER") == 5


def test_coerce_int_rejects_bool():
    with pytest.raises(ValueError, match="not an int"):
        RP._coerce_int(True, field="f", route="OTHER")


def test_coerce_int_rejects_fractional():
    with pytest.raises(ValueError, match="not an int"):
        RP._coerce_int(2.5, field="f", route="OTHER")


def test_coerce_int_rejects_non_numeric():
    with pytest.raises(ValueError, match="not an int"):
        RP._coerce_int("nope", field="f", route="OTHER")


# --- load_and_validate_route_policy ---------------------------------------


def _route_block(rm=1.0, mk=5, min_score=0.1, mb=1, ma=1):
    return {
        "retrieval_multiplier": rm,
        "max_keep": mk,
        "min_score": min_score,
        "expansion": {"max_before": mb, "max_after": ma},
    }


def _full_policy():
    return {route: _route_block() for route in RP.EXPECTED_ROUTES}


def _write_policy(tmp_path, monkeypatch, obj):
    path = tmp_path / "route_policy.json"
    if isinstance(obj, str):
        path.write_text(obj, encoding="utf-8")
    else:
        path.write_text(json.dumps(obj), encoding="utf-8")
    monkeypatch.setattr(RP, "_policy_path", lambda: str(path))
    return path


def test_load_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(RP, "_policy_path", lambda: str(tmp_path / "absent.json"))
    with pytest.raises(FileNotFoundError):
        RP.load_and_validate_route_policy()


def test_load_non_object_raises(tmp_path, monkeypatch):
    _write_policy(tmp_path, monkeypatch, "[]")
    with pytest.raises(ValueError, match="must be a JSON object"):
        RP.load_and_validate_route_policy()


def test_load_missing_route_block_raises(tmp_path, monkeypatch):
    _write_policy(tmp_path, monkeypatch, {})
    with pytest.raises(ValueError, match="missing/invalid route block"):
        RP.load_and_validate_route_policy()


def test_load_missing_required_keys_raises(tmp_path, monkeypatch):
    policy = _full_policy()
    del policy["CHITCHAT"]["min_score"]
    _write_policy(tmp_path, monkeypatch, policy)
    with pytest.raises(ValueError, match="missing retrieval_multiplier/max_keep/min_score"):
        RP.load_and_validate_route_policy()


def test_load_missing_expansion_block_raises(tmp_path, monkeypatch):
    policy = _full_policy()
    del policy["CHITCHAT"]["expansion"]
    _write_policy(tmp_path, monkeypatch, policy)
    with pytest.raises(ValueError, match="missing/invalid expansion block"):
        RP.load_and_validate_route_policy()


def test_load_negative_retrieval_multiplier_raises(tmp_path, monkeypatch):
    policy = _full_policy()
    policy["DIRECT"]["retrieval_multiplier"] = -1.0
    _write_policy(tmp_path, monkeypatch, policy)
    with pytest.raises(ValueError, match="retrieval_multiplier: must be >= 0"):
        RP.load_and_validate_route_policy()


def test_load_negative_max_keep_raises(tmp_path, monkeypatch):
    policy = _full_policy()
    policy["DIRECT"]["max_keep"] = -3
    _write_policy(tmp_path, monkeypatch, policy)
    with pytest.raises(ValueError, match="max_keep: must be >= 0"):
        RP.load_and_validate_route_policy()


def test_load_out_of_range_min_score_raises(tmp_path, monkeypatch):
    policy = _full_policy()
    policy["DIRECT"]["min_score"] = 1.5
    _write_policy(tmp_path, monkeypatch, policy)
    with pytest.raises(ValueError, match="min_score: must be between 0 and 1"):
        RP.load_and_validate_route_policy()


def test_load_negative_expansion_before_raises(tmp_path, monkeypatch):
    policy = _full_policy()
    policy["DIRECT"]["expansion"]["max_before"] = -1
    _write_policy(tmp_path, monkeypatch, policy)
    with pytest.raises(ValueError, match="expansion.max_before: must be >= 0"):
        RP.load_and_validate_route_policy()


def test_load_negative_expansion_after_raises(tmp_path, monkeypatch):
    policy = _full_policy()
    policy["DIRECT"]["expansion"]["max_after"] = -1
    _write_policy(tmp_path, monkeypatch, policy)
    with pytest.raises(ValueError, match="expansion.max_after: must be >= 0"):
        RP.load_and_validate_route_policy()


def test_load_valid_policy_returns_all_routes(tmp_path, monkeypatch):
    _write_policy(tmp_path, monkeypatch, _full_policy())
    out = RP.load_and_validate_route_policy()
    assert set(out.keys()) == set(RP.EXPECTED_ROUTES)
    assert out["OTHER"].retrieval_multiplier == 1.0


# --- get_route_policy -----------------------------------------------------


def test_get_route_policy_known_and_fallback():
    direct = RP.get_route_policy("direct")  # case-insensitive
    assert isinstance(direct, RP.RoutePolicy)
    # Unknown routes fall back to the OTHER policy.
    assert RP.get_route_policy("nonexistent-route") is RP._POLICY["OTHER"]
    assert RP.get_route_policy("") is RP._POLICY["OTHER"]
