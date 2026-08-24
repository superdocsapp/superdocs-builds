from models import Release

def get_mock_releases():
    return [
        Release(
            version="v2.1.0",
            date="2023-09-01",
            added=["Initial support for document viewing"],
            fixed=["Fixed rendering of large tables"]
        ),
        Release(
            version="v2.2.0",
            date="2023-10-15",
            fixed=["Resolved an issue where documents would not load on Safari",
                   "Fixed a memory leak during prolonged editing sessions"],
            improved=["Enhanced loading speeds by 20%"]
        ),
        Release(
            version="v2.3.0",
            date="2023-11-20",
            added=["Added PDF export capabilities", "New AI writing assistant preview"],
            improved=["UI improvements for mobile devices"]
        )
    ]

def get_latest_mock_release():
    return Release(
        version="v2.4.0",
        date="2023-12-10",
        added=[
            "Added document export improvements",
            "Added human approval for AI edits"
        ],
        improved=[
            "Improved multilingual document generation"
        ],
        fixed=[
            "Fixed an issue with image handling"
        ]
    )
