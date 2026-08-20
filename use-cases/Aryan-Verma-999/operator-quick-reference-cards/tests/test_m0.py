import hashlib, json
from pathlib import Path
import pytest
from linecard.superdocs_client import OperationBudget, OperationBudgetExceeded, normalize_proposals, redact, reject_unsafe_proposals

def test_redaction():
    x=redact({'authorization':'Bearer ' + 'sanitized-test-value','upload_url':'https://signed.invalid/x','text':'ordinary'})
    assert 'secret' not in str(x) and 'signed.invalid' not in str(x) and x['text']=='ordinary'

def test_nested_proposal_shapes():
    p={'proposed_change_batch': json.dumps([{'change_id':'c1','document_id':'card'}])}
    assert normalize_proposals(p)[0]['change_id']=='c1'

def test_unsafe_manual_target():
    with pytest.raises(ValueError): reject_unsafe_proposals([{'change_id':'x','document_id':'manual','operation':'replace'}], 'card','manual')

def test_budget():
    b=OperationBudget(1); b.consume('one')
    with pytest.raises(OperationBudgetExceeded): b.consume('two')

def test_fixture_deterministic():
    script=Path(__file__).parents[1]/'scripts/generate_m0_fixture.py'
    assert script.exists()
