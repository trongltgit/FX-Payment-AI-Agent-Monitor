"""
CN Margin + NSDH store theo CIF
- margin CN: không vượt trần HQ (max_branch_margin)
- nsdh_points: điểm điều hòa CN set (0 = không dùng TGDH)
- Dùng cho KH online (preset) và offline (CN báo giá)
"""
from threading import Lock
from copy import deepcopy
from typing import Any, Dict, List, Optional

_lock = Lock()
# key: (customer_id, currency, side)
_PRESETS: Dict[tuple, Dict[str, Any]] = {}


def set_preset(
    customer_id,
    currency,
    side,
    margin,
    nsdh_points=0,
    use_nsdh=False,
    amount_min=0,
    amount_max=None,
):
    currency = str(currency).upper()
    side = str(side).upper()
    key = (customer_id, currency, side)
    with _lock:
        _PRESETS[key] = {
            "margin": str(margin),
            "nsdh_points": str(nsdh_points or 0),
            "use_nsdh": bool(use_nsdh) and float(nsdh_points or 0) != 0,
            "amount_min": float(amount_min or 0),
            "amount_max": float(amount_max) if amount_max is not None else None,
            "customer_id": customer_id,
            "currency": currency,
            "side": side,
        }
        return deepcopy(_PRESETS[key])


def get_preset(customer_id, currency, side, amount=None):
    currency = str(currency).upper()
    side = str(side).upper()
    key = (customer_id, currency, side)
    with _lock:
        p = _PRESETS.get(key)
        if not p:
            return None
        if amount is not None:
            a = float(amount)
            if a < p["amount_min"]:
                return None
            if p["amount_max"] is not None and a > p["amount_max"]:
                return None
        return deepcopy(p)


def list_presets_for_customers(customer_ids):
    ids = set(customer_ids or [])
    with _lock:
        return [deepcopy(v) for k, v in _PRESETS.items() if k[0] in ids]


def list_all_presets():
    with _lock:
        return [deepcopy(v) for v in _PRESETS.values()]


def delete_preset(customer_id, currency, side):
    currency = str(currency).upper()
    side = str(side).upper()
    key = (customer_id, currency, side)
    with _lock:
        return _PRESETS.pop(key, None) is not None
