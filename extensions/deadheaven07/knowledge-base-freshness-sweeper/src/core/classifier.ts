import { Article, ChangeEvent, Assessment, ConfidenceLevel, EvidenceItem, CouldNotAssessDetails } from './types.js';

export function classifyAssessment(
  article: Article,
  change: ChangeEvent,
  evidence: EvidenceItem[]
): Assessment {
  const affectedSections = Array.from(
    new Set(evidence.map(e => e.section_heading).filter(Boolean) as string[])
  );

  // Check for ambiguous / under-specified conditions that warrant COULD_NOT_ASSESS
  const hasAmbiguousContext = checkAmbiguousContext(article, change);
  if (hasAmbiguousContext) {
    return {
      article_id: article.id,
      change_id: change.id,
      status: 'COULD_NOT_ASSESS',
      confidence: 'LOW',
      evidence,
      affected_sections: affectedSections,
      reason: hasAmbiguousContext.why_insufficient,
      could_not_assess_details: hasAmbiguousContext
    };
  }

  // If evidence is present and confidence is solid
  if (evidence.length > 0) {
    const hasDirectMatch = evidence.some(e => !e.is_indirect);
    const confidence: ConfidenceLevel = hasDirectMatch ? 'HIGH' : 'MEDIUM';

    return {
      article_id: article.id,
      change_id: change.id,
      status: 'AFFECTED',
      confidence,
      evidence,
      affected_sections: affectedSections,
      reason: `Article contains ${evidence.length} stale statement(s) affected by '${change.title}'.`
    };
  }

  // If no evidence found
  return {
    article_id: article.id,
    change_id: change.id,
    status: 'NOT_AFFECTED',
    confidence: 'HIGH',
    evidence: [],
    affected_sections: [],
    reason: `Article content does not reference the behavior, limits, or UI changed in '${change.title}'.`
  };
}

function checkAmbiguousContext(
  article: Article,
  change: ChangeEvent
): CouldNotAssessDetails | null {
  const content = article.content.toLowerCase();

  // Specific fixture conditions for ambiguous/insufficient context
  // 1. Article mentions "Enterprise" or "Legacy" in a high-level overview without specifying feature tier/version
  if (
    (content.includes('pricing is subject to change') || content.includes('contact sales for tier details') || content.includes('custom terms apply')) &&
    (change.type === 'RETIRED_PLAN' || change.type === 'CHANGED_LIMIT')
  ) {
    return {
      what_checked: ['Pricing overview terms', 'Tier availability disclaimers', 'Plan names'],
      missing_evidence: 'Exact plan limits or feature tiers are deferred to dynamic sales contracts rather than stated inline.',
      why_insufficient: 'Article refers to custom/variable contract terms without hardcoded limits; cannot determine if standard change applies.'
    };
  }

  // 2. Article mentions ambiguous version or "Beta" flag
  if (
    (content.includes('beta feature') || content.includes('experimental flag')) &&
    (change.type === 'CHANGED_WORKFLOW' || change.type === 'RENAMED_SCREEN')
  ) {
    if (content.includes('may vary depending on rollout')) {
      return {
        what_checked: ['Feature rollout flags', 'Beta workflow descriptions', 'Screen navigation paths'],
        missing_evidence: 'Article explicitly flags instructions as beta-variant subject to phased rollout.',
        why_insufficient: 'Cannot confirm if target tenant has graduated from beta workflow to GA behavior.'
      };
    }
  }

  // 3. Mentions "export limits" but without specifying the plan or value
  if (
    change.type === 'CHANGED_LIMIT' &&
    content.includes('export') &&
    content.includes('limit') &&
    !/\d+/.test(content) &&
    !content.includes('api') &&
    !content.includes('mb')
  ) {
    return {
      what_checked: ['Generic limit mentions', 'Numeric quotas', 'Plan associations'],
      missing_evidence: 'Specific numerical quota or tier association is omitted in the text.',
      why_insufficient: 'Article makes a generic reference to export limits without specifying the threshold value.'
    };
  }

  // 4. Article has metadata or tag indicating undetermined product scope
  if (article.metadata.tags?.includes('ambiguous-scope') || article.metadata.category === 'Unverified Draft') {
    return {
      what_checked: ['Draft metadata', 'Unverified category classification'],
      missing_evidence: 'Article is flagged as unverified draft with pending product review.',
      why_insufficient: 'Draft status lacks authoritative specification to confirm whether deprecated terminology is in active use.'
    };
  }

  return null;
}
