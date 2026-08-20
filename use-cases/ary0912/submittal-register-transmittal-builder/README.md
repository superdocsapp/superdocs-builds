# Submittal Register & Transmittal Packet Builder

A SuperDocs build for construction project engineers and document controllers to manage submittal requirements, review submitted product information against specifications, and create transmittal packets.

Built for the SuperDocs Round 2 assigned build: **Submittal Register and Transmittal Packet Builder.**

## What It Does

- Manages the submittal register
- Compares submitted product information against specification requirements
- Produces MATCH / DEVIATION findings with supporting evidence
- Supports human reviewer decisions
- Creates transmittal packets
- Uses SuperDocs for document editing, approval, and export
- Tracks submittal status and overdue items

## Workflow

```text
Specification Sections
        ↓
Submittal Register
        ↓
Submittal Received
        ↓
Product vs Specification Comparison
        ↓
MATCH / DEVIATION Findings
        ↓
Human Review
        ↓
Transmittal Packet
        ↓
SuperDocs Edit
        ↓
Human Approval
        ↓
Final Export
```

## SuperDocs Features Used

- Document upload
- Document editing / chat instructions
- Proposed edit workflow
- Human approval
- Document export

## How to Run

See the setup instructions in the `frontend/` and `backend/` directories.

Use environment-variable placeholders for local credentials, for example:

```env
SUPERDOCS_API_KEY=your-key-here
```

Never commit real API keys, tokens, passwords, or other secrets.

## Demo

Demo video / live deployment: **To be added**

## Screenshot

![Submittal Register & Transmittal Packet Builder](screenshot.png)

## Credit

Built by **Aryan Lodha** for the SuperDocs Round 2 task.
