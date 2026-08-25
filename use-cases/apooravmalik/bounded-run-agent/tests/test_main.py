import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1])); from main import resource_context, run

class Fake:
 def __init__(self,fail=False,export=True):self.fail,self.export,self.instructions=fail,export,[]
 def upload(self,path,session):return {"persisted":True}
 def edit(self,s,i):self.instructions.append(i);return {"job_id":i}
 def job(self,j):return {"status":"failed"} if self.fail else {"status":"completed"}
 def wait(self,j):return self.job(j)
 def export(self,s,p):
  if not self.export:raise RuntimeError("export down")
  return p
class TestRun(unittest.TestCase):
 def test_full_completion(self):
  r=run(Fake(),"x","one; two",3,None,True,"x");self.assertEqual(r["status"],"COMPLETED");self.assertEqual(r["completed"],["T1","T2"])
 def test_budget_is_honest(self):
  r=run(Fake(),"x","one; two; three",2,None,True,"x");self.assertEqual(r["status"],"BUDGET_EXHAUSTED");self.assertEqual(r["not_completed"],["T3"])
 def test_failure_not_success(self):self.assertEqual(run(Fake(fail=True),"x","one",1,None,True,"x")["completed"],[])
 def test_export_is_separate(self):
  r=run(Fake(export=False),"x","one",1,None,True,"x");self.assertEqual(r["status"],"COMPLETED");self.assertIn("export_error",r)
 def test_deadline_stops_before_edit(self):
  times=iter([1,2,2]); r=run(Fake(),"x","one",1,0,True,"x",lambda:next(times));self.assertEqual(r["status"],"DEADLINE_EXCEEDED")
 def test_text_resource_is_included_in_edit_instruction(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory,"reference.txt");path.write_text("Use formal terminology.");client=Fake();run(client,"x","one",1,None,True,"x",resources=[str(path)])
   self.assertIn("Use formal terminology.",client.instructions[0]);self.assertEqual(resource_context([str(path)]).splitlines()[0],"Reference: reference.txt")
if __name__=="__main__":unittest.main()
