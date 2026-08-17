from __future__ import annotations

from superdocs_sdk import SuperDocsClient


def main() -> None:
    with SuperDocsClient.from_env() as client:
        result = client.chat(
            session_id="sdk-example",
            message="Add a concise executive summary.",
            document_html="<h1 data-chunk-id='title'>Talent Deal</h1><p data-chunk-id='body'>Maya will appear in one video.</p>",
            approval_mode="approve_all",
        )
        print(result.response)


if __name__ == "__main__":
    main()
