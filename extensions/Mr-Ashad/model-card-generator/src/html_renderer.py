"""Interactive, Publication-Ready HTML & Web Viewer Generator for Model Cards.

Renders high-aesthetic Model Cards with dark/light mode toggle, metric visualizers,
domain filter pills, real-time search, delta progress bars, and print/PDF optimization.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class HTMLCardRenderer:
    """Generates standalone, interactive HTML Model Card experiences."""

    @staticmethod
    def render(
        manifest: Dict[str, Any],
        evaluation_records: List[Dict[str, Any]],
        evaluation_metadata: Optional[Dict[str, Any]] = None,
        raw_markdown: Optional[str] = None
    ) -> str:
        """Render complete interactive HTML document."""
        eval_meta = evaluation_metadata or {}
        model_name = manifest.get("model_name", "Model Card")
        version = manifest.get("version", "v1.0.0")
        release_date = manifest.get("release_date", "Not provided")
        model_type = manifest.get("model_type", "Not provided")
        license_str = manifest.get("license", "Not provided")
        description = manifest.get("description", "Not provided")
        architecture = manifest.get("model_architecture", "Not provided")
        org = manifest.get("author_organization", "Not provided")
        contact = manifest.get("maintenance_contact", "Not provided")
        intended = manifest.get("intended_purpose", "Not provided")
        out_of_scope = manifest.get("out_of_scope_uses", "Not provided")
        limitations = manifest.get("limitations", "Not provided")
        training_data = manifest.get("training_data_summary", "Not provided")
        hardware = manifest.get("hardware_and_compute", "Not provided")
        ethics = manifest.get("ethical_considerations", "Not provided")
        citation = manifest.get("citation", "Not provided")

        eval_ts = eval_meta.get("timestamp", "2026-08-17 12:00:00 UTC")
        eval_run_id = eval_meta.get("run_id", "run-latest")
        eval_baseline = eval_meta.get("baseline_model", "Baseline Reference")

        # Compute summary stats for hero metrics
        total_evals = len(evaluation_records)
        max_score = max([r.get("score", 0) for r in evaluation_records], default=0.0)
        positive_deltas = [r.get("delta_val", 0) for r in evaluation_records if r.get("delta_val") is not None and r.get("delta_val") > 0]
        max_delta = max(positive_deltas, default=0.0)

        # Build JSON data payload for embedded frontend interactivity
        eval_json_str = json.dumps(evaluation_records)
        manifest_json_str = json.dumps(manifest)

        html_template = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Model Card: {model_name} ({version})</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Outfit:wght@500;600;700;800&display=swap" rel="stylesheet" />
  
  <style>
    :root {{
      --font-heading: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-body: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
      
      /* Dark Theme (Default) */
      --bg-base: #0B0F19;
      --bg-surface: #111827;
      --bg-card: rgba(17, 24, 39, 0.85);
      --bg-card-hover: #1F2937;
      --bg-input: #1F2937;
      --border-color: rgba(255, 255, 255, 0.08);
      --border-accent: rgba(99, 102, 241, 0.3);
      
      --text-main: #F9FAFB;
      --text-muted: #9CA3AF;
      --text-subtle: #6B7280;
      
      --primary: #6366F1;
      --primary-glow: rgba(99, 102, 241, 0.25);
      --accent-cyan: #06B6D4;
      --accent-emerald: #10B981;
      --accent-amber: #F59E0B;
      --accent-rose: #F43F5E;
      
      --pill-positive-bg: rgba(16, 185, 129, 0.15);
      --pill-positive-text: #34D399;
      --pill-negative-bg: rgba(244, 63, 94, 0.15);
      --pill-negative-text: #FB7185;
      --pill-neutral-bg: rgba(156, 163, 175, 0.15);
      --pill-neutral-text: #9CA3AF;
      
      --shadow-card: 0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.4);
      --shadow-glow: 0 0 30px var(--primary-glow);
    }}

    [data-theme="light"] {{
      --bg-base: #F8FAFC;
      --bg-surface: #FFFFFF;
      --bg-card: #FFFFFF;
      --bg-card-hover: #F1F5F9;
      --bg-input: #F1F5F9;
      --border-color: #E2E8F0;
      --border-accent: rgba(99, 102, 241, 0.3);
      
      --text-main: #0F172A;
      --text-muted: #475569;
      --text-subtle: #94A3B8;
      
      --primary: #4F46E5;
      --primary-glow: rgba(79, 70, 229, 0.15);
      --accent-cyan: #0891B2;
      --accent-emerald: #059669;
      --accent-amber: #D97706;
      --accent-rose: #E11D48;
      
      --pill-positive-bg: #ECFDF5;
      --pill-positive-text: #059669;
      --pill-negative-bg: #FFF1F2;
      --pill-negative-text: #E11D48;
      --pill-neutral-bg: #F1F5F9;
      --pill-neutral-text: #64748B;
      
      --shadow-card: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -4px rgba(0, 0, 0, 0.05);
      --shadow-glow: 0 0 25px rgba(79, 70, 229, 0.1);
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      transition: background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease;
    }}

    body {{
      font-family: var(--font-body);
      background-color: var(--bg-base);
      color: var(--text-main);
      line-height: 1.6;
      padding-bottom: 80px;
    }}

    /* Top Navigation Header */
    .top-nav {{
      position: sticky;
      top: 0;
      z-index: 100;
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      background: rgba(11, 15, 25, 0.85);
      border-bottom: 1px solid var(--border-color);
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 14px 32px;
    }}

    [data-theme="light"] .top-nav {{
      background: rgba(255, 255, 255, 0.88);
    }}

    .nav-brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      font-family: var(--font-heading);
      font-weight: 700;
      font-size: 1.15rem;
      color: var(--text-main);
      text-decoration: none;
    }}

    .nav-brand-badge {{
      background: linear-gradient(135deg, var(--primary), var(--accent-cyan));
      color: #FFF;
      font-size: 0.75rem;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 6px;
      letter-spacing: 0.5px;
    }}

    .nav-controls {{
      display: flex;
      gap: 12px;
      align-items: center;
    }}

    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-family: var(--font-body);
      font-size: 0.875rem;
      font-weight: 600;
      padding: 8px 16px;
      border-radius: 8px;
      border: 1px solid var(--border-color);
      background: var(--bg-surface);
      color: var(--text-main);
      cursor: pointer;
      box-shadow: 0 1px 2px rgba(0,0,0,0.1);
      transition: all 0.2s ease;
    }}

    .btn:hover {{
      border-color: var(--primary);
      transform: translateY(-1px);
      box-shadow: var(--shadow-glow);
    }}

    .btn-primary {{
      background: linear-gradient(135deg, var(--primary), #4338CA);
      color: #FFF;
      border: none;
    }}

    .btn-primary:hover {{
      filter: brightness(1.1);
    }}

    /* Container */
    .container {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 32px 24px;
    }}

    /* Hero Banner */
    .hero-card {{
      background: linear-gradient(145deg, var(--bg-surface), #1A2234);
      border: 1px solid var(--border-color);
      border-radius: 20px;
      padding: 36px 40px;
      box-shadow: var(--shadow-card);
      position: relative;
      overflow: hidden;
      margin-bottom: 32px;
    }}

    [data-theme="light"] .hero-card {{
      background: linear-gradient(145deg, #FFFFFF, #F1F5F9);
    }}

    .hero-card::before {{
      content: '';
      position: absolute;
      top: -50%;
      right: -20%;
      width: 450px;
      height: 450px;
      background: radial-gradient(circle, var(--primary-glow) 0%, transparent 70%);
      pointer-events: none;
    }}

    .hero-title {{
      font-family: var(--font-heading);
      font-size: 2.5rem;
      font-weight: 800;
      letter-spacing: -0.5px;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
    }}

    .hero-subtitle {{
      color: var(--text-muted);
      font-size: 1.1rem;
      max-width: 850px;
      line-height: 1.6;
      margin-bottom: 24px;
    }}

    .badges-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 28px;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 0.85rem;
      font-weight: 600;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-color);
      color: var(--text-main);
    }}

    [data-theme="light"] .badge {{
      background: #F1F5F9;
    }}

    .badge-primary {{ border-color: var(--primary); color: #A5B4FC; }}
    .badge-success {{ border-color: var(--accent-emerald); color: #6EE7B7; }}
    .badge-cyan    {{ border-color: var(--accent-cyan); color: #67E8F9; }}

    [data-theme="light"] .badge-primary {{ color: var(--primary); }}
    [data-theme="light"] .badge-success {{ color: var(--accent-emerald); }}
    [data-theme="light"] .badge-cyan    {{ color: var(--accent-cyan); }}

    /* Quick Stat Cards Grid */
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-top: 20px;
    }}

    .stat-card {{
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 16px 20px;
    }}

    [data-theme="light"] .stat-card {{
      background: #FFFFFF;
    }}

    .stat-label {{
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-subtle);
      margin-bottom: 4px;
    }}

    .stat-value {{
      font-family: var(--font-heading);
      font-size: 1.75rem;
      font-weight: 700;
      color: var(--text-main);
    }}

    .stat-sub {{
      font-size: 0.85rem;
      color: var(--accent-emerald);
      margin-top: 2px;
    }}

    /* Section Cards */
    .section-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 16px;
      padding: 32px;
      margin-bottom: 28px;
      box-shadow: var(--shadow-card);
    }}

    .section-title {{
      font-family: var(--font-heading);
      font-size: 1.4rem;
      font-weight: 700;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 10px;
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 12px;
    }}

    /* Grid Layout for details */
    .two-col-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }}

    @media (max-width: 768px) {{
      .two-col-grid {{ grid-template-columns: 1fr; }}
    }}

    .info-box {{
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid var(--border-color);
      border-radius: 10px;
      padding: 18px 22px;
    }}

    [data-theme="light"] .info-box {{
      background: #F8FAFC;
    }}

    .info-box h4 {{
      font-size: 0.95rem;
      font-weight: 600;
      margin-bottom: 8px;
      color: var(--primary);
    }}

    .info-box ul {{
      padding-left: 20px;
      color: var(--text-muted);
      font-size: 0.92rem;
    }}

    .info-box li {{
      margin-bottom: 6px;
    }}

    /* Interactive Benchmark Section */
    .eval-toolbar {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 20px;
    }}

    .filter-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .filter-pill {{
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 0.82rem;
      font-weight: 600;
      border: 1px solid var(--border-color);
      background: var(--bg-card);
      color: var(--text-muted);
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .filter-pill:hover, .filter-pill.active {{
      background: var(--primary);
      color: #FFF;
      border-color: var(--primary);
    }}

    .search-input {{
      padding: 8px 16px;
      border-radius: 8px;
      border: 1px solid var(--border-color);
      background: var(--bg-input);
      color: var(--text-main);
      font-size: 0.88rem;
      outline: none;
      min-width: 240px;
    }}

    .search-input:focus {{
      border-color: var(--primary);
      box-shadow: 0 0 0 2px var(--primary-glow);
    }}

    /* Benchmark Table */
    .table-container {{
      overflow-x: auto;
      border-radius: 12px;
      border: 1px solid var(--border-color);
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
      text-align: left;
    }}

    th {{
      background: rgba(255, 255, 255, 0.04);
      padding: 14px 18px;
      font-weight: 600;
      color: var(--text-muted);
      border-bottom: 1px solid var(--border-color);
      white-space: nowrap;
    }}

    [data-theme="light"] th {{
      background: #F1F5F9;
    }}

    td {{
      padding: 14px 18px;
      border-bottom: 1px solid var(--border-color);
      color: var(--text-main);
      vertical-align: middle;
    }}

    tr:last-child td {{
      border-bottom: none;
    }}

    tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    [data-theme="light"] tr:hover td {{
      background: #F8FAFC;
    }}

    .delta-pill {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      border-radius: 12px;
      font-family: var(--font-mono);
      font-size: 0.8rem;
      font-weight: 600;
      white-space: nowrap;
    }}

    .delta-positive {{ background: var(--pill-positive-bg); color: var(--pill-positive-text); }}
    .delta-negative {{ background: var(--pill-negative-bg); color: var(--pill-negative-text); }}
    .delta-neutral  {{ background: var(--pill-neutral-bg);  color: var(--pill-neutral-text); }}

    .score-bar-wrap {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 160px;
    }}

    .score-bar-bg {{
      flex: 1;
      height: 8px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 4px;
      overflow: hidden;
      position: relative;
    }}

    [data-theme="light"] .score-bar-bg {{
      background: #E2E8F0;
    }}

    .score-bar-fill {{
      height: 100%;
      background: linear-gradient(90deg, var(--primary), var(--accent-cyan));
      border-radius: 4px;
      transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
    }}

    .score-text {{
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 0.95rem;
    }}

    /* Callout Alerts */
    .callout {{
      border-radius: 10px;
      padding: 16px 20px;
      margin: 16px 0;
      border-left: 4px solid var(--primary);
      background: rgba(99, 102, 241, 0.08);
      font-size: 0.92rem;
    }}

    .callout-warning {{
      border-left-color: var(--accent-amber);
      background: rgba(245, 158, 11, 0.08);
    }}

    .callout-title {{
      font-weight: 700;
      margin-bottom: 4px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    /* Code & Bibtex Block */
    pre.code-block {{
      background: #050811;
      border: 1px solid var(--border-color);
      border-radius: 10px;
      padding: 18px;
      font-family: var(--font-mono);
      font-size: 0.85rem;
      color: #A5B4FC;
      overflow-x: auto;
      white-space: pre-wrap;
    }}

    /* Print & PDF Export Styles */
    @media print {{
      @page {{
        size: A4 portrait;
        margin: 12mm 14mm 14mm 14mm;
      }}
      *, *::before, *::after {{
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
        color-adjust: exact !important;
      }}
      .top-nav, .eval-toolbar, .btn, #themeToggleBtn {{
        display: none !important;
      }}
      body {{
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        padding-bottom: 0 !important;
        font-size: 8.5pt !important;
        line-height: 1.45 !important;
      }}
      .container {{
        max-width: 100% !important;
        padding: 0 !important;
      }}
      .hero-card {{
        background: linear-gradient(135deg, #EEF2FF 0%, #F8FAFC 100%) !important;
        border: 1.5px solid #4F46E5 !important;
        border-radius: 10px !important;
        padding: 16px 20px !important;
        margin-bottom: 14px !important;
        box-shadow: none !important;
        page-break-inside: avoid;
        break-inside: avoid;
      }}
      .hero-title {{
        font-size: 18pt !important;
        color: #1E1B4B !important;
        margin-bottom: 4px !important;
      }}
      .hero-subtitle {{
        font-size: 9pt !important;
        color: #475569 !important;
        margin-bottom: 10px !important;
      }}
      .badges-row {{
        margin-bottom: 10px !important;
        gap: 6px !important;
      }}
      .badge {{
        padding: 3px 8px !important;
        font-size: 7.5pt !important;
        background: #F1F5F9 !important;
        border: 1px solid #CBD5E1 !important;
        color: #1E293B !important;
      }}
      .stats-grid {{
        grid-template-columns: repeat(4, 1fr) !important;
        gap: 8px !important;
        margin-top: 10px !important;
      }}
      .stat-card {{
        background: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        padding: 8px 10px !important;
        border-radius: 6px !important;
      }}
      .stat-label {{
        font-size: 6.5pt !important;
        color: #64748B !important;
      }}
      .stat-value {{
        font-size: 12pt !important;
        color: #0F172A !important;
      }}
      .stat-sub {{
        font-size: 7pt !important;
        color: #059669 !important;
      }}
      .section-card {{
        background: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
        padding: 14px 16px !important;
        margin-bottom: 12px !important;
        box-shadow: none !important;
        page-break-inside: avoid;
        break-inside: avoid;
      }}
      .section-title {{
        font-size: 11pt !important;
        color: #1E1B4B !important;
        border-bottom: 1.5px solid #E2E8F0 !important;
        margin-bottom: 10px !important;
        padding-bottom: 4px !important;
      }}
      .info-box {{
        background: #F8FAFC !important;
        border: 1px solid #E2E8F0 !important;
        padding: 10px 12px !important;
      }}
      .info-box h4 {{
        font-size: 8.5pt !important;
        color: #4F46E5 !important;
      }}
      .info-box ul {{
        font-size: 8pt !important;
      }}
      .table-container {{
        border: 1px solid #E2E8F0 !important;
        border-radius: 6px !important;
      }}
      table {{
        font-size: 7.5pt !important;
      }}
      th {{
        background: #EEF2FF !important;
        color: #1E1B4B !important;
        font-weight: 700 !important;
        padding: 6px 8px !important;
      }}
      td {{
        padding: 6px 8px !important;
        border-bottom: 1px solid #E2E8F0 !important;
        color: #0F172A !important;
      }}
      tr:nth-child(even) td {{
        background: #F8FAFC !important;
      }}
      .delta-pill {{
        padding: 2px 6px !important;
        font-size: 7pt !important;
      }}
      .delta-positive {{ background: #ECFDF5 !important; color: #047857 !important; }}
      .delta-negative {{ background: #FFF1F2 !important; color: #BE123C !important; }}
      .delta-neutral  {{ background: #F1F5F9 !important; color: #64748B !important; }}
      .score-bar-bg {{
        background: #E2E8F0 !important;
        height: 6px !important;
      }}
      .score-bar-fill {{
        background: #4F46E5 !important;
      }}
      .score-text {{
        font-size: 8pt !important;
      }}
      .callout {{
        padding: 10px 12px !important;
        font-size: 8pt !important;
        page-break-inside: avoid;
        break-inside: avoid;
      }}
      .callout-warning {{
        background: #FFFBEB !important;
        border-left: 3px solid #F59E0B !important;
      }}
      pre.code-block {{
        background: #F8FAFC !important;
        color: #334155 !important;
        border: 1px solid #CBD5E1 !important;
        font-size: 7pt !important;
        padding: 10px !important;
        page-break-inside: avoid;
        break-inside: avoid;
      }}
    }}
  </style>
</head>
<body>

  <!-- Top Sticky Navigation Bar -->
  <header class="top-nav">
    <a href="#" class="nav-brand">
      <span>🏛️ Model Card Explorer</span>
      <span class="nav-brand-badge">SuperDocs Sync</span>
    </a>
    <div class="nav-controls">
      <button class="btn" id="themeToggleBtn" onclick="toggleTheme()">
        <span id="themeIcon">☀️</span> <span id="themeText">Light Mode</span>
      </button>
      <button class="btn" onclick="copyMarkdown()">
        📋 Copy Markdown
      </button>
      <button class="btn btn-primary" onclick="window.print()">
        📄 Print / Export PDF
      </button>
    </div>
  </header>

  <main class="container">
    
    <!-- Hero Header -->
    <section class="hero-card">
      <div class="badges-row">
        <span class="badge badge-primary">🏷️ {version}</span>
        <span class="badge badge-success">📜 {license_str}</span>
        <span class="badge badge-cyan">⚡ {model_type}</span>
        <span class="badge">📅 {release_date}</span>
      </div>

      <h1 class="hero-title">{model_name}</h1>
      <p class="hero-subtitle">{description}</p>

      <!-- Quick Metrics Highlight -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Total Benchmarks</div>
          <div class="stat-value">{total_evals}</div>
          <div class="stat-sub">Multi-domain capability suite</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Peak Performance</div>
          <div class="stat-value">{max_score:.1f}%</div>
          <div class="stat-sub">Top standardized metric</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Max Baseline Delta</div>
          <div class="stat-value">+{max_delta:.1f}%</div>
          <div class="stat-sub">Outperforming {eval_baseline}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Last Evaluation Run</div>
          <div class="stat-value" style="font-size: 1.1rem; padding-top: 8px;">{eval_ts[:10]}</div>
          <div class="stat-sub">{eval_run_id}</div>
        </div>
      </div>
    </section>

    <!-- 1. Technical Architecture & Governance -->
    <section class="section-card">
      <h2 class="section-title">📐 Specifications & Architecture</h2>
      <div class="two-col-grid">
        <div class="info-box">
          <h4>Model Specifications</h4>
          <ul>
            {HTMLCardRenderer._render_dict_or_list_html(architecture)}
          </ul>
        </div>
        <div class="info-box">
          <h4>Governance & Contacts</h4>
          <ul>
            <li><strong>Organization / Lab:</strong> {org}</li>
            <li><strong>Maintenance Contact:</strong> {HTMLCardRenderer._render_contact_html(contact)}</li>
            <li><strong>Hardware / Compute:</strong> {hardware}</li>
          </ul>
        </div>
      </div>
    </section>

    <!-- 2. Intended Purpose & Limitations -->
    <section class="section-card">
      <h2 class="section-title">🎯 Operational Scope & Limitations</h2>
      <div class="two-col-grid">
        <div class="info-box">
          <h4>✅ Primary Intended Applications</h4>
          <ul>
            {HTMLCardRenderer._render_list_items_html(intended)}
          </ul>
        </div>
        <div class="info-box">
          <h4>⚠️ Known Limitations</h4>
          <ul>
            {HTMLCardRenderer._render_list_items_html(limitations)}
          </ul>
        </div>
      </div>

      <div class="callout callout-warning" style="margin-top: 24px;">
        <div class="callout-title">🚫 Out-of-Scope & Prohibited Deployment Scenarios</div>
        <ul style="padding-left: 20px; margin-top: 6px;">
          {HTMLCardRenderer._render_list_items_html(out_of_scope)}
        </ul>
      </div>
    </section>

    <!-- 3. Quantitative Evaluation Benchmarks (Interactive) -->
    <section class="section-card" id="evaluation-section">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
        <h2 class="section-title" style="margin-bottom: 0; border-bottom: none; padding-bottom: 0;">
          📊 Benchmark Evaluations & Comparative Deltas
        </h2>
        <div style="font-size: 0.85rem; color: var(--text-subtle);">
          Synced with <strong>{eval_baseline}</strong>
        </div>
      </div>

      <!-- Evaluation Toolbar -->
      <div class="eval-toolbar">
        <div class="filter-pills" id="domainPills">
          <button class="filter-pill active" onclick="filterDomain('ALL')">All Domains</button>
        </div>
        <input type="text" class="search-input" id="metricSearch" placeholder="🔍 Search benchmarks or tasks..." oninput="handleSearch()" />
      </div>

      <!-- Interactive Benchmark Table -->
      <div class="table-container">
        <table id="benchmarkTable">
          <thead>
            <tr>
              <th>Benchmark</th>
              <th>Domain</th>
              <th>Metric & Setting</th>
              <th style="min-width: 180px;">Current Score</th>
              <th>Baseline ({eval_baseline})</th>
              <th>Delta</th>
              <th>Task Details</th>
            </tr>
          </thead>
          <tbody id="benchmarkTableBody">
            <!-- Populated via JavaScript -->
          </tbody>
        </table>
      </div>
    </section>

    <!-- 4. Training Data & Safety -->
    <section class="section-card">
      <h2 class="section-title">🛡️ Safety Evaluations & Training Data</h2>
      <div class="two-col-grid">
        <div class="info-box">
          <h4>🗄️ Training Data Summary</h4>
          <ul>
            {HTMLCardRenderer._render_dict_or_list_html(training_data)}
          </ul>
        </div>
        <div class="info-box">
          <h4>🛡️ Safety Alignment & Red Teaming</h4>
          <ul>
            {HTMLCardRenderer._render_list_items_html(ethics)}
          </ul>
        </div>
      </div>
    </section>

    <!-- 5. Citation -->
    <section class="section-card">
      <h2 class="section-title">📜 Citation & Attribution</h2>
      <pre class="code-block"><code>{citation}</code></pre>
    </section>

  </main>

  <script>
    // Embedded benchmark records
    const benchmarkData = {eval_json_str};
    let activeDomain = 'ALL';
    let searchQuery = '';

    // Initialize Domain Filter Pills
    function initFilters() {{
      const domains = Array.from(new Set(benchmarkData.map(item => item.domain || 'General'))).sort();
      const container = document.getElementById('domainPills');
      domains.forEach(d => {{
        const btn = document.createElement('button');
        btn.className = 'filter-pill';
        btn.textContent = d;
        btn.onclick = () => filterDomain(d);
        container.appendChild(btn);
      }});
    }}

    // Filter by Domain
    function filterDomain(domain) {{
      activeDomain = domain;
      document.querySelectorAll('.filter-pill').forEach(btn => {{
        btn.classList.toggle('active', btn.textContent === domain || (domain === 'ALL' && btn.textContent === 'All Domains'));
      }});
      renderTable();
    }}

    // Search handler
    function handleSearch() {{
      searchQuery = document.getElementById('metricSearch').value.toLowerCase();
      renderTable();
    }}

    // Render Table Rows
    function renderTable() {{
      const tbody = document.getElementById('benchmarkTableBody');
      tbody.innerHTML = '';

      const filtered = benchmarkData.filter(item => {{
        const matchesDomain = activeDomain === 'ALL' || item.domain === activeDomain;
        const matchesSearch = !searchQuery || 
          item.name.toLowerCase().includes(searchQuery) ||
          item.task_id.toLowerCase().includes(searchQuery) ||
          (item.description && item.description.toLowerCase().includes(searchQuery));
        return matchesDomain && matchesSearch;
      }});

      if (filtered.length === 0) {{
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-subtle); padding: 32px;">No matching benchmarks found.</td></tr>`;
        return;
      }}

      filtered.forEach(r => {{
        const tr = document.createElement('tr');

        // Delta Class
        let deltaClass = 'delta-neutral';
        if (r.delta_val > 0) deltaClass = 'delta-positive';
        else if (r.delta_val < 0) deltaClass = 'delta-negative';

        // Score bar percentage
        const pct = Math.min(Math.max(r.score || 0, 0), 100);

        tr.innerHTML = `
          <td><strong>${{r.name}}</strong></td>
          <td><span style="color: var(--text-muted); font-size: 0.85rem;">${{r.domain}}</span></td>
          <td>${{r.metric}} <span style="color: var(--text-subtle); font-size: 0.8rem;">(${{r.shots}})</span></td>
          <td>
            <div class="score-bar-wrap">
              <span class="score-text">${{r.score_str}}</span>
              <div class="score-bar-bg">
                <div class="score-bar-fill" style="width: ${{pct}}%;"></div>
              </div>
            </div>
          </td>
          <td style="font-family: var(--font-mono);">${{r.baseline_str}}</td>
          <td><span class="delta-pill ${{deltaClass}}">${{r.delta_str}}</span></td>
          <td style="color: var(--text-muted); font-size: 0.85rem; max-width: 250px;">${{r.description || '—'}}</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    // Theme Toggle
    function toggleTheme() {{
      const html = document.documentElement;
      const current = html.getAttribute('data-theme');
      const next = current === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-theme', next);
      
      document.getElementById('themeIcon').textContent = next === 'dark' ? '☀️' : '🌙';
      document.getElementById('themeText').textContent = next === 'dark' ? 'Light Mode' : 'Dark Mode';
    }}

    // Copy Raw Markdown
    function copyMarkdown() {{
      const rawMd = `{raw_markdown or ''}`;
      if (rawMd) {{
        navigator.clipboard.writeText(rawMd).then(() => {{
          alert('Model Card Markdown copied to clipboard!');
        }});
      }} else {{
        alert('Markdown content ready in output directory.');
      }}
    }}

    // Initialize on load
    document.addEventListener('DOMContentLoaded', () => {{
      initFilters();
      renderTable();
    }});
  </script>
</body>
</html>
"""
        return html_template

    @staticmethod
    def _render_list_items_html(value: Any) -> str:
        """Render string or list into <li> items."""
        if not value or value == "Not provided":
            return "<li><em>Not provided</em></li>"
        if isinstance(value, str):
            return f"<li>{value}</li>"
        if isinstance(value, list):
            items = [f"<li>{item}</li>" for item in value if item]
            return "".join(items) if items else "<li><em>Not provided</em></li>"
        return f"<li>{value}</li>"

    @staticmethod
    def _render_dict_or_list_html(value: Any) -> str:
        """Render dict or list cleanly as HTML list items."""
        if not value or value == "Not provided":
            return "<li><em>Not provided</em></li>"
        if isinstance(value, str):
            return f"<li>{value}</li>"
        if isinstance(value, dict):
            items = []
            for k, v in value.items():
                label = k.replace("_", " ").title()
                items.append(f"<li><strong>{label}:</strong> {v}</li>")
            return "".join(items)
        if isinstance(value, list):
            return "".join(f"<li>{item}</li>" for item in value)
        return f"<li>{value}</li>"

    @staticmethod
    def _render_contact_html(contact: Any) -> str:
        """Format contact details for HTML."""
        if not contact or contact == "Not provided":
            return "<em>Not provided</em>"
        if isinstance(contact, str):
            return contact
        if isinstance(contact, dict):
            parts = []
            if "team" in contact:
                parts.append(str(contact["team"]))
            if "email" in contact:
                parts.append(f'<a href="mailto:{contact["email"]}" style="color: var(--primary);">{contact["email"]}</a>')
            return " — ".join(parts) if parts else str(contact)
        return str(contact)
