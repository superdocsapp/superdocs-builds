import { atomicWrite } from './io.js';

export function buildPublicationPlan({ canonicalPath, releaseId, outputPaths, outputHashes = {}, repository = 'public-repository', base = 'main' }) {
  return {
    mode: 'dry-run',
    would_publish: false,
    repository,
    base,
    release_id: releaseId,
    integrity: { canonical_sha256: outputHashes.canonical_sha256 || null, pdf_sha256: outputHashes.pdf_sha256 || null, docx_sha256: outputHashes.docx_sha256 || null },
    actions: [
      { action: 'create_branch', name: `changelog/${releaseId}` },
      { action: 'add_canonical_changelog', path: canonicalPath },
      { action: 'add_derived_exports', paths: outputPaths },
      { action: 'open_pull_request', title: `docs: update changelog for ${releaseId}`, requires_explicit_external_authorization: true },
    ],
    network_calls: 0,
    credentials_used: false,
  };
}

export async function writePublicationPlan(path, plan, overwrite = false) {
  await atomicWrite(path, `${JSON.stringify(plan, null, 2)}\n`, { mode: 0o600, overwrite });
  return path;
}
