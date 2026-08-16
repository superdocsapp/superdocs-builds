import asyncio
from pathlib import Path
from fastapi import UploadFile
from app.services.report_intake import create_report
from app.services.report_pipeline import process_report


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

    # We are testing the pipeline without uploaded photos first.
    intake = await create_report(
        notes=notes,
        photos=[],
    )

    print("Intake:")
    print(intake)

    report_id = intake["report_id"]
    report_dir = Path(intake["report_dir"])

    result = await process_report(
        report_id=report_id,
        report_dir=report_dir,
        notes=notes,
        photo_filenames=intake["photos"],
    )

    print("\nPipeline result:")
    print(result)

    html_path = Path(result["html_path"])

    print("\nGenerated HTML exists:")
    print(html_path.exists())


if __name__ == "__main__":
    asyncio.run(main())