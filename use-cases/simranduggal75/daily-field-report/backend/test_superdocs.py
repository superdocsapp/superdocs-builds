import asyncio

from app.services.superdocs_service import SuperDocsClient


async def main():
    client = SuperDocsClient()

    result = await client.chat(
        session_id="task2-test-session",
        message="Make the title more professional.",
        document_html="""
        <h1>Daily Field Report</h1>
        <p>18 workers were onsite today.</p>
        <p>Concrete work was completed in Zone A.</p>
        """,
    )

    print(result)


if __name__ == "__main__":
    asyncio.run(main())