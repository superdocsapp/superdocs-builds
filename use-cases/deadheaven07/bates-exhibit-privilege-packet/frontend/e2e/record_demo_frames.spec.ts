import { test, expect } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FIXTURES_DIR = path.join(__dirname, 'fixtures');
const FRAMES_DIR = '/tmp/task21_demo_frames';

test.describe('Task 2.1 Demo Recording', () => {
  test('Record high-resolution frames for Task 2.1 Workflow GIF', async ({ page }) => {
    // Setup frames directory
    if (fs.existsSync(FRAMES_DIR)) {
      fs.rmSync(FRAMES_DIR, { recursive: true, force: true });
    }
    fs.mkdirSync(FRAMES_DIR, { recursive: true });

    let frameCount = 0;
    const capture = async (name: string, delayMs = 200) => {
      if (delayMs > 0) await page.waitForTimeout(delayMs);
      frameCount++;
      const paddedIndex = String(frameCount).padStart(3, '0');
      const framePath = path.join(FRAMES_DIR, `frame_${paddedIndex}_${name}.png`);
      await page.screenshot({ path: framePath, fullPage: false });
      console.log(`Captured frame [${paddedIndex}]: ${name}`);
    };

    const packetName = 'Doe v. Acme Corp - Trial Packet';
    const packetDesc = 'Evidentiary litigation packet with Bates stamping, PII redactions, and privilege log.';

    // -------------------------------------------------------------
    // Step 1: Dashboard
    // -------------------------------------------------------------
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: 'Packets' })).toBeVisible({ timeout: 15000 });
    await capture('01_dashboard', 500);

    // -------------------------------------------------------------
    // Step 2: Create New Packet Modal
    // -------------------------------------------------------------
    await page.getByRole('button', { name: /New Packet/i }).click();
    await page.waitForTimeout(300);
    const nameInput = page.getByPlaceholder(/Smith v\. Jones/i);
    await expect(nameInput).toBeVisible();
    await nameInput.fill(packetName);
    const descInput = page.getByPlaceholder(/evidentiary submission/i);
    await descInput.fill(packetDesc);
    await capture('02_create_packet_modal', 400);

    // -------------------------------------------------------------
    // Step 3: Open Packet Workspace
    // -------------------------------------------------------------
    await page.getByRole('button', { name: 'Create Packet' }).click();
    await expect(page.getByText(packetName).first()).toBeVisible({ timeout: 10000 });
    await capture('03_packet_in_list', 400);

    await page.getByText(packetName).first().click();
    await page.waitForURL(/\/packets\/[a-f0-9-]+/);
    await page.waitForTimeout(500);
    await capture('04_empty_workspace', 400);

    // -------------------------------------------------------------
    // Step 4: Mixed-Format Document Ingestion
    // -------------------------------------------------------------
    const file1 = path.join(FIXTURES_DIR, '01_contract_services.pdf');
    const file2 = path.join(FIXTURES_DIR, '02_privileged_strategy_memo.pdf');
    const file3 = path.join(FIXTURES_DIR, '03_invoice_billing.pdf');
    const file4 = path.join(FIXTURES_DIR, '04_scanned_medical_receipt.png');

    const fileInput = page.locator('input[type="file"][multiple]');
    await fileInput.setInputFiles([file1, file2, file3, file4]);

    await expect(page.getByRole('button', { name: /01_contract_services\.pdf/i }).first()).toBeVisible({ timeout: 25000 });
    await expect(page.getByRole('button', { name: /02_privileged_strategy_memo\.pdf/i }).first()).toBeVisible({ timeout: 25000 });
    await expect(page.getByRole('button', { name: /03_invoice_billing\.pdf/i }).first()).toBeVisible({ timeout: 25000 });
    await expect(page.getByRole('button', { name: /04_scanned_medical_receipt\.png/i }).first()).toBeVisible({ timeout: 25000 });
    await capture('05_exhibits_uploaded', 600);

    // -------------------------------------------------------------
    // Step 5: Document Processing & OCR
    // -------------------------------------------------------------
    const processBtn = page.getByRole('button', { name: /Process/i });
    if (await processBtn.isEnabled()) {
      await processBtn.click();
      await page.waitForTimeout(2000);
      await capture('06_processing_active', 400);
      await page.waitForTimeout(4000);
    }
    await capture('07_processing_completed', 500);

    // -------------------------------------------------------------
    // Step 6: Sequential Bates Numbering Assignment
    // -------------------------------------------------------------
    const assignBatesBtn = page.getByRole('button', { name: /Assign Bates/i });
    await assignBatesBtn.click();
    await expect(page.getByText(/CASE-000001/i).first()).toBeVisible({ timeout: 15000 });
    await capture('08_bates_assigned', 600);

    // -------------------------------------------------------------
    // Step 7: OCR Status Drawer
    // -------------------------------------------------------------
    const inspectButtons = page.getByTitle('Quick Inspect');
    await inspectButtons.last().click();
    await expect(page.getByText(/OCR \/ Searchable Status/i)).toBeVisible({ timeout: 5000 });
    await capture('09_ocr_drawer_open', 600);

    await page.keyboard.press('Escape');
    await page.waitForTimeout(400);
    await capture('10_drawer_closed', 200);

    // -------------------------------------------------------------
    // Step 8: Privilege Review & Dynamic Logging
    // -------------------------------------------------------------
    await page.getByRole('tab', { name: 'Privilege' }).click();
    await page.waitForTimeout(600);

    const privilegeSelect = page.locator('select').filter({ hasText: 'Privileged' }).first();
    await privilegeSelect.selectOption('privileged');

    const categorySelect = page.locator('select').filter({ hasText: 'Attorney-Client' }).first();
    await categorySelect.selectOption('attorney_client');

    const reasonInput = page.getByPlaceholder(/Reason/i).first();
    await reasonInput.fill('Confidential attorney-client communication regarding settlement exposure.');
    await capture('11_privilege_decision_filled', 400);

    await page.getByRole('button', { name: 'Save Decision' }).first().click();
    await page.waitForTimeout(1000);
    await capture('12_privilege_saved', 500);

    // -------------------------------------------------------------
    // Step 9: AI PII Candidate Detection & Human Approval Flow
    // -------------------------------------------------------------
    await page.getByRole('button', { name: /Detect PII/i }).click();
    await page.waitForTimeout(3000);

    await page.getByRole('tab', { name: 'Redactions' }).click();
    await page.waitForTimeout(1000);

    const approveBtn = page.getByRole('button', { name: 'Approve', exact: true }).first();
    await expect(approveBtn).toBeVisible({ timeout: 45000 });
    await capture('13_pii_candidates_surfaced', 600);

    // Human Approval Gate
    await approveBtn.click();
    await page.waitForTimeout(1000);
    await capture('14_candidate_approved', 600);

    // Apply approved byte-level scrub
    const applyBtn = page.getByRole('button', { name: 'Apply', exact: true }).first();
    if (await applyBtn.isVisible().catch(() => false)) {
      await applyBtn.click();
      await page.waitForTimeout(1500);
      await capture('15_redactions_applied_verified', 600);
    }

    // -------------------------------------------------------------
    // Step 10: Immutable Audit Trail
    // -------------------------------------------------------------
    await page.getByRole('tab', { name: 'Audit Trail' }).click();
    await expect(page.getByText(/Immutable Audit Trail & Ledger/i)).toBeVisible({ timeout: 10000 });
    await capture('16_audit_trail', 600);

    // -------------------------------------------------------------
    // Step 11: Pre-Flight Checklist Modal & Build Packet
    // -------------------------------------------------------------
    await page.getByRole('button', { name: 'Build Packet', exact: true }).click();
    await expect(page.getByText(/Pre-Flight Packet Build Checklist/i)).toBeVisible({ timeout: 10000 });
    await capture('17_preflight_modal', 600);

    await page.getByRole('button', { name: 'Proceed & Build Final Packet' }).click();
    await page.waitForTimeout(5000);
    await capture('18_packet_built_overview', 600);

    // -------------------------------------------------------------
    // Step 12: Cryptographic Verification (15-Point Integrity Check)
    // -------------------------------------------------------------
    await page.getByRole('button', { name: 'Verify', exact: true }).click();
    await expect(page.getByText(/PACKET CRYPTOGRAPHICALLY VERIFIED/i)).toBeVisible({ timeout: 30000 });
    await capture('19_packet_verified_banner', 1000);

    // -------------------------------------------------------------
    // Step 13: Export Ready Deliverables
    // -------------------------------------------------------------
    await capture('20_export_ready', 800);

    console.log(`Demo recording completed successfully! Total frames: ${frameCount}`);
  });
});
