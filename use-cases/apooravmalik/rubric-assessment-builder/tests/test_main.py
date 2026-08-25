import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1])); from main import Package, Question, RubricRow, build, load_template, publish, validate

class Fake:
 def __init__(self,export=True): self.export_ok=export
 def create(self,document,title): return {"session_id":"s","job_id":"j"}
 def wait(self,job_id): return {"status":"completed"}
 def export(self,session_id,path):
  if not self.export_ok: raise RuntimeError("export down")
  return path

class Tests(unittest.TestCase):
 def test_five_questions_align(self):
  p=build("Photosynthesis",5,25,"8");self.assertEqual(len(p.questions),5);self.assertEqual([r.question_id for r in p.rubric],["Q1","Q2","Q3","Q4","Q5"]);self.assertEqual(len({q.text for q in p.questions}),5)
 def test_missing_rubric_fails(self):
  p=build("Cells",5);p.rubric.pop();self.assertRaises(ValueError,validate,p)
 def test_duplicate_question_fails(self):
  p=build("Cells",2);p.questions[1].id="Q1";self.assertRaises(ValueError,validate,p)
 def test_mark_mismatch_fails(self):
  p=build("Cells",2);p.rubric[0].max_marks+=1;self.assertRaises(ValueError,validate,p)
 def test_publish_only_reports_export_after_artifact(self):
  self.assertTrue(publish(Fake(),build("Cells",2),True,"x")["exported"])
  self.assertEqual(publish(Fake(False),build("Cells",2),True,"x")["status"],"EXPORT_FAILED")
 def test_template_changes_question_shape(self):
  examples=Path(__file__).parents[1]/"examples";mixed=build("Photosynthesis",5,25,"8",load_template(str(examples/"mixed.json")));short=build("Photosynthesis",5,25,"8",load_template(str(examples/"short-answer.json")))
  self.assertNotEqual([q.question_type for q in mixed.questions],[q.question_type for q in short.questions]);self.assertEqual(mixed.template_name,"mixed-concept-assessment")
 def test_invalid_template_and_too_many_questions_fail(self):
  examples=Path(__file__).parents[1]/"examples";template=load_template(str(examples/"mixed.json"));self.assertRaises(ValueError,build,"Cells",6,6,None,template)
  with self.assertRaises(ValueError): load_template(str(examples/"invalid.json"))
if __name__=="__main__":unittest.main()
