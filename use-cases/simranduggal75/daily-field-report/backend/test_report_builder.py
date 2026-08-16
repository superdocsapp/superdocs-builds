import asyncio

from app.services.report_builder import build_daily_report_html
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
        report_id="builder-test-001",
        notes=notes,
    )

    html = build_daily_report_html(
        report=report,
    )

    with open(
        "sample_daily_report.html",
        "w",
        encoding="utf-8",
    ) as file:
        file.write(html)

    print("Daily report HTML generated successfully.")


if __name__ == "__main__":
    asyncio.run(main())