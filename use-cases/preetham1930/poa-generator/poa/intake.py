"""The guided intake: who, which type, which powers.

Non-interactive by construction. An intake is a JSON file, so a test and a demo
drive exactly the same code path a person filling the form would - there is no
second, easier route into the assembler that only the tests use.

The intake is the **only** channel by which a power reaches the document. That
is the structural half of INVARIANTS.md A6, and it is the same argument as
Decision 13 in `system/`: the defence against a fabricated power is not a check
on the output, it is that there is no path for one to arrive through. The
assembler takes power ids, resolves them against the catalogue, and has no way
to accept a power the catalogue does not hold.

Every refusal below is a hard error naming what is missing. A limited power of
attorney with no stated limit is not drafted around, and a missing successor
agent is not quietly omitted - the card names the successor-agent clause, and a
clause that is sometimes there is worse than one that is always there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .errors import (
    IncompleteIntakeError,
    UnknownJurisdictionError,
    UnknownPoaTypeError,
    UnknownPowerError,
)
from .library import Library

REQUIRED_PARTIES = ("principal", "agent", "successor_agent")


@dataclass(frozen=True)
class Party:
    name: str
    address: str
    identifier: str = ""


@dataclass(frozen=True)
class Intake:
    intake_id: str
    poa_type: str
    jurisdiction: str
    principal: Party
    agent: Party
    successor_agent: Party
    granted_powers: tuple[str, ...]
    effective_date: str
    limitation: str = ""
    real_property_description: str = ""

    def categories(self, library: Library) -> tuple[str, ...]:
        """The granted categories, in the library's own category order.

        Ordered by the catalogue rather than by the order the ids happened to be
        typed in, so two intakes that grant the same powers produce the same
        document whatever order the form was filled in.
        """
        granted = {library.powers[p].category for p in self.granted_powers}
        return tuple(c for c in library.category_order if c in granted)

    def powers_in(self, library: Library, category: str) -> tuple[str, ...]:
        return tuple(
            p
            for p in library.power_order
            if p in self.granted_powers and library.powers[p].category == category
        )


def load_intake(path: Path, library: Library) -> Intake:
    raw = json.loads(path.read_text(encoding="utf-8"))
    intake = Intake(
        intake_id=str(raw.get("intake_id") or path.stem),
        poa_type=str(raw.get("poa_type") or ""),
        jurisdiction=str(raw.get("jurisdiction") or ""),
        principal=_party(raw, "principal", path),
        agent=_party(raw, "agent", path),
        successor_agent=_party(raw, "successor_agent", path),
        granted_powers=tuple(raw.get("granted_powers") or ()),
        effective_date=str(raw.get("effective_date") or "").strip(),
        limitation=str(raw.get("limitation") or "").strip(),
        real_property_description=str(raw.get("real_property_description") or "").strip(),
    )
    validate(intake, library, source=path)
    return intake


def _party(raw: dict, key: str, path: Path) -> Party:
    block = raw.get(key)
    if not isinstance(block, dict):
        raise IncompleteIntakeError(
            f"the intake at {path} has no '{key}' block. A power of attorney names three "
            f"parties - {', '.join(REQUIRED_PARTIES)} - and this build refuses to draft one "
            f"that names fewer. The successor-agent clause is not optional."
        )
    return Party(
        name=str(block.get("name") or "").strip(),
        address=str(block.get("address") or "").strip(),
        identifier=str(block.get("identifier") or "").strip(),
    )


def validate(intake: Intake, library: Library, source: Path | None = None) -> None:
    where = f" (from {source})" if source else ""

    if intake.poa_type not in library.types:
        raise UnknownPoaTypeError(
            f"the intake{where} asks for POA type {intake.poa_type!r}. The library defines "
            f"{sorted(library.types)}. A type this build does not know is never approximated to "
            f"the nearest one it does: the general/limited/durable distinction is the thing the "
            f"card says people need to get right."
        )
    if intake.jurisdiction not in library.jurisdictions:
        raise UnknownJurisdictionError(
            f"the intake{where} names jurisdiction {intake.jurisdiction!r}. The library defines "
            f"{sorted(library.jurisdictions)}. Adding one is a row in config/jurisdictions.csv, "
            f"not a code change."
        )

    for key in REQUIRED_PARTIES:
        party: Party = getattr(intake, key)
        if not party.name or not party.address:
            raise IncompleteIntakeError(
                f"the intake{where} gives the {key.replace('_', ' ')} "
                f"name={party.name!r} address={party.address!r}. Both are required: an "
                f"instrument that cannot say who it appoints is not a draft, it is a gap."
            )

    if not intake.granted_powers:
        raise IncompleteIntakeError(
            f"the intake{where} grants no powers. A power of attorney granting nothing is not a "
            f"shorter document, it is a wrong one."
        )
    unknown = [p for p in intake.granted_powers if p not in library.powers]
    if unknown:
        raise UnknownPowerError(
            f"the intake{where} grants {unknown}, which the catalogue does not have. The "
            f"catalogue is config/powers.csv and holds {len(library.powers)} power(s) across "
            f"{list(library.category_order)}. An unknown power is never dropped and never "
            f"approximated - a power nobody granted is the exact failure this build is built "
            f"against."
        )
    duplicated = sorted({p for p in intake.granted_powers if intake.granted_powers.count(p) > 1})
    if duplicated:
        raise IncompleteIntakeError(
            f"the intake{where} lists {duplicated} more than once. A power granted twice would "
            f"be stated twice in the instrument."
        )

    if not intake.effective_date:
        raise IncompleteIntakeError(
            f"the intake{where} does not say when the authority commences. A power of attorney "
            f"with no commencement is a question, not a draft."
        )

    poa_type = library.types[intake.poa_type]
    if poa_type.requires_limitation and not intake.limitation:
        raise IncompleteIntakeError(
            f"the intake{where} asks for {poa_type.label} and states no limitation. "
            f"config/poa-types.csv marks this type requires_limitation=yes. A limited power of "
            f"attorney whose limit is blank is a general one wearing the wrong heading, which is "
            f"the single most consequential thing this build could get wrong."
        )
    if not poa_type.requires_limitation and intake.limitation:
        raise IncompleteIntakeError(
            f"the intake{where} states a limitation but asks for {poa_type.label}, which carries "
            f"no clause to put it in. The limitation would be silently dropped, and a granted "
            f"power that was meant to be limited and is not is the worst direction to fail in."
        )

    real_property = "real_property"
    grants_real_property = real_property in intake.categories(library)
    if grants_real_property and not intake.real_property_description:
        raise IncompleteIntakeError(
            f"the intake{where} grants real property powers and describes no property. The "
            f"clause that names the property has nothing to name, and a real property power over "
            f"an unnamed property is unbounded."
        )
    if not grants_real_property and intake.real_property_description:
        raise IncompleteIntakeError(
            f"the intake{where} describes a property but grants no real property power, so the "
            f"description has no clause to appear in and would be silently dropped."
        )
