#!/usr/bin/env python3
"""
FHIR Query Builder - TUI Entry Point

A terminal-based interface for building FHIR search queries using AI.

Usage:
    python fhir_query_builder.py
    # or
    python -m fhir_query_builder
"""

from src.fhir_tui import main

if __name__ == "__main__":
    main()
