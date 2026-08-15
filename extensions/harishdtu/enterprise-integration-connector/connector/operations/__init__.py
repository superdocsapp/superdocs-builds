from connector.operations.edit_by_instruction import edit_by_instruction
from connector.operations.export_document import export_document
from connector.operations.generate_from_template import generate_from_template
from connector.operations.poll_for_completion import poll_for_completion
from connector.operations.submit_for_approval import submit_for_approval
from connector.operations.upload_document import upload_document

__all__ = [
    "generate_from_template",
    "edit_by_instruction",
    "submit_for_approval",
    "poll_for_completion",
    "export_document",
    "upload_document",
]
