EXTRACT_PROMPT = """You are a tariff classification expert. Extract all tariff-related information from the following document.

Document content:
{document_content}

Extract and structure the following information for each product mentioned:
1. HS Code (Harmonized System tariff code)
2. Product description
3. Applicable duty rate
4. Any special notes or conditions

Return a structured list of tariff claims."""


GENERATE_PROMPT = """You are a tariff classification expert. Generate a comprehensive tariff classification report.

Extracted claims:
{claims}

Generate a professional tariff classification report that includes:
1. Executive summary
2. Detailed classification for each product
3. Duty calculations
4. Compliance notes
5. Recommendations

Format the report in a clear, professional manner suitable for customs documentation."""
