import pytest
from pydantic import SecretStr
from series_bible.infrastructure.superdocs_service import EditInstructionRequest, SuperDocsConnection, SuperDocsService, UploadDocumentRequest

class RecordingService(SuperDocsService):
    def __init__(self):
        super().__init__(SuperDocsConnection(mcp_api_key=SecretStr("test-only")))
        self.calls=[]
    async def _call_tool(self,name,arguments):
        self.calls.append((name,arguments));return {"ok":True}

@pytest.mark.asyncio
async def test_edit_always_requires_human_approval():
    service=RecordingService()
    await service.send_edit_instruction(EditInstructionRequest(session_id="session-1",message="Change green to blue."))
    assert service.calls == [("chat_async", {"session_id":"session-1","message":"Change green to blue.","response_mode":"compact","approval_mode":"ask_every_time"})]

@pytest.mark.asyncio
async def test_upload_uses_live_wire_tool_name():
    service=RecordingService()
    await service.upload_document(UploadDocumentRequest(filename="chapter.md",file_base64="YQ=="))
    assert service.calls[0][0] == "upload_document_base64"

@pytest.mark.asyncio
async def test_job_polling_uses_real_get_job_tool_and_requires_change_id():
    service=RecordingService()
    async def call(name, arguments):
        service.calls.append((name, arguments))
        return {"status":"awaiting_approval","pending_changes":[{"change_id":"change-1","before_html":"old","after_html":"new"}]}
    service._call_tool=call
    proposal=await service.wait_for_edit_proposal("job-1",poll_seconds=0.001)
    assert service.calls[0] == ("get_job", {"job_id":"job-1","compact":False})
    assert proposal.change_id == "change-1"
    assert proposal.proposed_html == "new"
