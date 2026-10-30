import requests
import json
import time

BASE_URL = 'http://127.0.0.1:8001'

print('===========================================================================')
print('               TASK 2 STANDALONE SERVER MANUAL AUDIT')
print('===========================================================================')

# 1. Health Check & Reset
print('\n[1] Testing GET /healthz and POST /api/clinical/reset...')
r = requests.get(f'{BASE_URL}/healthz')
print(f'Status: {r.status_code} | Payload: {r.json()}')
assert r.status_code == 200

r_reset = requests.post(f'{BASE_URL}/api/clinical/reset')
print(f'Reset Status: {r_reset.status_code} | Payload: {r_reset.json()}')
assert r_reset.status_code == 200

# 2. Web Dashboard Availability
print('\n[2] Testing GET /dashboard (HTML UI)...')
r = requests.get(f'{BASE_URL}/dashboard')
print(f'Status: {r.status_code} | HTML Length: {len(r.text)} bytes')
assert r.status_code == 200
assert 'SuperDocs Clinical Transfer Assembler' in r.text

# 3. Patient State & Reconciled MAR
print('\n[3] Testing GET /api/clinical/handoff/883921...')
r = requests.get(f'{BASE_URL}/api/clinical/handoff/883921')
print(f'Status: {r.status_code}')
data = r.json()
print(f"Patient: {data['demographics']['name']} | Code Status: {data['demographics']['code_status']}")
print(f"Allergies: {data['allergies']}")
print(f"Medications Count: {len(data['medications'])}")
for m in data['medications']:
    high_alert = f" [HIGH ALERT: {m['high_risk_category']}]" if m['is_high_risk'] else ""
    dup = f" --> WARNING: {m['duplicate_warning']}" if m['is_duplicate'] else ""
    print(f" - {m['name']} ({m['dose']}){high_alert}{dup}")

# 4. Attempt Export While Gated (Expect HTTP 422 Fail-Closed)
print('\n[4] GATING CHECK: Testing GET /api/clinical/export/pdf BEFORE Nurse Sign-off...')
r = requests.get(f'{BASE_URL}/api/clinical/export/pdf')
print(f'Status: {r.status_code} (Expected 422 Unprocessable Entity)')
print(f'Blocked Response: {r.json()}')
assert r.status_code == 422
assert 'EXPORT_BLOCKED_SAFETY_GATES_PENDING' in r.text

# 5. Confirm Gate 1: Allergies
print('\n[5] Confirming Gate 1: Allergies (RN Sarah Jenkins)...')
r = requests.post(f'{BASE_URL}/api/clinical/confirm-gate', json={
    'gate_type': 'allergies',
    'nurse_name': 'RN Sarah Jenkins',
    'nurse_id': 'RN-4029'
})
res_json = r.json()
print(f"Status: {r.status_code} | Unlocked: {res_json.get('is_export_unlocked')} | Pending: {res_json.get('pending_gates')}")

# Still blocked?
r_block1 = requests.get(f'{BASE_URL}/api/clinical/export/pdf')
assert r_block1.status_code == 422
print(' -> Verified: Export still blocked after 1 gate.')

# 6. Confirm Gate 2: Code Status
print('\n[6] Confirming Gate 2: Code Status (RN Sarah Jenkins)...')
r = requests.post(f'{BASE_URL}/api/clinical/confirm-gate', json={
    'gate_type': 'code_status',
    'nurse_name': 'RN Sarah Jenkins',
    'nurse_id': 'RN-4029'
})
res_json2 = r.json()
print(f"Status: {r.status_code} | Unlocked: {res_json2.get('is_export_unlocked')} | Pending: {res_json2.get('pending_gates')}")

# Still blocked?
r_block2 = requests.get(f'{BASE_URL}/api/clinical/export/pdf')
assert r_block2.status_code == 422
print(' -> Verified: Export still blocked after 2 gates.')

# 7. Confirm Gate 3: High-Risk Medications (Dual-Nurse Sign-off)
print('\n[7] Confirming Gate 3: High-Alert Meds (RN Sarah Jenkins & RN Mark Taylor)...')
r = requests.post(f'{BASE_URL}/api/clinical/confirm-gate', json={
    'gate_type': 'high_risk_meds',
    'nurse_name': 'RN Sarah Jenkins',
    'nurse_id': 'RN-4029',
    'second_nurse_name': 'RN Mark Taylor',
    'second_nurse_id': 'RN-5104'
})
res_json3 = r.json()
print(f"Status: {r.status_code} | Unlocked: {res_json3.get('is_export_unlocked')} | Pending: {res_json3.get('pending_gates')}")
assert res_json3.get('is_export_unlocked') is True

# 8. Export PDF Dossier (Now Unlocked!)
print('\n[8] Testing GET /api/clinical/export/pdf (UNLOCKED)...')
r_pdf = requests.get(f'{BASE_URL}/api/clinical/export/pdf')
print(f"Status: {r_pdf.status_code} | Content-Type: {r_pdf.headers.get('Content-Type')}")
print(f"PDF Bytes Received: {len(r_pdf.content):,} bytes")
assert r_pdf.status_code == 200
assert r_pdf.content.startswith(b'%PDF')
assert len(r_pdf.content) > 10000

# 9. Export Word Dossier
print('\n[9] Testing GET /api/clinical/export/docx (SuperDocs Word Format)...')
r_docx = requests.get(f'{BASE_URL}/api/clinical/export/docx')
print(f"Status: {r_docx.status_code} | Content-Type: {r_docx.headers.get('Content-Type')}")
print(f"Word (.docx) Bytes Received: {len(r_docx.content):,} bytes")
assert r_docx.status_code == 200
assert len(r_docx.content) > 30000

print('\n===========================================================================')
print('[SUCCESS] ALL TASK 2 CLINICAL FEATURES, GATES & EXPORTS TESTED & 100% OPERATIONAL')
print('===========================================================================')
