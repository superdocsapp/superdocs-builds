from app.utils.json_utils import coerce_truncated_json_object


def test_coerce_truncated_questions_array():
    frag = (
        '{ "questions": [ {"question": "Q1", "difficulty": "Easy", '
        '"expected_answer": "A", "resume_evidence": "No evidence found." '
    )
    data = coerce_truncated_json_object(frag)
    assert data is not None
    assert "questions" in data
    assert data["questions"][0]["question"] == "Q1"


def test_coerce_truncated_second_item():
    frag = (
        '{"questions":[{"question":"Q1","difficulty":"Easy","expected_answer":"A",'
        '"resume_evidence":"No evidence found.","missing_knowledge":[],'
        '"revision_links":[]},{"question":"Q2","difficulty":"Med'
    )
    data = coerce_truncated_json_object(frag)
    assert data is not None
    assert len(data["questions"]) >= 1
