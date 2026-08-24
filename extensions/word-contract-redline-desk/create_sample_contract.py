from docx import Document

doc = Document()

doc.add_heading("SERVICE AGREEMENT", level=1)

doc.add_paragraph(
    "This Service Agreement is entered into between Acme Corporation "
    "and Example Client."
)

doc.add_heading("1. Confidentiality", level=2)
doc.add_paragraph(
    "Each party shall keep confidential all information received from "
    "the other party and shall not disclose such information to any "
    "third party without prior written consent."
)

doc.add_heading("2. Limitation of Liability", level=2)
doc.add_paragraph(
    "The liability of each party under this Agreement shall be unlimited."
)

doc.add_heading("3. Termination", level=2)
doc.add_paragraph(
    "Either party may terminate this Agreement by providing thirty "
    "days written notice to the other party."
)

doc.add_heading("4. Governing Law", level=2)
doc.add_paragraph(
    "This Agreement shall be governed by the laws of the State of New York."
)

doc.save("data/sample_contract.docx")

print("Sample contract created successfully.")