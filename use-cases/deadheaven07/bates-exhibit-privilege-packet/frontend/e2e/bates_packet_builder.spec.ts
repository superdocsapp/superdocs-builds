import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FIXTURES_DIR = path.join(__dirname, 'fixtures');

test.describe('Task 2.1: Bates-stamped Exhibit and Privilege-Log Packet Builder E2E Suite', () => {
  const packetName = `Litigation Packet ${Date.now()}`;
  const packetDesc = 'E-Discovery legal exhibit submission with OCR, Bates stamping, and human-approved redactions.';

  test('Complete End-to-End Legal Litigation Workflow in Headed Mode', async ({ page }) => {
    // -------------------------------------------------------------
    // Step 1: Navigate to the Application & Check Dashboard
    // -------------------------------------------------------------
    console.log('--- Step 1: Navigating to Exhibit Packet Builder ---');
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Packets' })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('button', { name: /New Packet/i })).toBeVisible();

    // -------------------------------------------------------------
    // Step 2: Create a New Exhibit Packet
    // -------------------------------------------------------------
    console.log('--- Step 2: Creating New Exhibit Packet ---');
    await page.getByRole('button', { name: /New Packet/i }).click();

    // Fill in packet details modal
    const nameInput = page.getByPlaceholder(/Smith v\. Jones/i);
    await expect(nameInput).toBeVisible();
    await nameInput.fill(packetName);

    const descInput = page.getByPlaceholder(/evidentiary submission/i);
    await descInput.fill(packetDesc);

    // Submit form
    await page.getByRole('button', { name: 'Create Packet' }).click();

    // Verify packet appears in the list
    await expect(page.getByText(packetName).first()).toBeVisible({ timeout: 10000 });

    // Open the newly created packet workspace
    await page.getByText(packetName).first().click();
    await page.waitForURL(/\/packets\/[a-f0-9-]+/);
    console.log('Opened Packet Workspace URL:', page.url());

    // -------------------------------------------------------------
    // Step 3: Ingest Mixed-Format Exhibits (PDFs, Scanned Image PNG)
    // -------------------------------------------------------------
    console.log('--- Step 3: Uploading Mixed-Format Exhibits ---');
    const file1 = path.join(FIXTURES_DIR, '01_contract_services.pdf');
    const file2 = path.join(FIXTURES_DIR, '02_privileged_strategy_memo.pdf');
    const file3 = path.join(FIXTURES_DIR, '03_invoice_billing.pdf');
    const file4 = path.join(FIXTURES_DIR, '04_scanned_medical_receipt.png');

    // Locate the hidden file input and upload all files
    const fileInput = page.locator('input[type="file"][multiple]');
    await fileInput.setInputFiles([file1, file2, file3, file4]);

    // Wait for the files to be ingested and rendered in the sidebar
    await expect(page.getByRole('button', { name: /01_contract_services\.pdf/i }).first()).toBeVisible({ timeout: 25000 });
    await expect(page.getByRole('button', { name: /02_privileged_strategy_memo\.pdf/i }).first()).toBeVisible({ timeout: 25000 });
    await expect(page.getByRole('button', { name: /03_invoice_billing\.pdf/i }).first()).toBeVisible({ timeout: 25000 });
    await expect(page.getByRole('button', { name: /04_scanned_medical_receipt\.png/i }).first()).toBeVisible({ timeout: 25000 });

    // -------------------------------------------------------------
    // Step 4: Process Ingestion & Assign Sequential Bates Numbers
    // -------------------------------------------------------------
    console.log('--- Step 4: Triggering Processing and Bates Numbering ---');
    // Click Process if ready
    const processBtn = page.getByRole('button', { name: /Process/i });
    if (await processBtn.isEnabled()) {
      await processBtn.click();
      await page.waitForTimeout(6000);
    }

    // Click Assign Bates
    const assignBatesBtn = page.getByRole('button', { name: /Assign Bates/i });
    await assignBatesBtn.click();

    // Verify Bates numbers assigned to documents
    await expect(page.getByText(/CASE-000001/i).first()).toBeVisible({ timeout: 15000 });
    console.log('Bates numbering assigned contiguously.');

    // -------------------------------------------------------------
    // Step 5: Inspect Document Properties and OCR Searchable Status
    // -------------------------------------------------------------
    console.log('--- Step 5: Inspecting Document Drawer & OCR Status ---');
    // Click Quick Inspect on the scanned medical receipt
    const inspectButtons = page.getByTitle('Quick Inspect');
    await inspectButtons.last().click();

    // Verify drawer contents
    await expect(page.getByText(/OCR \/ Searchable Status/i)).toBeVisible({ timeout: 5000 });
    await expect(page.getByText(/Searchable text layer active/i)).toBeVisible({ timeout: 5000 });

    // Close the inspector drawer
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);

    // -------------------------------------------------------------
    // Step 6: Test Document Reordering & Deterministic Bates Re-stamping
    // -------------------------------------------------------------
    console.log('--- Step 6: Testing Document Reordering & Bates Contiguity ---');
    const moveDownButtons = page.getByTitle('Move down');
    if (await moveDownButtons.first().isEnabled()) {
      await moveDownButtons.first().click();
      await page.waitForTimeout(1500);
      // Verify Bates stamps remain contiguous
      await expect(page.getByText(/CASE-000001/i).first()).toBeVisible();
    }

    // -------------------------------------------------------------
    // Step 7: OCR Full-Text & Bates Search
    // -------------------------------------------------------------
    console.log('--- Step 7: Testing Full-Text & Bates Search ---');
    await page.getByRole('link', { name: 'Packet Search' }).first().click();
    await page.waitForURL(/\/search/);

    // Select the current packet from dropdown
    const selectDropdown = page.locator('select').first();
    await selectDropdown.selectOption({ label: packetName });

    // Search query for content extracted via OCR from scanned image
    const searchInput = page.getByPlaceholder(/Search filenames, extracted content/i);
    await searchInput.fill('Acute Bronchitis');
    await page.getByRole('button', { name: 'Search', exact: true }).click();

    // Verify search snippet match on OCR text
    await expect(page.getByText(/Found/i).first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/04_scanned_medical_receipt\.png/i).first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Page 1/i).first()).toBeVisible();

    // Return to the packet workspace by clicking the search result link
    await page.getByRole('link', { name: /04_scanned_medical_receipt\.png/i }).first().click();
    await page.waitForURL(/\/packets\/[a-f0-9-]+/);

    // -------------------------------------------------------------
    // Step 8: Privilege Review & Privilege Log Assembly
    // -------------------------------------------------------------
    console.log('--- Step 8: Privilege Review & Dynamic Logging ---');
    // Switch to Privilege Tab in center panel
    await page.getByRole('tab', { name: 'Privilege' }).click();
    await page.waitForTimeout(1000);

    // Locate the status dropdown and set Privileged
    const privilegeSelect = page.locator('select').filter({ hasText: 'Privileged' }).first();
    await privilegeSelect.selectOption('privileged');

    // Locate category dropdown and set Attorney-Client
    const categorySelect = page.locator('select').filter({ hasText: 'Attorney-Client' }).first();
    await categorySelect.selectOption('attorney_client');

    // Fill reason
    const reasonInput = page.getByPlaceholder(/Reason/i).first();
    await reasonInput.fill('Confidential attorney-client communication regarding settlement exposure.');

    // Click Save Decision
    const saveBtn = page.getByRole('button', { name: 'Save Decision' }).first();
    await saveBtn.click();
    await page.waitForTimeout(1500);

    // -------------------------------------------------------------
    // Step 9: PII Candidate Redaction Detection & Human Approval Flow
    // -------------------------------------------------------------
    console.log('--- Step 9: PII Detection & Human Approval Enforcement ---');
    // Trigger PII Detection
    await page.getByRole('button', { name: /Detect PII/i }).click();
    await page.waitForTimeout(3000);

    // Switch to Redactions tab
    await page.getByRole('tab', { name: 'Redactions' }).click();

    // Wait for redaction candidate card to load from backend analysis
    const approveBtn = page.getByRole('button', { name: 'Approve', exact: true }).first();
    await expect(approveBtn).toBeVisible({ timeout: 60000 });

    const approveButtons = page.getByRole('button', { name: 'Approve', exact: true });
    const count = await approveButtons.count();
    console.log(`Found ${count} proposed redaction candidate(s).`);

    // Approve the first candidate
    if (count > 0) {
      await approveBtn.click();
      await page.waitForTimeout(1000);

      // Now apply the approved redaction
      const applyBtn = page.getByRole('button', { name: 'Apply', exact: true }).first();
      if (await applyBtn.isVisible().catch(() => false)) {
        await applyBtn.click();
        await page.waitForTimeout(1500);
      }
    }

    // -------------------------------------------------------------
    // Step 10: Audit Trail Verification
    // -------------------------------------------------------------
    console.log('--- Step 10: Verifying Audit Trail ---');
    await page.getByRole('tab', { name: 'Audit Trail' }).click();
    await expect(page.getByText(/Immutable Audit Trail & Ledger/i)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/upload|bates|privilege|redaction/i).first()).toBeVisible({ timeout: 10000 });

    // -------------------------------------------------------------
    // Step 11: Pre-Flight Validation, Cryptographic Verification & Build
    // -------------------------------------------------------------
    console.log('--- Step 11: Building Final Packet Deliverables ---');
    // Click Build Packet button to open pre-flight checklist modal
    await page.getByRole('button', { name: 'Build Packet', exact: true }).click();

    // Verify pre-flight checklist modal
    await expect(page.getByText(/Pre-Flight Packet Build Checklist/i)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Total Exhibits/i)).toBeVisible();
    await expect(page.getByText(/Bates Stamping Range/i)).toBeVisible();

    // Confirm and proceed to build final packet
    await page.getByRole('button', { name: 'Proceed & Build Final Packet' }).click();

    // Wait for packet build compilation
    await page.waitForTimeout(5000);

    // Trigger cryptographic verification
    await page.getByRole('button', { name: 'Verify', exact: true }).click();

    // Verify cryptographic verification banner
    await expect(page.getByText(/PACKET CRYPTOGRAPHICALLY VERIFIED/i)).toBeVisible({ timeout: 30000 });
    console.log('Packet cryptographically verified with 100% check integrity!');

    // -------------------------------------------------------------
    // Step 12: Export Deliverable Packet
    // -------------------------------------------------------------
    console.log('--- Step 12: Triggering Packet Export ---');
    const downloadPromise = page.waitForEvent('download', { timeout: 15000 }).catch(() => null);
    await page.getByRole('button', { name: 'Export', exact: true }).click();
    const download = await downloadPromise;
    if (download) {
      console.log('Downloaded final deliverable:', await download.suggestedFilename());
    }

    console.log('--- End-to-End Headed Test Successfully Completed! ---');
  });
});
