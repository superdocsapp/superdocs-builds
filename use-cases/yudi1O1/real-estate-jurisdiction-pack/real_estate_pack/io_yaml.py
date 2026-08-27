"""Load a `LeasePackRequest` from a YAML file.

Strict about unknown keys, on purpose. A coordinator who writes `year_build`
instead of `year_built` has, in a permissive loader, silently created a property
with no construction year — which then blocks with a confusing message about
lead paint applicability, or worse, in a two-state engine, quietly drops the
federal lead disclosure. Rejecting the unknown key names the typo at the point
it was made.

`disclosure_facts` is the deliberate exception: its keys are open by design,
because they are whatever the jurisdiction files ask about. A misspelled fact
there is caught by the validator instead, which reports the fact it needed and
did not get.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import LeasePackRequest, Party, Property, Tenancy

_PROPERTY_KEYS = {f for f in Property.__dataclass_fields__}
_TENANCY_KEYS = {f for f in Tenancy.__dataclass_fields__}
_PARTY_KEYS = {f for f in Party.__dataclass_fields__}
_TOP_KEYS = {"pack_id", "jurisdiction", "property", "tenancy", "landlord", "tenants", "agent", "disclosure_facts"}


class InputError(ValueError):
    """A lease record that cannot be loaded. Always names the file and the key."""


def _check_keys(mapping: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise InputError(
            f"{where}: unknown key(s) {unknown}. Allowed here: {sorted(allowed)}. "
            f"Fix: correct the spelling, or move a jurisdiction-specific answer into 'disclosure_facts'."
        )


def _party(raw: Any, role: str, where: str) -> Party:
    if isinstance(raw, str):
        return Party(name=raw, role=role)
    if not isinstance(raw, dict):
        raise InputError(f"{where}: expected a name or a mapping, got {type(raw).__name__}.")
    data = {k: v for k, v in raw.items() if k != "role"}
    _check_keys(data, _PARTY_KEYS - {"role"}, where)
    return Party(role=role, **{k: str(v) for k, v in data.items()})


def load_request(path: str | Path) -> LeasePackRequest:
    path = Path(path)
    where = path.name
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise InputError(f"No input file at {path}.") from e
    except yaml.YAMLError as e:
        raise InputError(f"{where}: not valid YAML — {e}") from e

    if not isinstance(raw, dict):
        raise InputError(f"{where}: top level must be a mapping.")
    _check_keys(raw, _TOP_KEYS, where)

    for required in ("pack_id", "jurisdiction", "property", "tenancy", "landlord"):
        if required not in raw:
            raise InputError(f"{where}: missing required top-level key '{required}'.")

    prop_raw = raw["property"]
    if not isinstance(prop_raw, dict):
        raise InputError(f"{where}: 'property' must be a mapping.")
    _check_keys(prop_raw, _PROPERTY_KEYS, f"{where} -> property")
    for required in ("street_address", "city", "state", "postal_code"):
        if required not in prop_raw:
            raise InputError(f"{where} -> property: missing required key '{required}'.")

    tenancy_raw = raw["tenancy"]
    if not isinstance(tenancy_raw, dict):
        raise InputError(f"{where}: 'tenancy' must be a mapping.")
    _check_keys(tenancy_raw, _TENANCY_KEYS, f"{where} -> tenancy")
    for required in ("start_date", "end_date", "monthly_rent", "security_deposit"):
        if required not in tenancy_raw:
            raise InputError(f"{where} -> tenancy: missing required key '{required}'.")

    tenants_raw = raw.get("tenants") or []
    if not isinstance(tenants_raw, list):
        raise InputError(f"{where}: 'tenants' must be a list.")

    facts = raw.get("disclosure_facts") or {}
    if not isinstance(facts, dict):
        raise InputError(f"{where}: 'disclosure_facts' must be a mapping of fact name to answer.")

    try:
        prop = Property(
            **{
                k: (str(v) if k in ("street_address", "city", "state", "postal_code", "unit", "property_type", "county") else v)
                for k, v in prop_raw.items()
            }
        )
        tenancy = Tenancy(
            **{
                **{k: v for k, v in tenancy_raw.items()},
                "start_date": str(tenancy_raw["start_date"]),
                "end_date": str(tenancy_raw["end_date"]),
                "monthly_rent": float(tenancy_raw["monthly_rent"]),
                "security_deposit": float(tenancy_raw["security_deposit"]),
            }
        )
    except (TypeError, ValueError) as e:
        raise InputError(f"{where}: could not build the record — {e}") from e

    return LeasePackRequest(
        pack_id=str(raw["pack_id"]),
        jurisdiction=str(raw["jurisdiction"]).upper(),
        property=prop,
        tenancy=tenancy,
        landlord=_party(raw["landlord"], "landlord", f"{where} -> landlord"),
        tenants=[_party(t, "tenant", f"{where} -> tenants[{i}]") for i, t in enumerate(tenants_raw)],
        agent=_party(raw["agent"], "agent", f"{where} -> agent") if raw.get("agent") else None,
        disclosure_facts=dict(facts),
    )
