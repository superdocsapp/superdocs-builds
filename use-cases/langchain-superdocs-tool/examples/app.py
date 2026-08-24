"""
SuperDocs Dynamic Agentic Task Creation, HITL Plan Studio & LangGraph Agent.

Run with:
    python use-cases/langchain-superdocs-tool/examples/app.py 8080
Then open http://localhost:8080 in your browser.
"""

import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import uuid
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

warnings.filterwarnings("ignore", category=UserWarning, module="langgraph.*")
warnings.filterwarnings("ignore", message=".*allowed_objects.*")

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.graph import create_superdocs_agent_graph
from superdocs_langchain.models import DynamicTaskPlan, PlanApprovalState, TaskPlanItem
from superdocs_langchain.planner import DynamicTaskPlanner
from superdocs_langchain.toolkit import SuperDocsToolkit

client = SuperDocsClient()
planner = DynamicTaskPlanner(client=client)

HTML_PAGE = """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SuperDocs • Dynamic Agentic Studio</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800;900&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script>
    (function() {
      const savedTheme = localStorage.getItem('superdocs_theme') || 'light';
      document.documentElement.setAttribute('data-theme', savedTheme);
    })();
  </script>
  <style>
    :root, [data-theme="light"] {
      --bg-base: #f8fafc;
      --bg-surface: rgba(255, 255, 255, 0.92);
      --bg-card: rgba(255, 255, 255, 0.96);
      --bg-elevated: #f1f5f9;
      --border-subtle: rgba(15, 23, 42, 0.08);
      --border-glow: rgba(99, 102, 241, 0.35);
      --text-main: #0f172a;
      --text-dim: #475569;
      --text-muted: #94a3b8;
      --primary: #6366f1;
      --primary-gradient: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #d946ef 100%);
      --neon-cyan: #0891b2;
      --neon-emerald: #059669;
      --accent-gradient: linear-gradient(135deg, #10b981 0%, #06b6d4 100%);
      --danger: #ef4444;
      --warning: #f59e0b;
      --input-bg: #ffffff;
      --input-border: #cbd5e1;
      --input-focus-border: #6366f1;
      --input-focus-shadow: rgba(99, 102, 241, 0.2);
      --header-bg: rgba(255, 255, 255, 0.88);
      --nav-bg: rgba(248, 250, 252, 0.85);
      --card-shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.06), 0 2px 6px -1px rgba(15, 23, 42, 0.03);
      --card-shadow-highlight: 0 10px 30px -4px rgba(99, 102, 241, 0.12), 0 0 0 1px rgba(99, 102, 241, 0.25);
      --btn-glass-bg: rgba(15, 23, 42, 0.04);
      --btn-glass-hover: rgba(15, 23, 42, 0.08);
      --btn-glass-border: rgba(15, 23, 42, 0.1);
      --terminal-bg: #0b1120;
      --terminal-border: rgba(15, 23, 42, 0.12);
      --table-border: rgba(15, 23, 42, 0.06);
      --code-box-bg: #f8fafc;
      --theme-toggle-bg: rgba(15, 23, 42, 0.05);
      --theme-toggle-border: rgba(15, 23, 42, 0.12);
      --font-display: 'Outfit', sans-serif;
      --font-body: 'Inter', sans-serif;
      --font-code: 'JetBrains Mono', monospace;
    }

    [data-theme="dark"] {
      --bg-base: #07090e;
      --bg-surface: rgba(13, 17, 28, 0.82);
      --bg-card: rgba(18, 24, 38, 0.9);
      --bg-elevated: rgba(26, 34, 52, 0.95);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-glow: rgba(99, 102, 241, 0.4);
      --text-main: #f8fafc;
      --text-dim: #94a3b8;
      --text-muted: #64748b;
      --primary: #6366f1;
      --primary-gradient: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #d946ef 100%);
      --neon-cyan: #06b6d4;
      --neon-emerald: #10b981;
      --accent-gradient: linear-gradient(135deg, #10b981 0%, #06b6d4 100%);
      --danger: #ef4444;
      --warning: #f59e0b;
      --input-bg: rgba(7, 9, 14, 0.7);
      --input-border: rgba(255, 255, 255, 0.12);
      --input-focus-border: #818cf8;
      --input-focus-shadow: rgba(99, 102, 241, 0.25);
      --header-bg: rgba(7, 9, 14, 0.88);
      --nav-bg: rgba(13, 17, 28, 0.7);
      --card-shadow: 0 10px 36px rgba(0, 0, 0, 0.45);
      --card-shadow-highlight: 0 0 32px rgba(99, 102, 241, 0.15);
      --btn-glass-bg: rgba(255, 255, 255, 0.05);
      --btn-glass-hover: rgba(255, 255, 255, 0.1);
      --btn-glass-border: rgba(255, 255, 255, 0.1);
      --terminal-bg: #030508;
      --terminal-border: rgba(255, 255, 255, 0.08);
      --table-border: rgba(255, 255, 255, 0.04);
      --code-box-bg: rgba(7, 9, 14, 0.7);
      --theme-toggle-bg: rgba(255, 255, 255, 0.06);
      --theme-toggle-border: rgba(255, 255, 255, 0.12);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: var(--font-body);
      background-color: var(--bg-base);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      overflow-x: hidden;
      transition: background-color 0.25s ease, color 0.25s ease;
    }

    /* HEADER */
    header {
      padding: 12px 28px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border-subtle);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      background: var(--header-bg);
      position: sticky;
      top: 0;
      z-index: 100;
      gap: 16px;
    }

    .brand-group {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-shrink: 0;
    }

    .logo-cube {
      width: 38px;
      height: 38px;
      background: var(--primary-gradient);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.2rem;
      font-weight: 900;
      color: #fff;
      box-shadow: 0 0 20px rgba(99, 102, 241, 0.45);
    }

    .brand-title {
      font-family: var(--font-display);
      font-size: 1.15rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: var(--text-main);
    }

    .brand-sub {
      font-size: 0.72rem;
      color: var(--text-dim);
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .pill-tag {
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      padding: 2px 7px;
      border-radius: 999px;
      background: rgba(99, 102, 241, 0.12);
      border: 1px solid rgba(99, 102, 241, 0.3);
      color: #6366f1;
    }

    [data-theme="dark"] .pill-tag {
      color: #a5b4fc;
      background: rgba(99, 102, 241, 0.15);
      border-color: rgba(99, 102, 241, 0.35);
    }

    /* INLINE STEPPER */
    .header-stepper {
      display: flex;
      align-items: center;
      gap: 6px;
      background: var(--btn-glass-bg);
      border: 1px solid var(--border-subtle);
      border-radius: 999px;
      padding: 4px 12px;
      overflow-x: auto;
    }

    .mini-step-node {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.74rem;
      font-weight: 600;
      color: var(--text-muted);
      white-space: nowrap;
      transition: all 0.2s ease;
    }

    .mini-step-node.active {
      color: var(--primary);
      font-weight: 700;
    }

    .mini-step-node.completed {
      color: #059669;
    }

    [data-theme="dark"] .mini-step-node.completed {
      color: #34d399;
    }

    .mini-step-circle {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: var(--btn-glass-border);
      color: var(--text-dim);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.68rem;
      font-weight: 800;
    }

    .mini-step-node.active .mini-step-circle {
      background: var(--primary-gradient);
      color: #fff;
      box-shadow: 0 0 10px rgba(99, 102, 241, 0.5);
    }

    .mini-step-node.completed .mini-step-circle {
      background: var(--accent-gradient);
      color: #fff;
    }

    .mini-step-arrow {
      color: var(--text-muted);
      font-size: 0.68rem;
      opacity: 0.6;
    }

    .header-right {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }

    /* THEME TOGGLE BUTTON */
    .theme-toggle-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      border-radius: 999px;
      font-family: var(--font-display);
      font-size: 0.78rem;
      font-weight: 700;
      cursor: pointer;
      background: var(--theme-toggle-bg);
      border: 1px solid var(--theme-toggle-border);
      color: var(--text-main);
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      user-select: none;
    }

    .theme-toggle-btn:hover {
      background: var(--btn-glass-hover);
      border-color: var(--primary);
      transform: translateY(-1px);
    }

    [data-theme="light"] .theme-toggle-btn .moon-icon { display: none; }
    [data-theme="light"] .theme-toggle-btn .sun-icon { display: inline-block; }
    [data-theme="dark"] .theme-toggle-btn .sun-icon { display: none; }
    [data-theme="dark"] .theme-toggle-btn .moon-icon { display: inline-block; }

    .account-badge {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 5px 14px;
      border-radius: 999px;
      font-size: 0.74rem;
      font-weight: 600;
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #059669;
    }

    [data-theme="dark"] .account-badge {
      color: #34d399;
    }

    .account-badge.offline {
      background: rgba(245, 158, 11, 0.1);
      border-color: rgba(245, 158, 11, 0.3);
      color: #d97706;
    }

    [data-theme="dark"] .account-badge.offline {
      color: #fbbf24;
    }

    .pulse-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: currentColor;
    }

    /* NAVIGATION TABS */
    .nav-bar {
      display: flex;
      gap: 6px;
      padding: 6px 28px 0 28px;
      border-bottom: 1px solid var(--border-subtle);
      background: var(--nav-bg);
    }

    .nav-tab-btn {
      padding: 9px 18px;
      background: transparent;
      border: none;
      color: var(--text-dim);
      font-family: var(--font-display);
      font-size: 0.86rem;
      font-weight: 600;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .nav-tab-btn:hover {
      color: var(--text-main);
    }

    .nav-tab-btn.active {
      color: var(--primary);
      border-bottom-color: var(--primary);
      font-weight: 700;
    }

    /* MAIN CONTENT */
    main {
      padding: 20px 28px;
      max-width: 1720px;
      margin: 0 auto;
      width: 100%;
      flex: 1;
    }

    .tab-content {
      display: none;
    }

    .tab-content.active {
      display: grid;
      grid-template-columns: 460px 1fr;
      gap: 20px;
      align-items: start;
    }

    .tab-content.full-width.active {
      display: block;
    }

    @media (max-width: 1100px) {
      .tab-content.active {
        grid-template-columns: 1fr;
      }
    }

    /* CARDS */
    .glass-card {
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 16px 18px;
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      box-shadow: var(--card-shadow);
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 16px;
      position: relative;
      transition: background 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
    }

    .glass-card.highlight {
      border-color: rgba(99, 102, 241, 0.35);
      box-shadow: var(--card-shadow-highlight);
    }

    .card-header-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border-subtle);
      padding-bottom: 10px;
    }

    .card-heading {
      font-family: var(--font-display);
      font-size: 0.95rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text-main);
    }

    /* FORM ELEMENTS */
    .form-row {
      display: flex;
      flex-direction: column;
      gap: 5px;
    }

    label {
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-dim);
    }

    input, select, textarea {
      width: 100%;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 8px;
      padding: 8px 12px;
      color: var(--text-main);
      font-family: var(--font-body);
      font-size: 0.85rem;
      transition: all 0.2s;
    }

    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--input-focus-border);
      box-shadow: 0 0 0 2px var(--input-focus-shadow);
    }

    textarea {
      resize: vertical;
      min-height: 72px;
      line-height: 1.4;
    }

    .grid-2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    /* BUTTONS */
    .btn {
      padding: 8px 14px;
      border-radius: 8px;
      font-family: var(--font-display);
      font-size: 0.82rem;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: all 0.2s;
      border: none;
    }

    .btn-glow-primary {
      background: var(--primary-gradient);
      color: #fff;
      box-shadow: 0 3px 14px rgba(99, 102, 241, 0.35);
    }

    .btn-glow-primary:hover {
      transform: translateY(-1px);
      box-shadow: 0 5px 20px rgba(99, 102, 241, 0.5);
    }

    .btn-glow-accent {
      background: var(--accent-gradient);
      color: #fff;
      box-shadow: 0 3px 14px rgba(16, 185, 129, 0.3);
    }

    .btn-glow-accent:hover {
      transform: translateY(-1px);
      box-shadow: 0 5px 20px rgba(16, 185, 129, 0.45);
    }

    .btn-glass {
      background: var(--btn-glass-bg);
      color: var(--text-main);
      border: 1px solid var(--btn-glass-border);
    }

    .btn-glass:hover {
      background: var(--btn-glass-hover);
      border-color: var(--border-glow);
    }

    .btn-danger {
      background: rgba(239, 68, 68, 0.12);
      color: #dc2626;
      border: 1px solid rgba(239, 68, 68, 0.25);
    }

    [data-theme="dark"] .btn-danger {
      background: rgba(239, 68, 68, 0.15);
      color: #f87171;
      border-color: rgba(239, 68, 68, 0.3);
    }

    .btn-danger:hover {
      background: rgba(239, 68, 68, 0.22);
    }

    .btn-icon {
      padding: 5px 9px;
      font-size: 0.78rem;
      border-radius: 7px;
    }

    .btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    /* HITL PLAN BANNER & CARDS */
    .hitl-status-banner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px;
      background: rgba(99, 102, 241, 0.08);
      border: 1px solid rgba(99, 102, 241, 0.2);
      border-radius: 8px;
      gap: 8px;
    }

    .hitl-task-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: 10px;
      padding: 9px 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      transition: all 0.2s ease;
      position: relative;
    }

    .hitl-task-card:hover {
      border-color: rgba(99, 102, 241, 0.3);
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
    }

    .hitl-task-card.active-step {
      border-color: #6366f1;
      background: rgba(99, 102, 241, 0.06);
    }

    .hitl-task-card.completed-step {
      border-color: rgba(16, 185, 129, 0.35);
      background: rgba(16, 185, 129, 0.04);
    }

    .task-num-circle {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: rgba(99, 102, 241, 0.12);
      border: 1px solid rgba(99, 102, 241, 0.28);
      color: var(--primary);
      font-size: 0.72rem;
      font-weight: 800;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .hitl-task-card.completed-step .task-num-circle {
      background: rgba(16, 185, 129, 0.15);
      border-color: rgba(16, 185, 129, 0.4);
      color: #059669;
    }

    [data-theme="dark"] .hitl-task-card.completed-step .task-num-circle {
      color: #34d399;
    }

    .task-title-input {
      font-family: var(--font-display);
      font-weight: 700;
      font-size: 0.84rem;
      padding: 4px 6px;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 5px;
      color: var(--text-main);
    }

    .task-title-input:hover, .task-title-input:focus {
      background: var(--input-bg);
      border-color: var(--input-border);
    }

    .task-desc-input {
      font-size: 0.75rem;
      min-height: 32px;
      max-height: 70px;
      padding: 5px 6px;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 5px;
      color: var(--text-dim);
      resize: vertical;
      line-height: 1.35;
    }

    .tool-chip {
      font-family: var(--font-code);
      font-size: 0.65rem;
      background: rgba(99, 102, 241, 0.1);
      color: var(--primary);
      padding: 2px 6px;
      border-radius: 5px;
      border: 1px solid rgba(99, 102, 241, 0.2);
    }

    [data-theme="dark"] .tool-chip {
      color: #a5b4fc;
      background: rgba(99, 102, 241, 0.15);
      border-color: rgba(99, 102, 241, 0.3);
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 0.68rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .status-badge.completed { background: rgba(16, 185, 129, 0.15); color: #059669; border: 1px solid rgba(16, 185, 129, 0.4); }
    [data-theme="dark"] .status-badge.completed { color: #34d399; }
    .status-badge.in_progress { background: rgba(99, 102, 241, 0.15); color: #6366f1; border: 1px solid rgba(99, 102, 241, 0.4); }
    [data-theme="dark"] .status-badge.in_progress { color: #818cf8; }
    .status-badge.pending { background: rgba(245, 158, 11, 0.15); color: #d97706; border: 1px solid rgba(245, 158, 11, 0.4); }
    [data-theme="dark"] .status-badge.pending { color: #fbbf24; }
    .status-badge.approved { background: rgba(16, 185, 129, 0.2); color: #059669; border: 1px solid #10b981; }
    [data-theme="dark"] .status-badge.approved { color: #10b981; }
    .status-badge.failed { background: rgba(239, 68, 68, 0.15); color: #dc2626; border: 1px solid rgba(239, 68, 68, 0.4); }
    [data-theme="dark"] .status-badge.failed { color: #f87171; }
    .status-badge.editing { background: rgba(99, 102, 241, 0.2); color: #6366f1; border: 1px solid #6366f1; }
    [data-theme="dark"] .status-badge.editing { color: #a5b4fc; border-color: #818cf8; }

    /* PROGRESS TRACKER */
    .progress-bar-wrap {
      background: var(--input-border);
      border-radius: 6px;
      height: 6px;
      overflow: hidden;
      margin: 6px 0;
    }

    .progress-bar-fill {
      height: 100%;
      width: 0%;
      background: var(--accent-gradient);
      transition: width 0.35s ease;
      box-shadow: 0 0 10px rgba(16, 185, 129, 0.6);
    }

    .logs-terminal {
      background: var(--terminal-bg);
      border: 1px solid var(--terminal-border);
      border-radius: 10px;
      padding: 10px 12px;
      font-family: var(--font-code);
      font-size: 0.75rem;
      max-height: 180px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .log-row { color: #94a3b8; line-height: 1.35; }
    .log-row.success { color: #34d399; }
    .log-row.error { color: #f87171; }
    .log-row.info { color: #818cf8; }

    /* RICH TEXT EDITOR TOOLBAR */
    .editor-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 5px;
      padding: 6px 10px;
      background: var(--bg-elevated);
      border: 1px solid var(--border-glow);
      border-radius: 8px;
      margin-bottom: 10px;
    }

    .editor-btn {
      background: var(--btn-glass-bg);
      border: 1px solid var(--btn-glass-border);
      color: var(--text-main);
      padding: 4px 8px;
      border-radius: 5px;
      font-family: var(--font-display);
      font-size: 0.74rem;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s ease;
    }

    .editor-btn:hover {
      background: var(--primary);
      color: #fff;
      border-color: var(--primary);
    }

    .editor-divider {
      width: 1px;
      height: 16px;
      background: var(--border-subtle);
      margin: 0 2px;
    }

    /* DOCUMENT PREVIEW WORKSPACE */
    .document-preview-workspace {
      background: #ffffff;
      color: #1e293b;
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 28px 36px;
      min-height: 460px;
      max-height: 640px;
      overflow-y: auto;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.6;
      box-shadow: inset 0 2px 8px rgba(0,0,0,0.03);
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }

    .document-preview-workspace.editing {
      border-color: var(--primary);
      box-shadow: 0 0 0 2px var(--input-focus-shadow), inset 0 2px 8px rgba(0,0,0,0.03);
      outline: none;
      cursor: text;
    }

    .document-preview-workspace h1 { font-size: 1.8rem; margin-bottom: 0.9rem; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; font-family: var(--font-display); font-weight: 800; }
    .document-preview-workspace h2 { font-size: 1.3rem; margin-top: 1.3rem; margin-bottom: 0.7rem; color: #1e293b; font-family: var(--font-display); font-weight: 700; }
    .document-preview-workspace h3 { font-size: 1.1rem; margin-top: 1.1rem; margin-bottom: 0.5rem; color: #334155; font-family: var(--font-display); font-weight: 700; }
    .document-preview-workspace p { margin-bottom: 0.9rem; color: #334155; }
    .document-preview-workspace ul, .document-preview-workspace ol { margin-left: 1.5rem; margin-bottom: 0.9rem; color: #334155; }
    .document-preview-workspace table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; font-size: 0.85rem; }
    .document-preview-workspace th, .document-preview-workspace td { border: 1px solid #cbd5e1; padding: 8px 12px; text-align: left; }
    .document-preview-workspace th { background: #f1f5f9; font-weight: 700; }

    /* QUICK CHIPS FOR AI EDIT */
    .quick-chips-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 5px;
      margin-top: 5px;
    }

    .quick-chip-label {
      font-size: 0.68rem;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .quick-chip {
      background: var(--btn-glass-bg);
      border: 1px solid var(--btn-glass-border);
      color: var(--text-dim);
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
    }

    .quick-chip:hover {
      background: rgba(99, 102, 241, 0.12);
      border-color: var(--border-glow);
      color: var(--primary);
    }

    /* TOAST NOTIFICATION */
    #uiToast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      padding: 10px 18px;
      background: var(--bg-card);
      border: 1px solid var(--border-glow);
      border-radius: 10px;
      color: var(--text-main);
      font-family: var(--font-display);
      font-size: 0.82rem;
      font-weight: 700;
      box-shadow: 0 10px 30px rgba(0,0,0,0.18);
      display: none;
      z-index: 9999;
    }

    /* TABLES */
    .data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }

    .data-table th {
      text-align: left;
      padding: 9px 12px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--text-dim);
      font-weight: 700;
      text-transform: uppercase;
      font-size: 0.7rem;
    }

    .data-table td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--table-border);
    }

    .spinner {
      display: inline-block;
      width: 13px;
      height: 13px;
      border: 2px solid rgba(255,255,255,0.3);
      border-radius: 50%;
      border-top-color: #fff;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  </style>
</head>
<body>

  <!-- TOAST NOTIFICATION -->
  <div id="uiToast"></div>

  <!-- HEADER -->
  <header>
    <div class="brand-group">
      <div class="logo-cube">⚡</div>
      <div>
        <div class="brand-title">SuperDocs Studio</div>
        <div class="brand-sub">
          <span>Agentic Task Engine</span>
          <span class="pill-tag">HITL Gate</span>
        </div>
      </div>
    </div>

    <!-- STREAMLINED INLINE STEPPER -->
    <div class="header-stepper">
      <div class="mini-step-node active" id="stepNode1">
        <span class="mini-step-circle">1</span>
        <span>Intent</span>
      </div>
      <span class="mini-step-arrow">➔</span>
      <div class="mini-step-node" id="stepNode2">
        <span class="mini-step-circle">2</span>
        <span>Synthesis</span>
      </div>
      <span class="mini-step-arrow">➔</span>
      <div class="mini-step-node" id="stepNode3">
        <span class="mini-step-circle">3</span>
        <span>HITL Gate</span>
      </div>
      <span class="mini-step-arrow">➔</span>
      <div class="mini-step-node" id="stepNode4">
        <span class="mini-step-circle">4</span>
        <span>Cloud Execution</span>
      </div>
      <span class="mini-step-arrow">➔</span>
      <div class="mini-step-node" id="stepNode5">
        <span class="mini-step-circle">5</span>
        <span>Delivery</span>
      </div>
    </div>

    <div class="header-right">
      <div id="accountStatusBadge" class="account-badge">
        <span class="pulse-dot"></span>
        <span id="accountInfoText">Connecting to SuperDocs...</span>
      </div>
      <button id="themeToggleBtn" class="theme-toggle-btn" onclick="toggleTheme()" title="Toggle Light/Dark Mode" aria-label="Toggle Theme">
        <span class="theme-icon sun-icon">☀️</span>
        <span class="theme-icon moon-icon">🌙</span>
        <span class="theme-label" id="themeLabelText">Light</span>
      </button>
      <button class="btn btn-glass btn-icon" onclick="refreshAccountStatus()">↻</button>
    </div>
  </header>

  <!-- NAVIGATION TABS -->
  <div class="nav-bar">
    <button class="nav-tab-btn active" onclick="switchTab('tasksTab')">⚡ Live Dynamic Studio</button>
    <button class="nav-tab-btn" onclick="switchTab('planTab')">📋 HITL Decomposition Studio</button>
    <button class="nav-tab-btn" onclick="switchTab('jobsTab')">📊 Cloud Job Queue</button>
    <button class="nav-tab-btn" onclick="switchTab('docsTab')">📁 Saved Documents</button>
    <button class="nav-tab-btn" onclick="switchTab('agentTab')">🤖 LangGraph Multi-Node Agent</button>
  </div>

  <!-- MAIN VIEWPORT -->
  <main>
    <!-- TAB 1: Live Studio -->
    <div id="tasksTab" class="tab-content active">
      
      <!-- LEFT CONTROLLER PANE -->
      <div class="left-panel">
        
        <!-- CARD 1: OBJECTIVE -->
        <div class="glass-card">
          <div class="card-header-bar">
            <div class="card-heading">🎯 Document Objective</div>
            <span class="pill-tag">AI Planning Engine</span>
          </div>

          <div class="form-row">
            <label>Session Context</label>
            <div style="display: flex; gap: 6px;">
              <input type="text" id="taskSessionId" value="plan-session-1">
              <button class="btn btn-glass btn-icon" title="Generate New Session" onclick="generateNewSessionId()">🎲</button>
            </div>
          </div>

          <div class="form-row">
            <label>Goal Prompt</label>
            <textarea id="taskPrompt" placeholder="Describe the document to synthesize...">Draft a Multi-Cloud Disaster Recovery Runbook for fintech services with: 1. RTO/RPO objectives and failover triggers, 2. AWS to GCP database replication & DNS cutover, 3. Regulatory compliance checklist and post-incident review.</textarea>
          </div>

          <div class="grid-2">
            <div class="form-row">
              <label>Model Tier</label>
              <select id="taskModelTier">
                <option value="core" selected>Core (Balanced)</option>
                <option value="turbo">Turbo (Low Latency)</option>
                <option value="pro">Pro (Reasoning)</option>
                <option value="max">Max (Deep)</option>
              </select>
            </div>
            <div class="form-row">
              <label>Thinking Depth</label>
              <select id="taskThinkingDepth">
                <option value="balanced" selected>Balanced</option>
                <option value="fast">Fast</option>
                <option value="deep">Deep</option>
              </select>
            </div>
          </div>

          <button id="btnSynthesizePlan" class="btn btn-glow-primary" onclick="generateDynamicPlanFromPrompt()">
            <span>🔮 Synthesize Dynamic Plan</span>
          </button>
        </div>

        <!-- CARD 2: HITL PLAN GATE -->
        <div class="glass-card highlight">
          <div class="card-header-bar">
            <div>
              <div class="card-heading">📋 HITL Task Plan Gate</div>
              <div id="planMetaSubtitle" style="font-size: 0.72rem; color: var(--text-dim); margin-top: 2px;">Review, customize & approve prompt-specific subtasks</div>
            </div>
            <span id="planApprovalBadge" class="status-badge pending">AWAITING APPROVAL</span>
          </div>

          <div id="hitlPlanMetadata" class="hitl-status-banner" style="display: none;">
            <div>
              <div style="font-weight: 800; font-size: 0.82rem; color: #a5b4fc;" id="metaDocType">Custom Document</div>
              <div style="font-size: 0.72rem; color: var(--text-dim); margin-top: 2px;" id="metaRationale">Decomposition generated by SuperDocs AI.</div>
            </div>
            <span id="metaComplexityBadge" class="status-badge pending">COMPLEX PLAN</span>
          </div>

          <!-- Dynamic Task List Container -->
          <div id="hitlTaskListContainer" style="display: flex; flex-direction: column; gap: 8px; max-height: 380px; overflow-y: auto; padding-right: 4px;">
            <div style="text-align: center; color: var(--text-muted); padding: 20px; font-size: 0.82rem;">
              Click <strong>"🔮 Synthesize Dynamic Plan"</strong> above to decompose into subtasks.
            </div>
          </div>

          <!-- Action Controls -->
          <div style="display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--border-subtle); padding-top: 10px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div style="display: flex; gap: 6px;">
                <button class="btn btn-glass btn-icon" onclick="addNewSubtask()">➕ Add Subtask</button>
                <button class="btn btn-glass btn-icon" onclick="generateDynamicPlanFromPrompt()">↺ Reset</button>
              </div>
              <span id="taskCountPill" class="pill-tag">0 Tasks</span>
            </div>
            <button id="btnApproveAndExecute" class="btn btn-glow-accent" onclick="approveAndExecutePlan()">
              <span>🚀 Approve & Execute Plan</span>
            </button>
          </div>
        </div>

        <!-- CARD 3: EXECUTION TRACE -->
        <div class="glass-card">
          <div class="card-header-bar">
            <div class="card-heading">📡 Live Execution Trace</div>
            <span id="currentJobStatusBadge" class="status-badge pending">IDLE</span>
          </div>

          <div>
            <div style="display: flex; justify-content: space-between; font-size: 0.74rem; color: var(--text-dim);">
              <span id="progressStepText">Ready</span>
              <span id="progressPercentText">0%</span>
            </div>
            <div class="progress-bar-wrap">
              <div id="taskProgressBar" class="progress-bar-fill"></div>
            </div>
          </div>

          <div id="liveTaskLogs" class="logs-terminal">
            <div class="log-row">[Ready] Configure objective and click 'Synthesize Dynamic Plan'.</div>
          </div>
        </div>

      </div>

      <!-- RIGHT STAGE: DOCUMENT WORKSPACE & DELIVERABLES -->
      <div class="right-panel">
        <div class="glass-card" style="margin-bottom: 0;">
          <div class="card-header-bar">
            <div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <div class="card-heading">📄 Document Studio & Live Deliverables</div>
                <span id="docEditStatusBadge" class="status-badge editing" style="display: none;">✏️ EDIT MODE</span>
              </div>
              <div id="docMetaSubtitle" style="font-size: 0.72rem; color: var(--text-dim); margin-top: 2px;">Session: None</div>
            </div>
            <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
              <!-- Direct In-Place Edit Controls -->
              <button id="btnToggleDirectEdit" class="btn btn-glass btn-icon" onclick="toggleDirectEditMode()" title="Toggle direct in-place rich text editing">
                <span id="btnToggleDirectEditIcon">✏️</span> <span id="btnToggleDirectEditText">Edit Document</span>
              </button>
              <button id="btnSaveDirectEdit" class="btn btn-glow-accent btn-icon" onclick="saveDirectEdits()" style="display: none;" title="Save edits to SuperDocs">
                💾 Save
              </button>
              <button id="btnCancelDirectEdit" class="btn btn-glass btn-icon" onclick="cancelDirectEdits()" style="display: none;" title="Cancel edits">
                ❌ Cancel
              </button>

              <span style="color: var(--border-subtle); margin: 0 2px;">|</span>

              <!-- Export Controls -->
              <button class="btn btn-glass btn-icon" onclick="exportCurrentDoc('docx')" title="Export Word (.docx)">📥 DOCX</button>
              <button class="btn btn-glass btn-icon" onclick="exportCurrentDoc('pdf')" title="Export PDF (.pdf)">📥 PDF</button>
              <button class="btn btn-glass btn-icon" onclick="exportCurrentDoc('markdown')" title="Export Markdown (.md)">📥 MD</button>
              <button class="btn btn-glass btn-icon" onclick="exportCurrentDoc('html')" title="Export HTML (.html)">📥 HTML</button>
            </div>
          </div>

          <!-- Rich Text Formatting Toolbar (Visible in Edit Mode) -->
          <div id="richEditorToolbar" class="editor-toolbar" style="display: none;">
            <button class="editor-btn" onclick="formatDoc('bold')" title="Bold (Ctrl+B)"><b>B</b></button>
            <button class="editor-btn" onclick="formatDoc('italic')" title="Italic (Ctrl+I)"><i>I</i></button>
            <button class="editor-btn" onclick="formatDoc('underline')" title="Underline (Ctrl+U)"><u>U</u></button>
            <div class="editor-divider"></div>
            <button class="editor-btn" onclick="formatBlock('h1')" title="Heading 1">H1</button>
            <button class="editor-btn" onclick="formatBlock('h2')" title="Heading 2">H2</button>
            <button class="editor-btn" onclick="formatBlock('h3')" title="Heading 3">H3</button>
            <button class="editor-btn" onclick="formatBlock('p')" title="Paragraph">P</button>
            <div class="editor-divider"></div>
            <button class="editor-btn" onclick="formatDoc('insertUnorderedList')" title="Bullet List">• List</button>
            <button class="editor-btn" onclick="formatDoc('insertOrderedList')" title="Numbered List">1. List</button>
            <button class="editor-btn" onclick="formatBlock('blockquote')" title="Blockquote">❝ Quote</button>
            <button class="editor-btn" onclick="insertTableAtCursor()" title="Insert Table">📊 Table</button>
            <div class="editor-divider"></div>
            <button class="editor-btn" onclick="formatDoc('removeFormat')" title="Clear Formatting">🧹 Clear</button>
            <span style="font-size: 0.7rem; color: var(--primary); font-weight: 700; margin-left: auto;">✏️ Click content to edit directly</span>
          </div>

          <!-- Editable Document Workspace -->
          <div id="documentPreviewArea" class="document-preview-workspace" spellcheck="false">
            <div style="text-align: center; color: #94a3b8; padding-top: 130px;">
              <h2 style="font-family: var(--font-display);">No Document Loaded</h2>
              <p>Execute an approved task plan or click <strong>"✏️ Edit Document"</strong> to start writing directly.</p>
            </div>
          </div>

          <!-- AI Prompt-Based Revision / Surgical Edit Bar -->
          <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 10px; padding: 10px 12px; margin-top: 10px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <span style="font-weight: 700; font-size: 0.76rem; color: var(--text-main); display: flex; align-items: center; gap: 6px;">
                <span>💬 Prompt-Based Document Revision & Surgical Edit</span>
              </span>
              <span class="pill-tag">AI Surgical Edit</span>
            </div>
            <div style="display: flex; gap: 6px;">
              <input type="text" id="aiRevisionPromptInput" placeholder="Describe the edit to apply (e.g. 'Add a disaster recovery test schedule', 'Make tone executive')..." style="flex: 1;">
              <button id="btnApplyAiEdit" class="btn btn-glow-primary" onclick="applyAiDocumentRevision()">
                <span>✨ Apply AI Edit</span>
              </button>
            </div>
            <div class="quick-chips-row">
              <span class="quick-chip-label">Quick Presets:</span>
              <button class="quick-chip" onclick="setAiPrompt('Add an Executive Summary section at the top')">+ Executive Summary</button>
              <button class="quick-chip" onclick="setAiPrompt('Add a Key Metrics and SLA Performance Table')">📊 Add SLA Table</button>
              <button class="quick-chip" onclick="setAiPrompt('Add a Security, Compliance & Risk Mitigation section')">🛡️ Add Security Section</button>
              <button class="quick-chip" onclick="setAiPrompt('Refine formatting, polish tone, and make headings professional')">✨ Polish & Formalize</button>
            </div>
          </div>

          <div style="display: flex; justify-content: space-between; font-size: 0.74rem; color: var(--text-muted); border-top: 1px solid var(--border-subtle); padding-top: 8px; margin-top: 8px;">
            <span id="docChangesSummary">Changes: None</span>
            <span id="docUsageSummary">Monthly Ops Remaining: --</span>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 2: Full Decomposition Studio -->
    <div id="planTab" class="tab-content full-width">
      <div class="glass-card">
        <div class="card-header-bar">
          <div>
            <div class="card-heading">📋 Dynamic HITL Plan Studio & Decomposition</div>
            <div style="font-size: 0.74rem; color: var(--text-dim); margin-top: 2px;">Inspect, edit subtasks, customize tools, reorder, and approve prompt-specific subtasks.</div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-glass btn-icon" onclick="addNewSubtask()">➕ Add Subtask</button>
            <button class="btn btn-glass btn-icon" onclick="generateDynamicPlanFromPrompt()">⚡ Regenerate Plan</button>
            <button class="btn btn-glow-primary btn-icon" onclick="executeFromStudioTab()">🚀 Approve & Run Plan</button>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-top: 14px;" id="dedicatedPlanGrid">
          <div style="text-align: center; color: var(--text-muted); padding: 48px; grid-column: 1 / -1;">
            No plan synthesized yet. Click <strong>"⚡ Regenerate Plan"</strong> or synthesize from the Live Dynamic Studio.
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 3: Job Queue Monitor -->
    <div id="jobsTab" class="tab-content full-width">
      <div class="glass-card">
        <div class="card-header-bar">
          <div class="card-heading">📊 SuperDocs Asynchronous Job Queue (/v1/jobs)</div>
          <button class="btn btn-glass btn-icon" onclick="loadJobsTable()">↻ Refresh Queue</button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Job ID</th>
              <th>Session ID</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Created At</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="jobsTableBody">
            <tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 24px;">Loading SuperDocs async jobs...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 4: Saved Documents -->
    <div id="docsTab" class="tab-content full-width">
      <div class="glass-card">
        <div class="card-header-bar">
          <div class="card-heading">📁 Durable Saved Documents (Files View)</div>
          <button class="btn btn-glass btn-icon" onclick="loadDocumentsTable()">↻ Refresh Documents</button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Document ID</th>
              <th>Title</th>
              <th>Source</th>
              <th>Version</th>
              <th>Chats / Sessions</th>
              <th>Updated</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="docsTableBody">
            <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">Loading saved documents from SuperDocs account...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 5: LangGraph Multi-Node Agent -->
    <div id="agentTab" class="tab-content">
      <div class="left-panel">
        <div class="glass-card">
          <div class="card-header-bar">
            <div class="card-heading">🤖 LangGraph Multi-Node Document Agent</div>
          </div>
          <div class="form-row">
            <label>Agent Objective / High-Level Goal</label>
            <textarea id="agentGoal" placeholder="Describe the goal for the autonomous agent...">Create a production-grade Technical Architecture Specification for an AI document agent with LangGraph StateGraph, SuperDocs REST client, and automated section verification.</textarea>
          </div>
          <div class="form-row">
            <label>Target Export Format</label>
            <select id="agentExportFormat">
              <option value="markdown" selected>Markdown (.md)</option>
              <option value="html">HTML (.html)</option>
              <option value="docx">Word (.docx)</option>
            </select>
          </div>
          <button id="btnRunAgent" class="btn btn-glow-primary" style="margin-top: 8px;" onclick="runLangGraphAgent()">
            <span>⚡ Launch Autonomous LangGraph Agent</span>
          </button>
        </div>

        <div class="glass-card">
          <div class="card-header-bar">
            <div class="card-heading">📋 Autonomous Task Checklist</div>
            <span id="agentStatusBadge" class="status-badge pending">IDLE</span>
          </div>
          <div id="agentTaskChecklist" style="display: flex; flex-direction: column; gap: 6px; font-size: 0.8rem;">
            <div style="color: var(--text-muted);">Tasks will populate upon agent launch.</div>
          </div>
        </div>
      </div>

      <div class="right-panel">
        <div class="glass-card" style="margin-bottom: 0;">
          <div class="card-header-bar">
            <div class="card-heading">📜 Agent Execution Trace & Output</div>
          </div>
          <div id="agentTraceLogs" class="logs-terminal" style="max-height: 240px; margin-bottom: 12px;">
            <div class="log-row">Awaiting agent execution...</div>
          </div>
          <div class="card-header-bar" style="border-top: 1px solid var(--border-subtle); padding-top: 10px;">
            <div class="card-heading">📄 Final Generated Document</div>
          </div>
          <div id="agentFinalOutput" class="document-preview-workspace" style="min-height: 260px;">
            <p style="color: #94a3b8;">Agent output will appear here.</p>
          </div>
        </div>
      </div>
    </div>
  </main>

  <script>
    let currentDocumentHtml = '';
    let currentActiveSession = '';
    let currentDynamicPlan = null;
    let isDirectEditing = false;

    function showToast(msg, duration = 3000) {
      const toast = document.getElementById('uiToast');
      if (!toast) return;
      toast.innerText = msg;
      toast.style.display = 'block';
      setTimeout(() => { toast.style.display = 'none'; }, duration);
    }

    function initTheme() {
      const savedTheme = localStorage.getItem('superdocs_theme') || 'light';
      applyTheme(savedTheme);
    }

    function toggleTheme() {
      const current = document.documentElement.getAttribute('data-theme') || 'light';
      const next = current === 'light' ? 'dark' : 'light';
      applyTheme(next);
      localStorage.setItem('superdocs_theme', next);
    }

    function applyTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      const label = document.getElementById('themeLabelText');
      if (label) {
        label.innerText = theme === 'light' ? 'Light' : 'Dark';
      }
    }

    window.onload = function() {
      initTheme();
      refreshAccountStatus();
      loadJobsTable();
      loadDocumentsTable();
    };

    function setStepNode(stepIndex) {
      for (let i = 1; i <= 5; i++) {
        const node = document.getElementById(`stepNode${i}`);
        if (!node) continue;
        node.className = 'mini-step-node';
        if (i < stepIndex) node.className = 'mini-step-node completed';
        else if (i === stepIndex) node.className = 'mini-step-node active';
      }
    }

    function switchTab(tabId) {
      document.querySelectorAll('.nav-tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(p => p.classList.remove('active'));
      if (event && event.target) {
        const btn = event.target.closest('.nav-tab-btn') || event.target;
        btn.classList.add('active');
      }
      const target = document.getElementById(tabId);
      if (target) target.classList.add('active');

      if (tabId === 'planTab' && currentDynamicPlan) renderDedicatedTaskPlan(currentDynamicPlan);
      if (tabId === 'jobsTab') loadJobsTable();
      if (tabId === 'docsTab') loadDocumentsTable();
    }

    function generateNewSessionId() {
      const id = 'plan-sess-' + Math.random().toString(36).substring(2, 9);
      document.getElementById('taskSessionId').value = id;
    }

    async function generateDynamicPlanFromPrompt() {
      const prompt = document.getElementById('taskPrompt').value.trim();
      const sessionId = document.getElementById('taskSessionId').value.trim() || 'dynamic-session';
      const modelTier = document.getElementById('taskModelTier').value;
      const thinkingDepth = document.getElementById('taskThinkingDepth').value;
      const btn = document.getElementById('btnSynthesizePlan');

      setStepNode(1);
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Analyzing & Synthesizing...';
      addLog(`Analyzing prompt complexity and generating dynamic tasks...`, 'info');

      try {
        setStepNode(2);
        const res = await fetch('/api/dynamic-plan/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: prompt,
            session_id: sessionId,
            model_tier: modelTier,
            thinking_depth: thinkingDepth,
          })
        });
        const data = await res.json();
        if (data.success && data.data) {
          currentDynamicPlan = data.data;
          renderHITLPlan(currentDynamicPlan);
          renderDedicatedTaskPlan(currentDynamicPlan);
          setStepNode(3);
          addLog(`Dynamic plan synthesized: ${currentDynamicPlan.tasks.length} prompt-specific tasks ready for HITL approval.`, 'success');
        } else {
          addLog(`Planning failed: ${data.message || 'Unknown error'}`, 'error');
        }
      } catch (e) {
        addLog(`Error synthesizing plan: ${e.message}`, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>🔮 Synthesize Dynamic Plan</span>';
      }
    }

    function renderHITLPlan(plan) {
      if (!plan) return;

      const banner = document.getElementById('hitlPlanMetadata');
      const docTypeSpan = document.getElementById('metaDocType');
      const rationaleSpan = document.getElementById('metaRationale');
      const complexityBadge = document.getElementById('metaComplexityBadge');
      const approvalBadge = document.getElementById('planApprovalBadge');
      const container = document.getElementById('hitlTaskListContainer');
      const countPill = document.getElementById('taskCountPill');

      banner.style.display = 'flex';
      docTypeSpan.innerText = `📄 ${plan.document_type || 'Custom Document'}`;
      rationaleSpan.innerText = plan.decision_rationale || 'Decomposition generated by SuperDocs AI.';
      
      complexityBadge.className = `status-badge ${plan.is_complex ? 'pending' : 'completed'}`;
      complexityBadge.innerText = plan.is_complex ? 'COMPLEX' : 'DIRECT';

      approvalBadge.className = `status-badge ${plan.approval_status === 'approved' ? 'approved' : 'pending'}`;
      approvalBadge.innerText = plan.approval_status === 'approved' ? 'APPROVED' : 'AWAITING APPROVAL';

      if (countPill) countPill.innerText = `${plan.tasks.length} Subtasks`;

      container.innerHTML = plan.tasks.map((task, idx) => {
        let numDisplay = `${idx + 1}`;
        if (task.status === 'completed') numDisplay = '✓';
        else if (task.status === 'in_progress') numDisplay = '⟳';

        return `
        <div class="hitl-task-card ${task.status === 'in_progress' ? 'active-step' : ''} ${task.status === 'completed' ? 'completed-step' : ''}" id="hitl-card-${idx}">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px;">
            <div style="display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0;">
              <span class="task-num-circle">${numDisplay}</span>
              <input type="text" class="task-title-input" value="${escapeHtml(task.title)}" onchange="updateSubtaskField(${idx}, 'title', this.value)" placeholder="Subtask title..." style="flex: 1;">
            </div>
            <div style="display: flex; align-items: center; gap: 4px; flex-shrink: 0;">
              <span class="status-badge ${task.status}" id="hitl-badge-${idx}">${task.status.replace('_', ' ').toUpperCase()}</span>
              <button class="btn btn-glass btn-icon" title="Move Up" onclick="moveSubtask(${idx}, -1)" ${idx === 0 ? 'disabled' : ''} style="padding: 2px 5px; font-size: 0.68rem;">▲</button>
              <button class="btn btn-glass btn-icon" title="Move Down" onclick="moveSubtask(${idx}, 1)" ${idx === plan.tasks.length - 1 ? 'disabled' : ''} style="padding: 2px 5px; font-size: 0.68rem;">▼</button>
              <button class="btn btn-danger btn-icon" title="Delete Task" onclick="deleteSubtask(${idx})" style="padding: 2px 5px; font-size: 0.68rem;">🗑</button>
            </div>
          </div>
          <textarea class="task-desc-input" onchange="updateSubtaskField(${idx}, 'description', this.value)" placeholder="Task description and objectives...">${escapeHtml(task.description || '')}</textarea>
          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.68rem; color: var(--text-muted);">
            <div style="display: flex; gap: 4px; align-items: center;">
              <select onchange="updateSubtaskField(${idx}, 'tool', this.value)" style="font-family: var(--font-code); font-size: 0.65rem; padding: 2px 5px; border-radius: 5px;">
                <option value="superdocs_create_document" ${task.tool === 'superdocs_create_document' ? 'selected' : ''}>⚡ create_doc</option>
                <option value="superdocs_edit_section" ${task.tool === 'superdocs_edit_section' ? 'selected' : ''}>⚡ edit_section</option>
                <option value="superdocs_create_task" ${task.tool === 'superdocs_create_task' ? 'selected' : ''}>⚡ create_task</option>
                <option value="superdocs_render_template" ${task.tool === 'superdocs_render_template' ? 'selected' : ''}>⚡ template</option>
                <option value="superdocs_search" ${task.tool === 'superdocs_search' ? 'selected' : ''}>⚡ search</option>
              </select>
              <span>•</span>
              <span style="color: var(--text-dim); font-weight: 500;">${task.phase || 'Drafting'}</span>
            </div>
            <span>Est: ${task.estimated_time || '5-10s'}</span>
          </div>
        </div>
      `;
      }).join('');
    }

    function renderDedicatedTaskPlan(plan) {
      const grid = document.getElementById('dedicatedPlanGrid');
      if (!grid) return;
      if (!plan || !plan.tasks || plan.tasks.length === 0) {
        grid.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 48px; grid-column: 1 / -1;">No subtasks present. Click <strong>"➕ Add Subtask"</strong> to create one.</div>';
        return;
      }
      grid.innerHTML = plan.tasks.map((task, idx) => {
        let numDisplay = `${idx + 1}`;
        if (task.status === 'completed') numDisplay = '✓';
        else if (task.status === 'in_progress') numDisplay = '⟳';

        return `
        <div class="glass-card" style="margin-bottom: 0; display: flex; flex-direction: column; gap: 8px;">
          <div class="card-header-bar">
            <div style="display: flex; align-items: center; gap: 6px;">
              <span class="task-num-circle">${numDisplay}</span>
              <strong>${task.id || `TASK-${idx + 1}`}</strong>
            </div>
            <div style="display: flex; align-items: center; gap: 4px;">
              <span class="status-badge ${task.status}">${task.status.replace('_', ' ').toUpperCase()}</span>
              <button class="btn btn-glass btn-icon" title="Move Up" onclick="moveSubtask(${idx}, -1)" ${idx === 0 ? 'disabled' : ''} style="padding: 2px 5px; font-size: 0.68rem;">▲</button>
              <button class="btn btn-glass btn-icon" title="Move Down" onclick="moveSubtask(${idx}, 1)" ${idx === plan.tasks.length - 1 ? 'disabled' : ''} style="padding: 2px 5px; font-size: 0.68rem;">▼</button>
              <button class="btn btn-danger btn-icon" title="Delete Task" onclick="deleteSubtask(${idx})" style="padding: 2px 5px; font-size: 0.68rem;">🗑</button>
            </div>
          </div>

          <div class="form-row" style="margin-bottom: 0;">
            <label style="font-size: 0.68rem;">Task Title</label>
            <input type="text" value="${escapeHtml(task.title)}" onchange="updateSubtaskField(${idx}, 'title', this.value); renderHITLPlan(currentDynamicPlan);" style="font-weight: 700;">
          </div>

          <div class="form-row" style="margin-bottom: 0;">
            <label style="font-size: 0.68rem;">Description & Objectives</label>
            <textarea style="min-height: 52px; font-size: 0.78rem;" onchange="updateSubtaskField(${idx}, 'description', this.value); renderHITLPlan(currentDynamicPlan);">${escapeHtml(task.description || '')}</textarea>
          </div>

          <div class="grid-2" style="gap: 6px;">
            <div class="form-row" style="margin-bottom: 0;">
              <label style="font-size: 0.68rem;">Assigned Tool</label>
              <select onchange="updateSubtaskField(${idx}, 'tool', this.value); renderHITLPlan(currentDynamicPlan);" style="font-size: 0.72rem; padding: 5px 6px;">
                <option value="superdocs_create_document" ${task.tool === 'superdocs_create_document' ? 'selected' : ''}>superdocs_create_document</option>
                <option value="superdocs_edit_section" ${task.tool === 'superdocs_edit_section' ? 'selected' : ''}>superdocs_edit_section</option>
                <option value="superdocs_create_task" ${task.tool === 'superdocs_create_task' ? 'selected' : ''}>superdocs_create_task</option>
                <option value="superdocs_render_template" ${task.tool === 'superdocs_render_template' ? 'selected' : ''}>superdocs_render_template</option>
                <option value="superdocs_search" ${task.tool === 'superdocs_search' ? 'selected' : ''}>superdocs_search</option>
              </select>
            </div>
            <div class="form-row" style="margin-bottom: 0;">
              <label style="font-size: 0.68rem;">Phase</label>
              <input type="text" value="${escapeHtml(task.phase || 'Drafting')}" onchange="updateSubtaskField(${idx}, 'phase', this.value);" style="font-size: 0.72rem; padding: 5px 6px;">
            </div>
          </div>

          <div style="background: var(--code-box-bg); padding: 6px 8px; border-radius: 6px; border: 1px solid var(--border-subtle); font-size: 0.72rem; margin-top: 2px;">
            <div style="color: var(--primary); font-weight: 700; margin-bottom: 2px;">Acceptance Criteria:</div>
            <input type="text" value="${escapeHtml(task.acceptance_criteria || 'Executable step verification.')}" onchange="updateSubtaskField(${idx}, 'acceptance_criteria', this.value);" style="background: transparent; border: none; padding: 2px; font-size: 0.72rem; color: var(--text-dim); width: 100%;">
          </div>
        </div>
      `;
      }).join('');
    }

    function updateSubtaskField(index, field, value) {
      if (currentDynamicPlan && currentDynamicPlan.tasks[index]) {
        currentDynamicPlan.tasks[index][field] = value;
      }
    }

    function moveSubtask(index, delta) {
      if (!currentDynamicPlan || !currentDynamicPlan.tasks) return;
      const targetIdx = index + delta;
      if (targetIdx < 0 || targetIdx >= currentDynamicPlan.tasks.length) return;
      const item = currentDynamicPlan.tasks.splice(index, 1)[0];
      currentDynamicPlan.tasks.splice(targetIdx, 0, item);
      currentDynamicPlan.tasks.forEach((t, i) => { t.step = i + 1; t.id = `TASK-${i + 1}`; });
      renderHITLPlan(currentDynamicPlan);
      renderDedicatedTaskPlan(currentDynamicPlan);
    }

    function deleteSubtask(index) {
      if (!currentDynamicPlan || !currentDynamicPlan.tasks) return;
      currentDynamicPlan.tasks.splice(index, 1);
      currentDynamicPlan.tasks.forEach((t, i) => { t.step = i + 1; t.id = `TASK-${i + 1}`; });
      renderHITLPlan(currentDynamicPlan);
      renderDedicatedTaskPlan(currentDynamicPlan);
    }

    function addNewSubtask() {
      if (!currentDynamicPlan) {
        currentDynamicPlan = {
          plan_id: 'plan-' + Math.random().toString(36).substring(2, 9),
          session_id: document.getElementById('taskSessionId').value || 'custom-plan',
          document_type: 'Custom Document',
          decision_rationale: 'User-composed dynamic task plan.',
          is_complex: true,
          approval_status: 'pending',
          tasks: []
        };
      }
      const newStep = currentDynamicPlan.tasks.length + 1;
      currentDynamicPlan.tasks.push({
        id: `TASK-${newStep}`,
        step: newStep,
        phase: 'Custom Phase',
        title: `Custom Subtask ${newStep}`,
        description: 'Specify subtask instructions, objectives, and parameters here.',
        tool: 'superdocs_create_task',
        acceptance_criteria: 'Custom requirements verified.',
        estimated_time: '5-10s',
        status: 'pending'
      });
      renderHITLPlan(currentDynamicPlan);
      renderDedicatedTaskPlan(currentDynamicPlan);
      showToast(`Added Subtask ${newStep}`);
    }

    /* DIRECT IN-PLACE DOCUMENT EDITING */
    function toggleDirectEditMode() {
      if (isDirectEditing) {
        saveDirectEdits();
      } else {
        startDirectEdit();
      }
    }

    function startDirectEdit() {
      const area = document.getElementById('documentPreviewArea');
      const toolbar = document.getElementById('richEditorToolbar');
      const badge = document.getElementById('docEditStatusBadge');
      const btnToggle = document.getElementById('btnToggleDirectEdit');
      const btnSave = document.getElementById('btnSaveDirectEdit');
      const btnCancel = document.getElementById('btnCancelDirectEdit');

      if (!currentDocumentHtml) {
        currentDocumentHtml = '<h1>Untitled Document</h1><p>Start writing your content here...</p>';
        area.innerHTML = currentDocumentHtml;
      }

      isDirectEditing = true;
      area.contentEditable = "true";
      area.classList.add('editing');
      toolbar.style.display = 'flex';
      badge.style.display = 'inline-flex';

      btnToggle.style.display = 'none';
      btnSave.style.display = 'inline-flex';
      btnCancel.style.display = 'inline-flex';

      area.focus();
      addLog('✏️ Direct in-place editing mode activated.', 'info');
      showToast('✏️ Edit mode enabled. Click inside document to type.');
    }

    async function saveDirectEdits() {
      const area = document.getElementById('documentPreviewArea');
      const toolbar = document.getElementById('richEditorToolbar');
      const badge = document.getElementById('docEditStatusBadge');
      const btnToggle = document.getElementById('btnToggleDirectEdit');
      const btnSave = document.getElementById('btnSaveDirectEdit');
      const btnCancel = document.getElementById('btnCancelDirectEdit');

      currentDocumentHtml = area.innerHTML;
      const sessId = currentActiveSession || document.getElementById('taskSessionId').value || 'active-session';

      try {
        const res = await fetch('/api/document/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessId,
            document_id: sessId,
            document_html: currentDocumentHtml
          })
        });
        const data = await res.json();
        if (data.success) {
          addLog(`💾 Saved document edits successfully for session '${sessId}'.`, 'success');
          showToast('💾 Document saved successfully!');
        } else {
          addLog(`Save warning: ${data.message}`, 'error');
        }
      } catch (err) {
        addLog(`Saved locally. (Network note: ${err.message})`, 'info');
        showToast('💾 Saved locally.');
      }

      isDirectEditing = false;
      area.contentEditable = "false";
      area.classList.remove('editing');
      toolbar.style.display = 'none';
      badge.style.display = 'none';

      btnToggle.style.display = 'inline-flex';
      btnSave.style.display = 'none';
      btnCancel.style.display = 'none';

      document.getElementById('docChangesSummary').innerText = `Changes: Manual in-place edit saved at ${new Date().toLocaleTimeString()}`;
    }

    function cancelDirectEdits() {
      const area = document.getElementById('documentPreviewArea');
      const toolbar = document.getElementById('richEditorToolbar');
      const badge = document.getElementById('docEditStatusBadge');
      const btnToggle = document.getElementById('btnToggleDirectEdit');
      const btnSave = document.getElementById('btnSaveDirectEdit');
      const btnCancel = document.getElementById('btnCancelDirectEdit');

      area.innerHTML = currentDocumentHtml || '<div style="text-align: center; color: #94a3b8; padding-top: 130px;"><h2 style="font-family: var(--font-display);">No Document Loaded</h2><p>Execute a task plan or click "✏️ Edit Document" to start writing.</p></div>';
      
      isDirectEditing = false;
      area.contentEditable = "false";
      area.classList.remove('editing');
      toolbar.style.display = 'none';
      badge.style.display = 'none';

      btnToggle.style.display = 'inline-flex';
      btnSave.style.display = 'none';
      btnCancel.style.display = 'none';

      addLog('Direct edit mode cancelled.', 'info');
      showToast('Edit cancelled.');
    }

    function formatDoc(command, value = null) {
      document.execCommand(command, false, value);
      document.getElementById('documentPreviewArea').focus();
    }

    function formatBlock(tag) {
      document.execCommand('formatBlock', false, `<${tag}>`);
      document.getElementById('documentPreviewArea').focus();
    }

    function insertTableAtCursor() {
      const tableHtml = `
        <table style="width: 100%; border-collapse: collapse; margin: 12px 0;">
          <thead>
            <tr>
              <th style="border: 1px solid #cbd5e1; padding: 6px 10px; background: #f1f5f9;">Item / Component</th>
              <th style="border: 1px solid #cbd5e1; padding: 6px 10px; background: #f1f5f9;">Specification</th>
              <th style="border: 1px solid #cbd5e1; padding: 6px 10px; background: #f1f5f9;">Status / SLA</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style="border: 1px solid #cbd5e1; padding: 6px 10px;">Primary Gateway</td>
              <td style="border: 1px solid #cbd5e1; padding: 6px 10px;">Active-Active Multi-Region</td>
              <td style="border: 1px solid #cbd5e1; padding: 6px 10px;">99.99% Availability</td>
            </tr>
            <tr>
              <td style="border: 1px solid #cbd5e1; padding: 6px 10px;">Failover Automation</td>
              <td style="border: 1px solid #cbd5e1; padding: 6px 10px;">Automated DNS Cutover</td>
              <td style="border: 1px solid #cbd5e1; padding: 6px 10px;">&lt; 60s RTO</td>
            </tr>
          </tbody>
        </table>
        <p><br></p>
      `;
      document.execCommand('insertHTML', false, tableHtml);
    }

    /* AI PROMPT-BASED DOCUMENT REVISION */
    function setAiPrompt(text) {
      const input = document.getElementById('aiRevisionPromptInput');
      input.value = text;
      input.focus();
    }

    async function applyAiDocumentRevision() {
      const promptInput = document.getElementById('aiRevisionPromptInput');
      const prompt = promptInput.value.trim();
      if (!prompt) {
        alert('Please enter an AI revision instruction.');
        promptInput.focus();
        return;
      }

      const btn = document.getElementById('btnApplyAiEdit');
      const sessId = currentActiveSession || document.getElementById('taskSessionId').value || 'revision-session';
      const modelTier = document.getElementById('taskModelTier').value;
      const thinkingDepth = document.getElementById('taskThinkingDepth').value;

      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Applying...';
      addLog(`[AI Surgical Revision] Applying: "${prompt}"...`, 'info');

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessId,
            message: prompt,
            document_html: currentDocumentHtml,
            model_tier: modelTier,
            thinking_depth: thinkingDepth,
          })
        });
        const chatData = await res.json();
        if (chatData.success) {
          addLog(`[AI Surgical Revision] Applied: ${chatData.data.response || 'Success'}`, 'success');
          if (chatData.data && chatData.data.document_changes && chatData.data.document_changes.updated_html) {
            renderDocument(chatData.data.document_changes.updated_html, sessId, chatData.data.document_changes.changes_summary);
          } else if (chatData.data && chatData.data.document_state && chatData.data.document_state.document_html) {
            renderDocument(chatData.data.document_state.document_html, sessId, 'AI prompt revision applied');
          }
          showToast('✨ AI Edit applied successfully!');
          promptInput.value = '';
        } else {
          addLog(`[AI Surgical Revision] Failed: ${chatData.message}`, 'error');
          alert('AI edit failed: ' + chatData.message);
        }
      } catch (err) {
        addLog(`Error applying AI edit: ${err.message}`, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>✨ Apply AI Edit</span>';
        refreshAccountStatus();
      }
    }

    async function approveAndExecutePlan() {
      if (!currentDynamicPlan) {
        alert('Please synthesize a dynamic plan first.');
        return;
      }

      const btn = document.getElementById('btnApproveAndExecute');
      const approvalBadge = document.getElementById('planApprovalBadge');
      const statusBadge = document.getElementById('currentJobStatusBadge');
      const progressBar = document.getElementById('taskProgressBar');
      const progressPercent = document.getElementById('progressPercentText');
      const progressStep = document.getElementById('progressStepText');

      setStepNode(4);
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Executing Plan...';
      statusBadge.className = 'status-badge in_progress';
      statusBadge.innerText = 'EXECUTING';
      approvalBadge.className = 'status-badge approved';
      approvalBadge.innerText = 'APPROVED';

      addLog(`[HITL Gate] Plan '${currentDynamicPlan.plan_id}' approved. Dispatching execution to SuperDocs API...`, 'info');

      try {
        const approveRes = await fetch('/api/dynamic-plan/approve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            plan_id: currentDynamicPlan.plan_id,
            edited_tasks: currentDynamicPlan.tasks,
          })
        });
        const approveData = await approveRes.json();
        if (!approveData.success) throw new Error(approveData.message || 'Approval failed');

        const total = currentDynamicPlan.tasks.length;
        for (let i = 0; i < total; i++) {
          const task = currentDynamicPlan.tasks[i];
          task.status = 'in_progress';
          renderHITLPlan(currentDynamicPlan);
          renderDedicatedTaskPlan(currentDynamicPlan);

          const percent = Math.round(((i + 0.5) / total) * 100);
          progressBar.style.width = `${percent}%`;
          progressPercent.innerText = `${percent}%`;
          progressStep.innerText = `Step ${i + 1}/${total}: ${task.title}`;
          addLog(`[Step ${i + 1}/${total}] Executing '${task.title}' via ${task.tool}...`, 'info');

          const execRes = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              session_id: currentDynamicPlan.session_id,
              message: `[${task.id} - ${task.title}]: ${task.description}`,
              document_html: currentDocumentHtml,
              model_tier: document.getElementById('taskModelTier').value,
              thinking_depth: document.getElementById('taskThinkingDepth').value,
            })
          });
          const chatData = await execRes.json();
          if (chatData.success) {
            task.status = 'completed';
            addLog(`[Step ${i + 1}/${total}] Completed: ${chatData.data.response || 'Done'}`, 'success');
            if (chatData.data && chatData.data.document_changes && chatData.data.document_changes.updated_html) {
              renderDocument(chatData.data.document_changes.updated_html, currentDynamicPlan.session_id, chatData.data.document_changes.changes_summary);
            }
          } else {
            task.status = 'failed';
            addLog(`[Step ${i + 1}/${total}] Failed: ${chatData.message}`, 'error');
          }
          renderHITLPlan(currentDynamicPlan);
          renderDedicatedTaskPlan(currentDynamicPlan);
        }

        setStepNode(5);
        progressBar.style.width = '100%';
        progressPercent.innerText = '100%';
        progressStep.innerText = 'All Dynamic Tasks Executed Successfully!';
        statusBadge.className = 'status-badge completed';
        statusBadge.innerText = 'COMPLETED';
        addLog(`🎉 All ${total} dynamic tasks completed successfully!`, 'success');
        showToast('🎉 Document generation complete!');

      } catch (err) {
        addLog(`Error executing dynamic plan: ${err.message}`, 'error');
        statusBadge.className = 'status-badge failed';
        statusBadge.innerText = 'FAILED';
        progressStep.innerText = 'Execution Failed';
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>🚀 Approve & Execute Plan</span>';
        refreshAccountStatus();
      }
    }

    function executeFromStudioTab() {
      switchTab('tasksTab');
      approveAndExecutePlan();
    }

    function renderDocument(html, sessionId, changesSummary) {
      currentDocumentHtml = html;
      currentActiveSession = sessionId;
      document.getElementById('documentPreviewArea').innerHTML = html;
      document.getElementById('docMetaSubtitle').innerText = `Active Session: ${sessionId}`;
      document.getElementById('docChangesSummary').innerText = `Changes: ${changesSummary || 'Updated by SuperDocs AI'}`;
    }

    async function exportCurrentDoc(format) {
      if (!currentDocumentHtml && !currentActiveSession) {
        alert('No active document to export. Please execute a task plan or write content first.');
        return;
      }
      try {
        const res = await fetch('/api/document/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: currentActiveSession || 'exported-doc',
            html_content: currentDocumentHtml,
            format: format
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`📥 Exported to ${format.toUpperCase()} successfully!`);
          addLog(`Document exported to ${format.toUpperCase()}.`, 'success');
        } else {
          alert(`Export failed: ${data.message}`);
        }
      } catch (e) {
        alert('Export error: ' + e);
      }
    }

    async function refreshAccountStatus() {
      const badge = document.getElementById('accountStatusBadge');
      const text = document.getElementById('accountInfoText');
      try {
        const res = await fetch('/api/whoami');
        const data = await res.json();
        if (data.success && data.data) {
          const acc = data.data;
          badge.className = 'account-badge';
          const resetStr = acc.resets_at ? ` (Resets ${new Date(acc.resets_at).toLocaleDateString()})` : '';
          text.innerText = `SuperDocs API Live • Tier: ${acc.tier.toUpperCase()} • Quota: ${acc.remaining}/${acc.monthly_limit} remaining${resetStr}`;
        } else {
          badge.className = 'account-badge offline';
          text.innerText = 'Offline Mock Mode Active';
        }
      } catch (err) {
        badge.className = 'account-badge offline';
        text.innerText = 'SuperDocs Offline Mock Active';
      }
    }

    function addLog(msg, type = 'info') {
      const container = document.getElementById('liveTaskLogs');
      const timeStr = new Date().toLocaleTimeString();
      const div = document.createElement('div');
      div.className = `log-row ${type}`;
      div.innerText = `[${timeStr}] ${msg}`;
      container.appendChild(div);
      container.scrollTop = container.scrollHeight;
    }

    async function loadJobsTable() {
      const tbody = document.getElementById('jobsTableBody');
      try {
        const res = await fetch('/api/jobs');
        const data = await res.json();
        const jobs = (data.data && data.data.jobs) ? data.data.jobs : [];
        if (!jobs.length) {
          tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 24px;">No async tasks found in SuperDocs queue.</td></tr>';
          return;
        }
        tbody.innerHTML = jobs.map(j => `
          <tr>
            <td style="font-family: var(--font-code); font-size: 0.78rem;">${j.job_id}</td>
            <td>${escapeHtml(j.session_id || 'N/A')}</td>
            <td><span class="status-badge ${j.status || 'pending'}">${j.status || 'PENDING'}</span></td>
            <td>${j.progress || 0}%</td>
            <td style="font-size: 0.78rem; color: var(--text-muted);">${j.created_at || 'N/A'}</td>
            <td>
              <button class="btn btn-glass btn-icon" onclick="cancelJob('${j.job_id}')">Cancel</button>
            </td>
          </tr>
        `).join('');
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #f87171; padding: 24px;">Error loading jobs: ${err}</td></tr>`;
      }
    }

    async function cancelJob(jobId) {
      if (!confirm(`Cancel job ${jobId}?`)) return;
      const res = await fetch('/api/task/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId })
      });
      const data = await res.json();
      alert(data.message || 'Cancelled');
      loadJobsTable();
    }

    async function loadDocumentsTable() {
      const tbody = document.getElementById('docsTableBody');
      try {
        const res = await fetch('/api/documents');
        const data = await res.json();
        const docs = (data.data && data.data.documents) ? data.data.documents : [];
        if (!docs.length) {
          tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">No saved documents found in SuperDocs account.</td></tr>';
          return;
        }
        tbody.innerHTML = docs.map(d => `
          <tr>
            <td style="font-family: var(--font-code); font-size: 0.78rem;">${d.document_id}</td>
            <td style="font-weight: 600;">${escapeHtml(d.title || 'Untitled')}</td>
            <td>${d.source || 'ai_created'}</td>
            <td>v${d.version || 1}</td>
            <td>${d.session_count || 1} chats</td>
            <td style="font-size: 0.78rem; color: var(--text-muted);">${d.updated_at || 'N/A'}</td>
            <td>
              <div style="display: flex; gap: 6px;">
                <button class="btn btn-glass btn-icon" onclick="openSavedDoc('${d.document_id}')">Inspect</button>
                <button class="btn btn-glow-primary btn-icon" onclick="editSavedDoc('${d.document_id}')">✏️ Edit</button>
              </div>
            </td>
          </tr>
        `).join('');
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: #f87171; padding: 24px;">Error loading documents: ${err}</td></tr>`;
      }
    }

    async function openSavedDoc(docId) {
      const res = await fetch(`/api/document?document_id=${encodeURIComponent(docId)}`);
      const data = await res.json();
      if (data.success && data.data) {
        switchTab('tasksTab');
        const doc = data.data;
        renderDocument(doc.content || `<h1>${escapeHtml(doc.title)}</h1><p>Document ID: ${doc.document_id}</p>`, doc.document_id, 'Loaded from Files');
      } else {
        alert('Failed to load document: ' + data.message);
      }
    }

    async function editSavedDoc(docId) {
      const res = await fetch(`/api/document?document_id=${encodeURIComponent(docId)}`);
      const data = await res.json();
      if (data.success && data.data) {
        switchTab('tasksTab');
        const doc = data.data;
        renderDocument(doc.content || `<h1>${escapeHtml(doc.title)}</h1><p>Document ID: ${doc.document_id}</p>`, doc.document_id, 'Loaded for editing');
        startDirectEdit();
      } else {
        alert('Failed to load document: ' + data.message);
      }
    }

    async function runLangGraphAgent() {
      const goal = document.getElementById('agentGoal').value.trim();
      const fmt = document.getElementById('agentExportFormat').value;
      const btn = document.getElementById('btnRunAgent');
      const badge = document.getElementById('agentStatusBadge');
      const traceContainer = document.getElementById('agentTraceLogs');
      const checklistContainer = document.getElementById('agentTaskChecklist');
      const outputContainer = document.getElementById('agentFinalOutput');

      btn.disabled = true;
      badge.className = 'status-badge in_progress';
      badge.innerText = 'EXECUTING';
      traceContainer.innerHTML = '<div class="log-row info">[LangGraph] Compiling state graph and planning tasks...</div>';

      try {
        const res = await fetch('/api/run-agent', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: goal, format: fmt })
        });
        const state = await res.json();

        const tasks = state.tasks || [];
        checklistContainer.innerHTML = tasks.map(t => `
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; background: var(--btn-glass-bg); border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div><strong>${t.id}:</strong> ${escapeHtml(t.title)}</div>
            <span class="status-badge ${t.status}">${t.status.toUpperCase()}</span>
          </div>
        `).join('');

        const logs = state.trace_logs || [];
        traceContainer.innerHTML = logs.map(l => `<div class="log-row">${escapeHtml(l)}</div>`).join('');

        if (state.final_output) {
          outputContainer.innerHTML = `<pre style="font-family: var(--font-code); white-space: pre-wrap; font-size: 0.82rem;">${escapeHtml(state.final_output)}</pre>`;
        }

        badge.className = 'status-badge completed';
        badge.innerText = 'COMPLETED';
      } catch (err) {
        badge.className = 'status-badge failed';
        badge.innerText = 'FAILED';
        traceContainer.innerHTML += `<div class="log-row error">[Error] ${err.message}</div>`;
      } finally {
        btn.disabled = false;
        refreshAccountStatus();
      }
    }

    function escapeHtml(str) {
      return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
  </script>
</body>
</html>
"""


class StudioHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif parsed.path == "/api/whoami":
            res = client.get_whoami()
            self._send_json(res.model_dump())
        elif parsed.path in ("/api/jobs", "/api/tasks"):
            res = client.list_tasks()
            self._send_json(res.model_dump())
        elif parsed.path == "/api/task/status":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("job_id", [""])[0]
            res = client.get_task_status(job_id=job_id)
            self._send_json(res.model_dump())
        elif parsed.path == "/api/documents":
            res = client.list_documents()
            self._send_json(res.model_dump())
        elif parsed.path == "/api/document":
            query = urllib.parse.parse_qs(parsed.query)
            doc_id = query.get("document_id", [""])[0]
            res = client.get_document(document_id=doc_id)
            self._send_json(res.model_dump())
        elif parsed.path == "/api/sessions":
            res = client.list_sessions()
            self._send_json(res.model_dump())
        elif parsed.path == "/api/session-history":
            query = urllib.parse.parse_qs(parsed.query)
            session_id = query.get("session_id", ["default-session"])[0]
            res = client.get_session_history(session_id)
            self._send_json(res.model_dump())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len)
        data = json.loads(post_body.decode("utf-8")) if post_body else {}

        if parsed.path in ("/api/dynamic-plan/generate", "/api/task-plan"):
            prompt = data.get("prompt", "Create document")
            session_id = data.get("session_id")
            model_tier = data.get("model_tier", "core")
            thinking_depth = data.get("thinking_depth", "balanced")
            
            plan = planner.evaluate_and_plan(
                prompt=prompt,
                session_id=session_id,
                model_tier=model_tier,
                thinking_depth=thinking_depth,
            )
            self._send_json({"success": True, "data": plan.model_dump()})

        elif parsed.path == "/api/dynamic-plan/approve":
            plan_id = data.get("plan_id", "")
            edited_tasks = data.get("edited_tasks")
            res = planner.approve_plan(plan_id=plan_id, edited_tasks=edited_tasks)
            self._send_json(res.model_dump())

        elif parsed.path == "/api/dynamic-plan/execute":
            plan_id = data.get("plan_id", "")
            res = planner.execute_approved_plan(plan_id=plan_id)
            self._send_json(res.model_dump())

        elif parsed.path == "/api/document/save":
            session_id = data.get("session_id", "default-session")
            document_id = data.get("document_id", session_id)
            document_html = data.get("document_html", "")
            res = client.save_document(session_id=session_id, document_id=document_id, document_html=document_html)
            self._send_json(res.model_dump())

        elif parsed.path == "/api/chat":
            session_id = data.get("session_id", "default-session")
            message = data.get("message", "")
            doc_html = data.get("document_html")
            model_tier = data.get("model_tier", "core")
            thinking_depth = data.get("thinking_depth")
            approval_mode = data.get("approval_mode", "approve_all")
            res = client.chat(
                session_id=session_id,
                message=message,
                document_html=doc_html,
                model_tier=model_tier,
                thinking_depth=thinking_depth,
                approval_mode=approval_mode,
            )
            self._send_json(res.model_dump())

        elif parsed.path == "/api/task/create":
            session_id = data.get("session_id", "default-session")
            message = data.get("message", "")
            doc_html = data.get("document_html")
            model_tier = data.get("model_tier", "core")
            thinking_depth = data.get("thinking_depth")
            approval_mode = data.get("approval_mode", "approve_all")
            res = client.create_task(
                session_id=session_id,
                message=message,
                document_html=doc_html,
                model_tier=model_tier,
                thinking_depth=thinking_depth,
                approval_mode=approval_mode,
            )
            self._send_json(res.model_dump())

        elif parsed.path == "/api/task/cancel":
            job_id = data.get("job_id", "")
            res = client.cancel_task(job_id=job_id)
            self._send_json(res.model_dump())

        elif parsed.path == "/api/document/export":
            session_id = data.get("session_id")
            html_content = data.get("html_content")
            fmt = data.get("format", "docx")
            res = client.export_document(session_id=session_id, html_content=html_content, export_format=fmt)
            self._send_json(res.model_dump())

        elif parsed.path == "/api/run-agent":
            prompt = data.get("prompt", "Create technical architecture specification")
            fmt = data.get("format", "markdown")
            graph = create_superdocs_agent_graph(client=client, max_iterations=12)
            state = graph.invoke({
                "user_goal": prompt,
                "tasks": [],
                "current_task_index": None,
                "current_task": None,
                "document_id": None,
                "document_title": None,
                "plan": None,
                "step": 0,
                "critique": None,
                "needs_revision": False,
                "iterations": 0,
                "max_iterations": 12,
                "export_format": fmt,
                "final_output": None,
                "status": "initialized",
                "trace_logs": [],
            })
            self._send_json(state)

        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, payload: Any):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


def start_server(port: int = 8080):
    server_address = ("", port)
    httpd = http.server.HTTPServer(server_address, StudioHandler)
    print(f"🚀 SuperDocs Task & Agent Studio running live at http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    start_server(port)
