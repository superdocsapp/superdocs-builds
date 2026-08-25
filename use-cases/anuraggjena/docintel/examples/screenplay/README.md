# Screenplay Formatter Examples

This directory contains representative example fixtures for the **Screenplay Formatter** use case in DocIntel.

## Contents

1. **sample_raw_screenplay.txt**:
   - An example of an unformatted or raw input screenplay text.
   - Contains common formatting issues such as lowercase scene headings (int. neon coffee shop - night), lowercase character names (maya), lowercase transition cues (cut to:), and irregular spacing.

2. **sample_formatted_screenplay.txt**:
   - The standardized output produced by DocIntel's multi-stage screenplay pipeline.
   - Accurately classifies elements into scene_heading, action, character, dialogue, parenthetical, and transition.
   - Formats elements to industry standards (Courier 12pt, exact indents, uppercase headings and cues).

3. **sample_formatted_screenplay.fountain**:
   - Standard Fountain representation of the formatted screenplay for plain-text screenwriting interoperability.

4. **sample_screenplay_proposals.json**:
   - Example of the granular element-by-element formatting proposals generated during the diff stage.
   - Allows users to review, accept, reject, or edit individual formatting adjustments through the human-in-the-loop review interface before final export.
