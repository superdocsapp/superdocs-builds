import asyncio
import json

from app.services.report_extractor import extract_field_report


async def main() -> None:
    notes = """
    Project: Riverside Commercial Building

    18 workers were onsite today:
    8 concrete workers, 6 general laborers, and 4 electricians.

    Concrete was poured in Zone A and reinforcement work continued
    in Zone B.

    One excavator was onsite but was unavailable for two hours
    because of a hydraulic issue.

    Light rain started around 3 PM and slowed exterior work.

    The supervisor noted that workers were wearing required PPE.
    """

    report = await extract_field_report(
        report_id="extraction-test-001",
        notes=notes,
    )

    print(
        json.dumps(
            report.model_dump(mode="json"),
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())