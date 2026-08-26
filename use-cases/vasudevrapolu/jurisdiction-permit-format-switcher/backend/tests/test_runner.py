import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.services.agent_runner import AgentRunner
from app.schemas.agent import SourceDocument, Rule, Decision
from app.models import AgentRun


def db_session():
    engine=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()

def test_runner_checkpoints_and_two_runs_have_isolated_state():
    db=db_session(); runner=AgentRunner(db)
    docs=[SourceDocument(name='a.txt',text='Project: A\nStatus: Ready')]
    rules=[Rule(id='r1',statement='Document must contain permit')]
    a=runner.start(docs,rules); b=runner.start([SourceDocument(name='b.txt',text='Project: B\nStatus: Ready')],[])
    runner.execute(a); runner.execute(b)
    assert a != b
    assert db.get(AgentRun,a).state_json != db.get(AgentRun,b).state_json

def test_runner_approval_closes_gate():
    db=db_session(); runner=AgentRunner(db)
    run=runner.start([SourceDocument(name='a.txt',text='Project: A')],[Rule(id='r1',statement='Document must contain permit')])
    state=runner.execute(run)
    assert db.get(AgentRun,run).status=='waiting_review'
    finding_id=state['findings'][0]['id']
    runner.approve(run,[Decision(id=finding_id,kind='finding',approved=True)])
    assert db.get(AgentRun,run).status=='completed'
