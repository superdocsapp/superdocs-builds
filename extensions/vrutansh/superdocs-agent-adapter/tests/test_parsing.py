import json

import pytest

from superdocs_adapter.errors import InvalidResponseError
from superdocs_adapter.models import JobStatus
from superdocs_adapter.parsing import parse_job


def test_proposed_change_content_gets_documented_second_parse() -> None:
    content = {"before": "Old", "after": "New"}
    job = parse_job(
        {
            "job_id": "job-1",
            "session_id": "session-1",
            "status": "awaiting_approval",
            "progress": 70,
            "metadata": {
                "pending_changes": [
                    {
                        "change_id": "change-1",
                        "chunk_id": "chunk-1",
                        "content": json.dumps(content),
                    }
                ]
            },
        }
    )

    assert job.status is JobStatus.AWAITING_APPROVAL
    assert job.proposed_changes[0].content == content


def test_final_result_remains_an_object() -> None:
    result = {"response": "done", "document_html": "<p>Updated</p>"}
    job = parse_job(
        {
            "job_id": "job-1",
            "session_id": "session-1",
            "status": "completed",
            "progress": 100,
            "result": result,
        }
    )
    assert job.result == result


def test_unknown_job_status_is_rejected() -> None:
    with pytest.raises(InvalidResponseError, match="Unknown job status"):
        parse_job(
            {
                "job_id": "job-1",
                "session_id": "session-1",
                "status": "mystery",
            }
        )
