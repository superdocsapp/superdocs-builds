import { Article, ChangeEvent, ScreenshotAssessment, Screenshot } from './types.js';

/**
 * Lightweight Screenshot Freshness Detector
 * Evaluates embedded screenshots using OCR labels, captions, and surrounding context.
 * Honestly flags whether replacement is required or if visual ambiguity requires COULD_NOT_ASSESS.
 */
export function analyzeScreenshots(
  article: Article,
  change: ChangeEvent
): ScreenshotAssessment[] {
  const results: ScreenshotAssessment[] = [];

  for (const screenshot of article.screenshots) {
    results.push(assessSingleScreenshot(article.id, screenshot, change));
  }

  return results;
}

function assessSingleScreenshot(
  articleId: string,
  screenshot: Screenshot,
  change: ChangeEvent
): ScreenshotAssessment {
  // If screenshot lacks OCR labels and caption is empty, we cannot honestly verify it
  if ((!screenshot.ocr_labels || screenshot.ocr_labels.length === 0) && !screenshot.caption) {
    return {
      article_id: articleId,
      screenshot_id: screenshot.id,
      status: 'COULD_NOT_ASSESS',
      reason: 'Screenshot lacks extracted OCR text labels and descriptive caption metadata.',
      evidence: ['No OCR text available for visual verification.'],
      replacement_required: false,
      mismatched_labels: []
    };
  }

  const ocrLower = (screenshot.ocr_labels || []).map(l => l.toLowerCase());
  const captionLower = (screenshot.caption || '').toLowerCase();
  const mismatched: string[] = [];
  const evidence: string[] = [];

  const before = change.before_state;

  // Check 1: Renamed UI label in screenshot
  if (before.ui_label) {
    const labelLower = before.ui_label.toLowerCase();
    const foundInOcr = ocrLower.some(l => l.includes(labelLower));
    const foundInCaption = captionLower.includes(labelLower);

    if (foundInOcr || foundInCaption) {
      mismatched.push(before.ui_label);
      evidence.push(`Visible UI label '${before.ui_label}' found in screenshot OCR/caption (renamed to '${change.after_state.ui_label || 'new label'}').`);
    }
  }

  // Check 2: Retired plan in screenshot
  if (before.entity_name && change.type === 'RETIRED_PLAN') {
    const planLower = before.entity_name.toLowerCase();
    const foundInOcr = ocrLower.some(l => l.includes(planLower));
    const foundInCaption = captionLower.includes(planLower);

    if (foundInOcr || foundInCaption) {
      mismatched.push(before.entity_name);
      evidence.push(`Retired plan name '${before.entity_name}' visible in screenshot OCR/caption.`);
    }
  }

  // Check 3: Changed limit or path
  if (before.path) {
    const pathLower = before.path.toLowerCase();
    if (ocrLower.some(l => l.includes(pathLower)) || captionLower.includes(pathLower)) {
      mismatched.push(before.path);
      evidence.push(`Deprecated navigation path '${before.path}' visible in screenshot.`);
    }
  }

  if (mismatched.length > 0) {
    return {
      article_id: articleId,
      screenshot_id: screenshot.id,
      status: 'SCREENSHOT_REPLACEMENT_REQUIRED',
      reason: `Screenshot displays outdated UI elements: ${mismatched.join(', ')}`,
      evidence,
      replacement_required: true,
      mismatched_labels: mismatched
    };
  }

  return {
    article_id: articleId,
    screenshot_id: screenshot.id,
    status: 'SCREENSHOT_OK',
    reason: 'No deprecated UI labels or retired entities detected in screenshot OCR labels.',
    evidence: ['Verified against change feed; all visible labels appear current.'],
    replacement_required: false,
    mismatched_labels: []
  };
}
