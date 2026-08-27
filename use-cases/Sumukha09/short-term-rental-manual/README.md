# Short Term Rental Manual Generator

This repository contains scripts and data to generate localized manuals and listing materials for short-term rental properties.

## Setup Instructions

Since generated manuals and build artifacts are not checked into version control, you will need to create the output directory before running the generation scripts (or ensure your scripts do so automatically).

1. **Create the output folder**
   Create a folder named `output` in the root of the project to store the generated PDFs and text files:
   ```bash
   mkdir output
   ```

2. **(Optional) Create other required folders**
   If you have additional properties or assets that are not checked in, make sure their respective directories are created in the appropriate locations.

3. **Install Dependencies**
   Make sure you have all required dependencies installed for the generation scripts.

4. **Run the Generator**
   Run the main script to generate the packs (example for `haveli-jaipur-demo`):
   ```bash
   python main.py generate haveli-jaipur-demo --lang en,es,fr --formats pdf,docx --html
   ```

## Note on Version Control
The `output/` directory is ignored via `.gitignore` to prevent generated artifacts from cluttering the repository.
