from pydantic import BaseModel
from typing import List, Optional

class Document(BaseModel):
    id: str
    filename: str
    status: str
    content: Optional[str] = None

class Job(BaseModel):
    id: str
    document_id: str
    status: str
    proposed_changes: Optional[List[dict]] = None
    cost: Optional[float] = 0.0

class Employee(BaseModel):
    employee_id: str
    name: str
    location: str
    union_status: str
    employment_type: str
    current_elections: List[str]

class ItemApproval(BaseModel):
    item_id: str
    status: str

class JobApprovalRequest(BaseModel):
    items: List[ItemApproval]

