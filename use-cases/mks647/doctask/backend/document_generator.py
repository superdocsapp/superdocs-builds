from pathlib import Path


BASE_DIR = Path(__file__).parent.parent

TEMPLATES_DIR = BASE_DIR / "templates"
GENERATED_DIR = BASE_DIR / "generated"


DOCUMENTS = [
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "MAINTAINERS.md",
    "CLA.md",
    "RELEASE_POLICY.md",
]


def generate_documents(project):
    """
    Generate governance documents from Markdown templates.
    """

    # Create generated folder if it does not exist
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    replacements = {
        "{{PROJECT_NAME}}": project.name,
        "{{LICENSE}}": project.license,
        "{{GOVERNANCE_MODEL}}": project.governance_model,
        "{{CONTACT_EMAIL}}": project.contact_email,
    }

    generated_documents = []

    for filename in DOCUMENTS:

        # Read template
        template_path = TEMPLATES_DIR / filename

        template_content = template_path.read_text(
            encoding="utf-8"
        )

        # Replace placeholders
        content = template_content

        for placeholder, value in replacements.items():
            content = content.replace(
                placeholder,
                value
            )

        # Save generated file
        output_path = GENERATED_DIR / filename

        output_path.write_text(
            content,
            encoding="utf-8"
        )

        generated_documents.append({
            "filename": filename,
            "content": content
        })

    return generated_documents