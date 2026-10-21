# Open-Enrolment Communication Kit

An automated HR benefits package generator built on top of the SuperDocs API.

## Features
- Generates a full benefits open-enrollment package from plan data.
- Automatically calculates a "what changed since last year" summary using an actual deep diff of JSON plan data.
- Generates personalized enrollment letters based on employee criteria (location, union status, etc.).
- Includes a Human Review Gate before finalizing PDF exports.

## How to Run

### Backend
1. `cd backend`
2. Ensure you have your `SUPERDOCS_API_KEY` set in a `.env` file.
3. Install requirements (e.g. `pip install fastapi uvicorn requests deepdiff`).
4. Run the server: `uvicorn main:app --reload`

### Frontend
1. `cd frontend`
2. `npm install`
3. `npm start`

---
*Built for the SuperDocs Engineer Task.*
