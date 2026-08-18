"""Pytest configuration and sys.path setup for M&A closing binder assembler."""

import os
import sys

# Add project root to sys.path so modules can be imported directly
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
