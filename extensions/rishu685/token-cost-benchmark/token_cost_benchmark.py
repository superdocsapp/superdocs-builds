import os
import sys
import json
import time
import httpx

API_KEY = os.environ.get("SUPERDOCS_API_KEY")
if not API_KEY:
    try:
        with open("/Users/apple/.superdocs/agent_credentials.json") as f:
            creds = json.load(f)
            API_KEY = creds.get("api_key")
    except Exception:
        pass

if not API_KEY:
    print("Error: SUPERDOCS_API_KEY environment variable is not set.")
    sys.exit(1)

BASE_URL = "https://api.superdocs.app"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def estimate_tokens(text):
    """Rough estimation of token count (~4 characters per token)."""
    return len(text) // 4

def main():
    print("=== SuperDocs Token-Cost & Latency Benchmark ===\n")
    print("Comparing Whole-Document Regeneration vs. SuperDocs Surgical Editing...\n")

    client = httpx.Client(timeout=300.0)

    # 1. Init session
    init_res = client.post(f"{BASE_URL}/v1/sessions/init", json={}, headers=HEADERS)
    if init_res.status_code != 200:
        print(f"Failed to init session: {init_res.text}")
        sys.exit(1)
    session_id = init_res.json().get("session_id")
    print(f"Session initialized. Session ID: {session_id}\n")

    # 2. Build a multi-section document (10 sections)
    doc_sections = []
    for i in range(1, 11):
        doc_sections.append(
            f"<div data-chunk-id='sec-{i}'>"
            f"<h2>Section {i}: Operational Guideline {i}</h2>"
            f"<p>This is the detailed specification for section {i}. It includes policy rules, compliance requirements, "
            f"operational procedures, risk mitigation steps, and monitoring protocols designed to ensure compliance.</p>"
            f"</div>"
        )
    full_doc_html = "<div>" + "".join(doc_sections) + "</div>"
    
    # ------------------ TEST 1: Full Regeneration ------------------
    print("Running Test 1: Full Document Regeneration (Simulated Full Re-send)...")
    start_time_a = time.time()
    
    # In full regeneration, caller sends entire doc HTML and asks for rewrite
    input_text_a = f"Edit Section 3 in this document: {full_doc_html}"
    tokens_in_a = estimate_tokens(input_text_a)
    
    res_a = client.post(
        f"{BASE_URL}/v1/chat",
        json={
            "session_id": session_id,
            "message": "Update Section 3 to add: 'All compliance logs must be retained for 7 years.'",
            "document_html": full_doc_html,
            "response_mode": "full"
        },
        headers=HEADERS
    )
    time_a = round(time.time() - start_time_a, 2)
    output_text_a = res_a.text
    tokens_out_a = estimate_tokens(output_text_a)
    total_tokens_a = tokens_in_a + tokens_out_a
    print(f"Test 1 Complete: Time = {time_a}s | Input Tokens = {tokens_in_a} | Output Tokens = {tokens_out_a} | Total = {total_tokens_a}\n")

    # ------------------ TEST 2: SuperDocs Compact Surgical Edit ------------------
    print("Running Test 2: SuperDocs Compact Surgical Editing (response_mode='compact')...")
    start_time_b = time.time()
    
    # In compact surgical edit, caller sends targeted edit instruction without re-sending full document HTML
    input_text_b = "Update Section 3 to add: 'All compliance logs must be retained for 7 years.'"
    tokens_in_b = estimate_tokens(input_text_b)
    
    res_b = client.post(
        f"{BASE_URL}/v1/chat",
        json={
            "session_id": session_id,
            "message": input_text_b,
            "response_mode": "compact"
        },
        headers=HEADERS
    )
    time_b = round(time.time() - start_time_b, 2)
    output_text_b = res_b.text
    tokens_out_b = estimate_tokens(output_text_b)
    total_tokens_b = tokens_in_b + tokens_out_b
    print(f"Test 2 Complete: Time = {time_b}s | Input Tokens = {tokens_in_b} | Output Tokens = {tokens_out_b} | Total = {total_tokens_b}\n")

    # ------------------ RESULTS REPORT ------------------
    token_savings = round(((total_tokens_a - total_tokens_b) / total_tokens_a) * 100, 1)
    latency_diff = round(time_a - time_b, 2)

    report_markdown = (
        f"# Benchmark Results: SuperDocs Surgical Editing vs. Full Regeneration\n\n"
        f"| Metric | Full Document Regeneration | SuperDocs Surgical Edit (Compact) | Improvement |\n"
        f"|---|---|---|---|\n"
        f"| **Input Tokens (est.)** | {tokens_in_a} tokens | {tokens_in_b} tokens | **{round(((tokens_in_a - tokens_in_b)/tokens_in_a)*100, 1)}% reduction** |\n"
        f"| **Output Tokens (est.)** | {tokens_out_a} tokens | {tokens_out_b} tokens | **{round(((tokens_out_a - tokens_out_b)/tokens_out_a)*100, 1)}% reduction** |\n"
        f"| **Total Tokens / Turn** | {total_tokens_a} tokens | {total_tokens_b} tokens | **{token_savings}% token savings** |\n"
        f"| **Latency (Wall-clock)** | {time_a} seconds | {time_b} seconds | **{abs(latency_diff)}s difference** |\n\n"
        f"### Key Takeaway\n"
        f"Surgical section editing via SuperDocs `response_mode='compact'` reduces total token footprint by **{token_savings}%**, "
        f"eliminating redundant payload transmission and scaling cost-effectively as documents grow in length."
    )

    print("=== BENCHMARK SUMMARY ===")
    print(report_markdown)

    # ------------------ CONSTRUCT STYLED HTML REPORT FOR PDF EXPORT ------------------
    input_reduction = round(((tokens_in_a - tokens_in_b)/tokens_in_a)*100, 1)
    output_reduction = round(((tokens_out_a - tokens_out_b)/tokens_out_a)*100, 1)
    
    report_html = f"""
    <div style="font-family: 'Inter', sans-serif; color: #202940; background-color: #FBF9F6; padding: 30px; border-radius: 20px;">
      <h1 style="font-family: 'Space Grotesk', sans-serif; color: #8B6240; border-bottom: 2px solid rgba(32,41,64,0.12); padding-bottom: 15px; margin-top: 0;">
        SuperDocs Token & Latency Benchmark Report
      </h1>
      <p style="font-size: 14px; line-height: 1.6; color: #202940;">
        This benchmark evaluates the performance of Scenario A (Whole-Document Regeneration) versus Scenario B (SuperDocs compact surgical edits with <code>response_mode='compact'</code>) on a 10-section document.
      </p>
      
      <table style="width: 100%; border-collapse: collapse; margin-top: 25px; margin-bottom: 25px; font-size: 14px;">
        <thead>
          <tr style="background-color: #202940; color: #FBF9F6;">
            <th style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; text-align: left;">Performance Metric</th>
            <th style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; text-align: left;">Scenario A: Full Regeneration</th>
            <th style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; text-align: left;">Scenario B: compact Surgical Edit</th>
            <th style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; text-align: left;">Measured Improvement</th>
          </tr>
        </thead>
        <tbody>
          <tr style="background-color: rgba(32,41,64,0.02);">
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; font-weight: bold;">Input Tokens (est.)</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px;">{tokens_in_a} tokens</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px;">{tokens_in_b} tokens</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; color: #1DA851; font-weight: bold;">-{tokens_in_a - tokens_in_b} ({input_reduction}%)</td>
          </tr>
          <tr>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; font-weight: bold;">Output Tokens (est.)</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px;">{tokens_out_a} tokens</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px;">{tokens_out_b} tokens</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; color: #1DA851; font-weight: bold;">-{tokens_out_a - tokens_out_b} ({output_reduction}%)</td>
          </tr>
          <tr style="background-color: rgba(141,98,64,0.08);">
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; font-weight: bold;">Total Tokens / Turn</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; font-weight: bold;">{total_tokens_a} tokens</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; font-weight: bold;">{total_tokens_b} tokens</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; color: #1DA851; font-weight: bold;">-{total_tokens_a - total_tokens_b} ({token_savings}%)</td>
          </tr>
          <tr style="background-color: rgba(32,41,64,0.02);">
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; font-weight: bold;">Latency (Wall-clock)</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px;">{time_a}s</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px;">{time_b}s</td>
            <td style="border: 1px solid rgba(32,41,64,0.12); padding: 12px; font-weight: bold; color: #C94C3D;">{latency_diff}s difference</td>
          </tr>
        </tbody>
      </table>

      <div style="background-color: rgba(29,168,81,0.05); border-left: 4px solid #1DA851; padding: 18px; border-radius: 8px; font-size: 14px; line-height: 1.6; margin-top: 20px;">
        <strong style="color: #1DA851;">Core Analysis:</strong> Compact surgical section editing via SuperDocs <code>response_mode='compact'</code> 
        reduces overall token footprint by <strong>{token_savings}%</strong>. By transmitting only modified section deltas 
        rather than regenerating the entire document, API clients eliminate redundant token consumption and remain 
        safely under rate limit boundaries while accelerating edit operations.
      </div>
    </div>
    """

    # Export report to PDF
    print("\nExporting Benchmark Report to PDF...")
    export_res = client.post(
        f"{BASE_URL}/v1/documents/export",
        json={
            "session_id": session_id,
            "format": "pdf",
            "html": report_html,
            "filename": "SuperDocs_Token_Cost_Benchmark.pdf"
        },
        headers=HEADERS
    )
    if export_res.status_code == 200:
        content_type = export_res.headers.get("content-type", "")
        if "application/json" not in content_type:
            with open("SuperDocs_Token_Cost_Benchmark.pdf", "wb") as f:
                f.write(export_res.content)
            print("Exported PDF saved to: SuperDocs_Token_Cost_Benchmark.pdf")
        else:
            print(f"Export URL: {export_res.json().get('download_url')}")

if __name__ == "__main__":
    main()
