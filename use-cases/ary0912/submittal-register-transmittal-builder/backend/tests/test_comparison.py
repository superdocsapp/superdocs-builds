from app.services.comparison import compare_flooring


def test_flooring_deviation():

    specification = {
        "minimum_thickness": 3.0,
        "fire_performance": "Class A",
        "warranty_years": 10,
    }

    submission = {
        "thickness": 2.5,
        "fire_performance": "Class A",
        "warranty_years": 10,
    }

    findings = compare_flooring(
        specification,
        submission,
    )

    assert findings[0].result == "DEVIATION"
    assert findings[1].result == "MATCH"
    assert findings[2].result == "MATCH"