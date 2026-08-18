"""Generator script for creating realistic sample M&A transaction documents for testing."""

import os
import pypdf
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import docx

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "executed_documents")


def generate_deal_corpus():
    """Generates 20+ realistic M&A files in PDF, DOCX, and TXT with messy filenames."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    styles = getSampleStyleSheet()

    def make_pdf(filename, title, body_paragraphs):
        path = os.path.join(OUTPUT_DIR, filename)
        doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54)
        story = [
            Paragraph(f"<b>{title}</b>", styles["Title"]),
            Spacer(1, 15),
        ]
        for p in body_paragraphs:
            story.append(Paragraph(p, styles["Normal"]))
            story.append(Spacer(1, 10))
        doc.build(story)
        return path

    def make_docx(filename, title, body_paragraphs):
        path = os.path.join(OUTPUT_DIR, filename)
        doc = docx.Document()
        doc.add_heading(title, level=1)
        for p in body_paragraphs:
            doc.add_paragraph(p)
        doc.save(path)
        return path

    def make_txt(filename, content):
        path = os.path.join(OUTPUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    # 1. Merger Agreement (Fully Executed with DocuSign)
    make_pdf(
        "Project_Titan_Merger_Agmt_Execution_FINAL_v4_signed.pdf",
        "AGREEMENT AND PLAN OF MERGER",
        [
            "DocuSign Envelope ID: 8A7B2C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D",
            "This AGREEMENT AND PLAN OF MERGER (this 'Agreement') is entered into as of August 18, 2026, by and among Apex Holdings LLC, a Delaware limited liability company ('Parent'), Titan Merger Sub Inc., a Delaware corporation ('Merger Sub'), and CloudScale Technologies, Inc., a Delaware corporation (the 'Company').",
            "WHEREAS, the parties intend to effect a merger of Merger Sub with and into the Company, with the Company surviving as a wholly-owned subsidiary of Parent for an aggregate merger consideration of $450,000,000.",
            "NOW, THEREFORE, the parties agree as follows: Section 1.01 The Merger. At the Effective Time, Merger Sub shall be merged with and into the Company.",
            "IN WITNESS WHEREOF, the parties hereto have caused this Agreement to be duly executed as of the date first written above.",
            "APEX HOLDINGS LLC<br/>By: /s/ Victoria Sterling<br/>Name: Victoria Sterling<br/>Title: Managing Director & CEO",
            "TITAN MERGER SUB INC.<br/>By: /s/ Marcus Vance<br/>Name: Marcus Vance<br/>Title: President",
            "CLOUDSCALE TECHNOLOGIES, INC.<br/>By: /s/ Dr. Alexander Vance<br/>Name: Dr. Alexander Vance<br/>Title: Chief Executive Officer",
        ]
    )

    # 2. Escrow Agreement (Unsigned Draft with Blank Line) -> agmt_clean_v2.docx
    make_docx(
        "agmt_clean_v2.docx",
        "ESCROW AGREEMENT",
        [
            "CONFIDENTIAL DRAFT - AUGUST 18, 2026",
            "This ESCROW AGREEMENT is made and entered into among Apex Holdings LLC ('Parent'), CloudScale Technologies, Inc. ('Company'), Stockholder Representative LLC ('Representative'), and Citibank, N.A. ('Escrow Agent').",
            "The Parent shall deposit $45,000,000 into the Indemnification Escrow Account to secure post-closing indemnification obligations under Section 8.02 of the Merger Agreement.",
            "IN WITNESS WHEREOF, the parties have executed this Escrow Agreement as of the date set forth above.",
            "APEX HOLDINGS LLC\nBy: _____________________\nName: [   ]\nTitle: Authorized Signatory",
            "CLOUDSCALE TECHNOLOGIES, INC.\nBy: _____________________\nName: Dr. Alexander Vance\nTitle: Chief Executive Officer",
            "CITIBANK, N.A.\nBy: _____________________\nName: [   ]\nTitle: Vice President & Trust Officer",
        ]
    )

    # 3. Paying Agent Agreement (Fully Signed) -> Scan_20260818_102.pdf
    make_pdf(
        "Scan_20260818_102.pdf",
        "PAYING AGENT AGREEMENT",
        [
            "This PAYING AGENT AGREEMENT is entered into as of August 18, 2026, by and between Apex Holdings LLC and Continental Stock Transfer & Trust Company.",
            "Parent hereby appoints Continental Stock Transfer & Trust Company as the Paying Agent for the distribution of $405,000,000 in closing cash consideration.",
            "IN WITNESS WHEREOF, the parties have executed this agreement.",
            "APEX HOLDINGS LLC<br/>By: /s/ Victoria Sterling<br/>Name: Victoria Sterling<br/>Title: CEO",
            "CONTINENTAL STOCK TRANSFER & TRUST COMPANY<br/>By: /s/ Robert J. Reynolds<br/>Name: Robert J. Reynolds<br/>Title: Managing Director",
        ]
    )

    # 4. Voting and Support Agreement (Partially Executed: Stockholder signed, Buyer blank) -> Titan_Voting_Agmt_partial.pdf
    make_pdf(
        "Titan_Voting_Agmt_partial.pdf",
        "VOTING AND SUPPORT AGREEMENT",
        [
            "This VOTING AND SUPPORT AGREEMENT is entered into as of August 18, 2026, between Apex Holdings LLC and Dr. Alexander Vance ('Stockholder').",
            "Stockholder agrees to vote all shares of Company Capital Stock owned by Stockholder in favor of the Merger and adoption of the Merger Agreement.",
            "IN WITNESS WHEREOF, the parties have caused this Agreement to be executed.",
            "STOCKHOLDER:<br/>By: /s/ Dr. Alexander Vance<br/>Dr. Alexander Vance (Founder & CEO)",
            "APEX HOLDINGS LLC:<br/>By: _______________________<br/>Name: [   ]<br/>Title: Managing Director",
        ]
    )

    # 5. Transition Services Agreement (Executed via DocuSign) -> TSA_Execution_Copy.docx
    make_docx(
        "TSA_Execution_Copy.docx",
        "TRANSITION SERVICES AGREEMENT",
        [
            "DocuSign Envelope ID: 9F8E7D6C-5B4A-3210-FEDC-BA9876543210",
            "This TRANSITION SERVICES AGREEMENT is made as of August 18, 2026, between Apex Holdings LLC and CloudScale Technologies, Inc.",
            "The Company shall provide transitional cloud infrastructure maintenance, security operations, and DevOps transition support for a term of 180 days.",
            "IN WITNESS WHEREOF, the parties have executed this Transition Services Agreement.",
            "APEX HOLDINGS LLC\nBy: /s/ Victoria Sterling\nName: Victoria Sterling\nTitle: CEO",
            "CLOUDSCALE TECHNOLOGIES, INC.\nBy: /s/ Dr. Alexander Vance\nName: Dr. Alexander Vance\nTitle: CEO",
        ]
    )

    # 6. IP Assignment Agreement (Fully Executed) -> IP_Assignment_Titan.pdf
    make_pdf(
        "IP_Assignment_Titan.pdf",
        "INTELLECTUAL PROPERTY ASSIGNMENT AGREEMENT",
        [
            "This INTELLECTUAL PROPERTY ASSIGNMENT AGREEMENT is made as of August 18, 2026, between CloudScale Technologies, Inc. and Apex Cloud Technologies LLC.",
            "Assignor hereby sells, assigns, transfers, and conveys to Assignee all right, title, and interest in and to the Registered Intellectual Property including US Patents 10,948,221 and 11,304,992.",
            "IN WITNESS WHEREOF, Assignor and Assignee have executed this Agreement.",
            "CLOUDSCALE TECHNOLOGIES, INC.<br/>By: /s/ Dr. Alexander Vance<br/>Name: Dr. Alexander Vance<br/>Title: Chief Executive Officer",
            "APEX CLOUD TECHNOLOGIES LLC<br/>By: /s/ Victoria Sterling<br/>Name: Victoria Sterling<br/>Title: Manager",
        ]
    )

    # 7. Non-Competition Agreement (Fully Signed) -> NonCompete_CEO_Signed.pdf
    make_pdf(
        "NonCompete_CEO_Signed.pdf",
        "NON-COMPETITION AND NON-SOLICITATION AGREEMENT",
        [
            "This NON-COMPETITION AND NON-SOLICITATION AGREEMENT is entered into as of August 18, 2026, by and between Apex Holdings LLC and Dr. Alexander Vance ('Executive').",
            "Executive agrees that for a period of 5 years following the Closing Date, Executive shall not engage in competing distributed cloud neural orchestration systems.",
            "IN WITNESS WHEREOF, the parties have executed this Agreement.",
            "APEX HOLDINGS LLC<br/>By: /s/ Victoria Sterling<br/>Name: Victoria Sterling<br/>Title: CEO",
            "EXECUTIVE:<br/>By: /s/ Dr. Alexander Vance<br/>Dr. Alexander Vance",
        ]
    )

    # 8. Certificate of Incorporation (Certified State Charter - Non Signature) -> Charter_Surviving_Corp.pdf
    make_pdf(
        "Charter_Surviving_Corp.pdf",
        "AMENDED AND RESTATED CERTIFICATE OF INCORPORATION OF CLOUDSCALE TECHNOLOGIES, INC.",
        [
            "STATE OF DELAWARE - SECRETARY OF STATE CERTIFIED CHARTER FILING",
            "ARTICLE I: The name of the corporation is CloudScale Technologies, Inc.",
            "ARTICLE II: The address of the registered office in the State of Delaware is 1209 Orange Street, Wilmington, New Castle County, DE 19801.",
            "ARTICLE III: The total number of shares of stock which the Corporation shall have authority to issue is 1,000 shares of Common Stock, par value $0.01 per share.",
            "FILED AND AUTHENTICATED UNDER THE GREAT SEAL OF THE STATE OF DELAWARE ON AUGUST 18, 2026.",
        ]
    )

    # 9. Delaware Articles of Merger -> Articles_of_Merger_DE.pdf
    make_pdf(
        "Articles_of_Merger_DE.pdf",
        "DELAWARE CERTIFICATE OF MERGER OF TITAN MERGER SUB INC. WITH AND INTO CLOUDSCALE TECHNOLOGIES, INC.",
        [
            "Pursuant to Section 251 of the Delaware General Corporation Law, the undersigned surviving corporation certifies that:",
            "1. The constituent corporations are Titan Merger Sub Inc. and CloudScale Technologies, Inc.",
            "2. An Agreement and Plan of Merger has been approved, adopted, executed and acknowledged by each of the constituent corporations.",
            "3. The surviving corporation is CloudScale Technologies, Inc.",
            "IN WITNESS WHEREOF, the surviving corporation has caused this Certificate of Merger to be executed by its authorized officer.",
            "CLOUDSCALE TECHNOLOGIES, INC.<br/>By: /s/ Victoria Sterling<br/>Name: Victoria Sterling<br/>Title: President",
        ]
    )

    # 10. Board Consent (Fully Signed) -> Board_Consent_Target.docx
    make_docx(
        "Board_Consent_Target.docx",
        "UNANIMOUS WRITTEN CONSENT OF THE BOARD OF DIRECTORS OF CLOUDSCALE TECHNOLOGIES, INC.",
        [
            "The undersigned, constituting all members of the Board of Directors of CloudScale Technologies, Inc., hereby unanimously adopt the following resolutions:",
            "RESOLVED, that the Merger and the Agreement and Plan of Merger by and among the Company, Apex Holdings LLC, and Titan Merger Sub Inc. be, and hereby are, approved and declared advisable.",
            "IN WITNESS WHEREOF, the undersigned directors have executed this Unanimous Written Consent.",
            "/s/ Dr. Alexander Vance - Director & CEO\n/s/ Elena Rostova - Director\n/s/ Sarah Jenkins - Director",
        ]
    )

    # 11. Stockholder Consent -> Stockholder_Consent_Signed.pdf
    make_pdf(
        "Stockholder_Consent_Signed.pdf",
        "WRITTEN CONSENT OF STOCKHOLDERS OF CLOUDSCALE TECHNOLOGIES, INC.",
        [
            "The undersigned stockholders representing 94.2% of the voting power of CloudScale Technologies, Inc. hereby consent in writing to the adoption of the Merger Agreement and the approval of the Merger.",
            "IN WITNESS WHEREOF, the undersigned have executed this Stockholder Written Consent.",
            "VANCE FAMILY TRUST (48.5%)<br/>By: /s/ Dr. Alexander Vance, Trustee",
            "SEQUOIA APEX VENTURES (32.1%)<br/>By: /s/ David Thorne, General Partner",
            "HORIZON CAPITAL PARTNERS (13.6%)<br/>By: /s/ Rachel Myers, Managing Director",
        ]
    )

    # 12. Good Standing Certificate -> scan_00192.pdf
    make_pdf(
        "scan_00192.pdf",
        "STATE OF DELAWARE - CERTIFICATE OF GOOD STANDING",
        [
            "I, JEFFREY W. BULLOCK, SECRETARY OF STATE OF THE STATE OF DELAWARE, DO HEREBY CERTIFY 'CLOUDSCALE TECHNOLOGIES, INC.' IS DULY INCORPORATED UNDER THE LAWS OF THE STATE OF DELAWARE AND IS IN GOOD STANDING AND HAS A LEGAL CORPORATE EXISTENCE SO FAR AS THE RECORDS OF THIS OFFICE SHOW, AS OF THE EIGHTEENTH DAY OF AUGUST, A.D. 2026.",
            "AUTHENTICATED UNDER THE GREAT SEAL OF THE STATE OF DELAWARE.",
        ]
    )

    # 13. FTC / DOJ HSR Notice -> HSR_Early_Termination_FTC.pdf
    make_pdf(
        "HSR_Early_Termination_FTC.pdf",
        "FEDERAL TRADE COMMISSION & DEPARTMENT OF JUSTICE - HSR EARLY TERMINATION NOTICE",
        [
            "TRANSACTION NUMBER: 2026-1492",
            "ACQUIRING PERSON: Apex Holdings LLC",
            "ACQUIRED PERSON: CloudScale Technologies, Inc.",
            "EARLY TERMINATION GRANTED: August 14, 2026.",
            "Notice is hereby given that the waiting period under the Hart-Scott-Rodino Antitrust Improvements Act has been granted early termination.",
        ]
    )

    # 14. Landlord Consent -> Landlord_Consent_SF_HQ.pdf
    make_pdf(
        "Landlord_Consent_SF_HQ.pdf",
        "LANDLORD CONSENT TO CHANGE OF CONTROL AND LEASE ASSIGNMENT",
        [
            "SF Embarcadero Real Estate Trust ('Landlord') hereby consents to the change of control of Tenant (CloudScale Technologies, Inc.) under the Master Office Lease dated June 1, 2022.",
            "IN WITNESS WHEREOF, Landlord and Tenant have executed this Consent.",
            "SF EMBARCADERO REAL ESTATE TRUST<br/>By: /s/ Gerald Montgomery<br/>Name: Gerald Montgomery<br/>Title: Authorized Trustee",
            "CLOUDSCALE TECHNOLOGIES, INC.<br/>By: /s/ Dr. Alexander Vance<br/>Name: Dr. Alexander Vance<br/>Title: CEO",
        ]
    )

    # 15. Secretary's Certificate -> Doc_Signed_0817.pdf
    make_pdf(
        "Doc_Signed_0817.pdf",
        "SECRETARY'S INCUMBENCY AND AUTHORITY CERTIFICATE",
        [
            "I, Amanda Wright, Secretary of CloudScale Technologies, Inc. (the 'Company'), do hereby certify that:",
            "1. Attached hereto as Exhibit A is a true, correct, and complete copy of the Certificate of Incorporation of the Company.",
            "2. Attached hereto as Exhibit B is a true and complete copy of the Bylaws of the Company.",
            "3. The following persons are duly elected, qualified, and acting officers of the Company holding the offices set opposite their names:",
            "Dr. Alexander Vance - Chief Executive Officer [Signed: /s/ Dr. Alexander Vance]<br/>Amanda Wright - Secretary & Treasurer [Signed: /s/ Amanda Wright]",
            "IN WITNESS WHEREOF, I have executed this Certificate and affixed the seal of the Company.",
            "/s/ Amanda Wright<br/>Amanda Wright, Secretary",
        ]
    )

    # 16. Officer's Closing Certificate -> Officer_Closing_Cert_Apex.pdf
    make_pdf(
        "Officer_Closing_Cert_Apex.pdf",
        "OFFICER'S CLOSING CERTIFICATE OF CLOUDSCALE TECHNOLOGIES, INC.",
        [
            "The undersigned, Chief Executive Officer of CloudScale Technologies, Inc., delivers this certificate pursuant to Section 7.02(a) of the Merger Agreement:",
            "1. The representations and warranties of the Company are true and correct as of the Closing Date.",
            "2. The Company has performed all covenants and agreements in all material respects.",
            "IN WITNESS WHEREOF, the undersigned has executed this Certificate.",
            "/s/ Dr. Alexander Vance<br/>Dr. Alexander Vance, Chief Executive Officer",
        ]
    )

    # 17. Solvency Certificate -> Solvency_Cert_Apex.pdf
    make_pdf(
        "Solvency_Cert_Apex.pdf",
        "SOLVENCY CERTIFICATE OF APEX HOLDINGS LLC",
        [
            "The undersigned, Chief Financial Officer of Apex Holdings LLC, certifies pursuant to Section 6.04 of the Merger Agreement that immediately after the Effective Time and after giving effect to the Merger and financing transactions, Parent and its subsidiaries on a consolidated basis are solvent.",
            "IN WITNESS WHEREOF, the undersigned CFO has executed this Certificate.",
            "/s/ Gregory Sterling<br/>Gregory Sterling, Chief Financial Officer",
        ]
    )

    # 18. Legal Opinion -> Scan_0817_2026_09312.pdf
    make_pdf(
        "Scan_0817_2026_09312.pdf",
        "LEGAL OPINION OF WILSON SONSINI GOODRICH & ROSATI LLP",
        [
            "To: Apex Holdings LLC",
            "Ladies and Gentlemen: We have acted as corporate counsel to CloudScale Technologies, Inc., a Delaware corporation (the 'Company'), in connection with the Agreement and Plan of Merger.",
            "Based upon our review of the corporate records, it is our opinion that:",
            "1. The Company is a corporation duly organized, validly existing and in good standing under Delaware law.",
            "2. The Company has all requisite corporate power and authority to execute, deliver, and perform the Merger Agreement.",
            "3. The Merger Agreement constitutes the valid and binding obligation of the Company.",
            "Very truly yours,<br/>WILSON SONSINI GOODRICH & ROSATI<br/>Professional Corporation<br/>/s/ Wilson Sonsini Goodrich & Rosati P.C.",
        ]
    )

    # 19. Tax Opinion -> Tax_Opinion_Sullivan_Cromwell.pdf
    make_pdf(
        "Tax_Opinion_Sullivan_Cromwell.pdf",
        "TAX OPINION OF SULLIVAN & CROMWELL LLP (SECTION 368 REORGANIZATION)",
        [
            "To: Apex Holdings LLC and CloudScale Technologies, Inc.",
            "Ladies and Gentlemen: We have acted as special tax counsel in connection with the reverse triangular merger.",
            "Based on the factual representations, it is our opinion that the Merger will qualify as a reorganization within the meaning of Section 368(a) of the Internal Revenue Code of 1986, as amended.",
            "/s/ Sullivan & Cromwell LLP",
        ]
    )

    # 20. Funds Flow Memo -> Funds_Flow_Memo_Signed.pdf
    make_pdf(
        "Funds_Flow_Memo_Signed.pdf",
        "FUNDS FLOW MEMORANDUM & CLOSING SETTLEMENT STATEMENT",
        [
            "Project Titan - $450,000,000 Acquisition of CloudScale Technologies, Inc.",
            "SOURCES OF FUNDS:<br/>Apex Acquisition Equity: $325,000,000<br/>Senior Debt Financing (JPMorgan): $125,000,000<br/>TOTAL SOURCES: $450,000,000",
            "USES OF FUNDS:<br/>Merger Consideration to Common/Preferred Stockholders: $385,000,000<br/>Indemnification Escrow Deposit (Citibank): $45,000,000<br/>Payoff of Senior Credit Facility (JPMorgan): $15,000,000<br/>Transaction Expenses & Advisory Fees: $5,000,000<br/>TOTAL USES: $450,000,000",
            "APPROVED AND ACCEPTED AS OF AUGUST 18, 2026:",
            "APEX HOLDINGS LLC: /s/ Victoria Sterling<br/>CLOUDSCALE TECHNOLOGIES, INC.: /s/ Dr. Alexander Vance",
        ]
    )

    # 21. Payoff Letter -> Payoff_Letter_JPMorgan.pdf
    make_pdf(
        "Payoff_Letter_JPMorgan.pdf",
        "PAYOFF LETTER AND LIEN RELEASE AGREEMENT",
        [
            "JPMorgan Chase Bank, N.A. confirms that upon receipt of $15,248,320.15 on August 18, 2026, all obligations under the Credit Agreement dated April 10, 2023, shall be satisfied in full, and all security interests and liens shall be automatically terminated.",
            "JPMORGAN CHASE BANK, N.A.<br/>By: /s/ Harold Davenport<br/>Title: Managing Director, Commercial Banking",
        ]
    )

    # 22. UCC-3 Termination -> UCC3_Termination_Secured_Creditor.pdf
    make_pdf(
        "UCC3_Termination_Secured_Creditor.pdf",
        "STATE OF DELAWARE - UNIFORM COMMERCIAL CODE UCC-3 FINANCING STATEMENT AMENDMENT / TERMINATION",
        [
            "INITIAL FINANCING STATEMENT FILE NUMBER: 2023-094812",
            "DEBTOR: CloudScale Technologies, Inc.",
            "SECURED PARTY: JPMorgan Chase Bank, N.A.",
            "TERMINATION: Effectiveness of the Financing Statement identified above is terminated with respect to security interest(s) of Secured Party.",
            "FILED IN THE OFFICE OF THE DELAWARE SECRETARY OF STATE ON AUGUST 18, 2026.",
        ]
    )

    # 23. Cap Table -> Schedule_2_1_Cap_Table.docx
    make_docx(
        "Schedule_2_1_Cap_Table.docx",
        "SCHEDULE 2.1(a) - CAPITALIZATION TABLE & EQUITY LEDGER",
        [
            "CloudScale Technologies, Inc. - Certified Capitalization Table as of August 18, 2026",
            "Common Stock Issued & Outstanding: 12,500,000 shares\nSeries A Preferred Stock: 5,000,000 shares\nSeries B Preferred Stock: 4,250,000 shares\nVested Stock Options: 1,800,000 shares\nTotal Fully Diluted Share Count: 23,550,000 shares",
            "CERTIFIED BY:\n/s/ Dr. Alexander Vance\nChief Executive Officer",
        ]
    )

    print(f"Successfully generated 23 sample M&A documents in {OUTPUT_DIR}")


if __name__ == "__main__":
    generate_deal_corpus()
