# Documentation Drift Detector — Test Corpus

# Intro doc (has one injected drift: npm → pnpm)
# intro.md
# ---
# Getting Started
#
# To install dependencies, run `npm install`. This will download all required packages.
# After installation, run `npm test` to verify everything works.
# The default port is 3000.

# Config doc (has one injected drift: default port changed)
# config.md
# ---
# Configuration Reference
#
# The application listens on port 3000 by default.
# Set `PORT` environment variable to change this.
# Logs are written to `/var/log/app.log`.

# Clean doc (no drifts — should yield zero findings)
# clean.md
# ---
# Clean Section
#
# This document describes the authentication system.
# Users authenticate with OAuth 2.0 using the /auth/login endpoint.
# Tokens expire after 24 hours.