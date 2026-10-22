import { chromium } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';

async function captureScreenshots() {
  const outDir = path.resolve(process.cwd(), 'docs/screenshots');
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
  });

  const page = await context.newPage();

  // Mock API endpoints
  await page.route('https://api.superdocs.app/**', async (route) => {
    const url = route.request().url();
    const method = route.request().method();

    if (url.endsWith('/v1/sessions/init') && method === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'session_demo_982' }) });
    }
    if (url.endsWith('/v1/documents/upload-base64') && method === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'session_demo_982', document_id: 'doc_demo_982', chunks_count: 3, html: '<h1>SuperDocs Demo</h1>' }) });
    }
    if (url.endsWith('/v1/chat/async') && method === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ job_id: 'job_demo_982' }) });
    }
    if (url.includes('/v1/jobs/job_demo_982') && method === 'GET') {
      const pendingChangesPayload = {
        batch_id: 'batch_demo_1',
        batch_total: 3,
        awaiting_kind: 'approval',
        changes: [
          { change_id: 'chg_1', operation: 'replace', old_html: '<h1>SuperDocs Demo</h1>', new_html: '<h1>SuperDocs Replit Extension</h1>', ai_explanation: 'Updated project title to match Replit workspace package' },
          { change_id: 'chg_2', operation: 'insert', new_html: '<h2>API Reference</h2><p>export function add(a, b)</p>', ai_explanation: 'Added API reference section extracted from src/index.ts' },
          { change_id: 'chg_3', operation: 'delete', old_html: '<p>Legacy notes</p>', ai_explanation: 'Removed obsolete notes' },
        ],
      };
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          job_id: 'job_demo_982',
          status: 'awaiting_approval',
          progress: 100,
          metadata: { pending_changes: JSON.stringify({ content: JSON.stringify(pendingChangesPayload) }) },
        }),
      });
    }
    if (url.includes('/v1/templates') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          templates: [
            { id: 'tmpl_1', name: 'API Spec Template', description: 'Standard REST and SDK API documentation structure', document_type: 'spec', default_content: '# {{project_name}} Specification\n\n## Overview\n{{description}}', variables: [{ name: 'project_name', description: 'Project Name', default_value: 'Replit App', required: true }] },
            { id: 'tmpl_2', name: 'Developer README', description: 'Quickstart, architecture, prerequisites, and developer scripts', document_type: 'readme', default_content: '# {{project_name}}', variables: [] },
          ],
        }),
      });
    }
    if (url.includes('/v1/prompts') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          prompts: [
            { id: 'p_1', name: 'Security Audit Prompt', description: 'Generates auth and vulnerability inspection docs', template: 'Audit {{module_name}}', variables: [{ name: 'module_name', description: 'Module name', default_value: 'AuthEngine', required: true }] },
          ],
        }),
      });
    }
    if (url.includes('/versions') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          versions: [
            { version_id: 'v2', document_id: 'doc_demo_982', created_at: '2026-08-25T12:00:00Z', created_by: 'SuperDocs AI', change_summary: 'Added API Reference & Auth Module docs', html: '<h1>SuperDocs Replit Extension</h1><h2>API Reference</h2>', is_current: true },
            { version_id: 'v1', document_id: 'doc_demo_982', created_at: '2026-08-25T10:00:00Z', created_by: 'Initial Draft', change_summary: 'Initial workspace ingestion', html: '<h1>SuperDocs Demo</h1>', is_current: false },
          ],
        }),
      });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
  });

  await page.goto('http://localhost:5173/replit-host.html');
  await page.waitForLoadState('networkidle');

  const iframe = page.frameLocator('#ext-frame');
  await iframe.getByRole('heading', { name: 'SuperDocs', level: 1 }).waitFor();

  // 1. Dark Mode Workspace File Tree
  await page.screenshot({ path: path.join(outDir, '01_dark_workspace_filetree.png'), fullPage: false });
  console.log('Saved 01_dark_workspace_filetree.png');

  // 2. API Key Modal Pop
  await iframe.getByRole('button', { name: 'Set API Key' }).click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(outDir, '02_api_key_modal_pop.png'), fullPage: false });
  console.log('Saved 02_api_key_modal_pop.png');

  // Set Key & Generate
  await iframe.getByPlaceholder('sk_...').fill('sk_live_demo_key_9988');
  await iframe.getByRole('button', { name: 'Save' }).click();
  await iframe.getByText('package.json').click();
  await iframe.getByText('src').click();
  await iframe.getByRole('tab', { name: 'Draft' }).click();
  await iframe.getByRole('button', { name: 'Generate Document' }).click();

  // 3. Granular Cherry-Pick Review Screen
  await iframe.getByText('3 Proposed Changes', { exact: true }).waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(outDir, '03_cherry_pick_review.png'), fullPage: false });
  console.log('Saved 03_cherry_pick_review.png');

  // 4. Side Drawer & Overview
  await iframe.getByLabel('Toggle Side Drawer').click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(outDir, '04_side_drawer_overview.png'), fullPage: false });
  console.log('Saved 04_side_drawer_overview.png');
  await iframe.getByLabel('Close Drawer').click();

  // 5. Template Gallery & Variable Injection
  await iframe.getByRole('tab', { name: 'Templates' }).click();
  await iframe.getByText('API Spec Template').click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(outDir, '05_template_gallery_variables.png'), fullPage: false });
  console.log('Saved 05_template_gallery_variables.png');

  // 6. Version History
  await iframe.getByRole('tab', { name: 'History' }).click();
  await iframe.getByRole('button', { name: 'Preview' }).last().click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(outDir, '06_version_history_rollback.png'), fullPage: false });
  console.log('Saved 06_version_history_rollback.png');

  // 7. Light Theme Mode
  await iframe.getByLabel('Toggle Theme').click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(outDir, '07_light_theme_mode.png'), fullPage: false });
  console.log('Saved 07_light_theme_mode.png');

  await browser.close();
  console.log('All screenshots captured successfully!');
}

captureScreenshots().catch(err => {
  console.error(err);
  process.exit(1);
});
