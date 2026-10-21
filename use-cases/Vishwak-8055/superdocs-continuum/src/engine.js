'use strict';
/**
 * Reality Engine — core domain logic.
 *
 * Framework-free on purpose: no React, no DOM, no network calls. Every
 * function is a pure function of its inputs, which is what makes it
 * possible to test the engine independently of the UI.
 *
 * The central idea: there is exactly one function that renders a document
 * graph into readable text for a given Payment Term value (buildWorld).
 * Every view — the primary document, a referenced-document preview, the
 * semantic diff, and verification — reads from that same rendered output,
 * so there is no path where two parts of the UI can show different values
 * for the same underlying state.
 */

function fmtTerm(days) {
  const words = { 30: 'thirty (30) days', 45: 'forty-five (45) days', 60: 'sixty (60) days', 90: 'ninety (90) days', 120: 'one hundred twenty (120) days' };
  return words[days] || `${days} days`;
}
function fmtNet(days) { return `Net-${days}`; }

/* -------------------------------------------------------------- */
/* WORLD MODEL                                                      */
/* -------------------------------------------------------------- */

function renderTemplate(template, paymentTermDays, capValue) {
  return template
    .replace(/\{TERM\}/g, fmtTerm(paymentTermDays))
    .replace(/\{NET\}/g, fmtNet(paymentTermDays))
    .replace(/\{CAP\}/g, fmtTerm(capValue));
}

/**
 * Renders every document in `docText` for a given proposed Payment Term.
 * This is the single rendering path — the primary document view, every
 * referenced-document preview, and the diff/verification logic all call
 * this, so they cannot drift out of sync with each other.
 */
function buildWorld(docText, objects, paymentTermDays) {
  const capValue = objects['con-enterprise-cap'] ? objects['con-enterprise-cap'].capValue : null;
  const render = (t) => renderTemplate(t, paymentTermDays, capValue);
  const docs = {};
  Object.keys(docText).forEach((docId) => {
    const src = docText[docId];
    docs[docId] = {
      id: src.id,
      title: src.title,
      subtitle: src.subtitle,
      sections: src.sections.map((s) => ({
        id: s.id,
        heading: s.heading,
        body: s.body != null ? render(s.body) : null,
        objectId: s.objectId,
        refs: s.refs,
        sub: s.sub ? s.sub.map((sub) => ({ id: sub.id, label: sub.label, body: render(sub.body), objectId: sub.objectId })) : undefined,
      })),
    };
  });
  const objectValues = {};
  Object.keys(objects).forEach((id) => {
    const o = objects[id];
    objectValues[id] = id === 'obl-payment' ? paymentTermDays : (o.value != null ? o.value : o.capValue);
  });
  return { paymentTermDays, docs, objectValues };
}

function findSection(doc, sectionRef) {
  for (const s of doc.sections) {
    if (s.id === sectionRef) return s;
    if (s.sub) {
      const hit = s.sub.find((sub) => sub.id === sectionRef);
      if (hit) return hit;
    }
  }
  return null;
}

/**
 * Resolves a semantic object's evidence against the *rendered* text of its
 * source section in a given world, rather than asserting the evidence is
 * accurate independent of what the document actually says.
 */
function resolveEvidence(world, objects, objectId) {
  const obj = objects[objectId];
  if (!obj) return { resolved: false, reason: 'unknown object' };
  const doc = world.docs[obj.doc];
  if (!doc) return { resolved: false, reason: 'source document missing from world' };
  const section = findSection(doc, obj.sectionRef);
  if (!section) return { resolved: false, reason: 'source section missing from world' };
  const capValue = objects['con-enterprise-cap'] ? objects['con-enterprise-cap'].capValue : null;
  const expected = renderTemplate(obj.evidenceTemplate, world.paymentTermDays, capValue);
  const resolved = typeof section.body === 'string' && section.body.includes(expected);
  return { resolved, text: expected, sectionId: section.id };
}

/**
 * Structural + semantic diff between two worlds. Text changes come from
 * comparing rendered section bodies section-by-section; semantic changes
 * are derived from which object values actually differ between the two
 * worlds, not written out as fixed strings.
 */
function diffWorlds(baseline, alternate, edges, objects, forecast) {
  const textChanges = [];
  Object.keys(baseline.docs).forEach((docId) => {
    const before = baseline.docs[docId];
    const after = alternate.docs[docId];
    if (!before || !after) return; // a document missing from either world can't be diffed here; verification's structure check is what catches this condition
    before.sections.forEach((bSection, i) => {
      const aSection = after.sections[i];
      if (!aSection) {
        textChanges.push({ doc: docId, section: bSection.id, before: bSection.body, after: null, kind: 'SECTION_REMOVED' });
        return;
      }
      if (bSection.body != null && bSection.body !== aSection.body) {
        textChanges.push({ doc: docId, section: bSection.id, before: bSection.body, after: aSection.body });
      }
      if (bSection.sub) {
        bSection.sub.forEach((bSub, j) => {
          const aSub = aSection.sub && aSection.sub[j];
          if (!aSub) {
            textChanges.push({ doc: docId, section: bSub.id, before: bSub.body, after: null, kind: 'SUBSECTION_REMOVED' });
            return;
          }
          if (bSub.body !== aSub.body) {
            textChanges.push({ doc: docId, section: bSub.id, before: bSub.body, after: aSub.body });
          }
        });
      }
    });
  });

  const semanticChanges = [];
  const changedValueIds = [];
  Object.keys(baseline.objectValues).forEach((objectId) => {
    const before = baseline.objectValues[objectId];
    const after = alternate.objectValues[objectId];
    if (before !== after) {
      semanticChanges.push({ kind: 'VALUE_CHANGED', objectId, before, after });
      changedValueIds.push(objectId);
    }
  });
  changedValueIds.forEach((changedId) => {
    edges.forEach((e) => {
      const isDependencyEdge = e.type === 'DEPENDS_ON' || e.type === 'DERIVED_FROM';
      if (isDependencyEdge && e.to === changedId && !semanticChanges.some((c) => c.objectId === e.from)) {
        semanticChanges.push({ kind: 'DEPENDENT_RESOLUTION_CHANGED', objectId: e.from, dependsOn: changedId });
      }
    });
  });
  if (forecast) {
    forecast.resolved.forEach(({ otherId }) => {
      semanticChanges.push({ kind: 'CONFLICT_RESOLVED', objectId: otherId });
    });
    forecast.introduced.forEach(({ otherId }) => {
      semanticChanges.push({ kind: 'CONFLICT_CREATED', objectId: otherId });
    });
  }

  const changedDocIds = new Set(textChanges.map((c) => c.doc));
  const unchangedDocIds = Object.keys(baseline.docs).filter((id) => !changedDocIds.has(id));

  return { textChanges, semanticChanges, changedDocIds: [...changedDocIds], unchangedDocIds };
}

/* -------------------------------------------------------------- */
/* CONSEQUENCE ENGINE                                                */
/* -------------------------------------------------------------- */

// How each edge class participates in impact traversal:
//  structural/strong  -> fully propagates impact
//  weak               -> reachable, but never counts as more than "potential"
//  conflict           -> excluded from impact traversal entirely; conflicts
//                        are a distinct relationship, surfaced by
//                        forecastContradictions instead of the impact BFS
const PROPAGATES = { structural: true, strong: true, weak: true, conflict: false };
const DEGRADES_TO_POTENTIAL = { weak: true };

function bfs(edges, startId, allowedClasses) {
  const hopOf = { [startId]: 0 };
  const parent = {};
  const touchedWeak = new Set();
  let frontier = [startId];
  let hop = 0;
  while (frontier.length && hop < 4) {
    hop += 1;
    const next = [];
    frontier.forEach((nodeId) => {
      edges.forEach((e) => {
        if (!allowedClasses[e.class]) return;
        let other = null;
        if (e.from === nodeId) other = e.to;
        else if (e.to === nodeId) other = e.from;
        if (other && !(other in hopOf)) {
          hopOf[other] = hop;
          parent[other] = { via: nodeId, edgeType: e.type };
          if (DEGRADES_TO_POTENTIAL[e.class] || touchedWeak.has(nodeId)) touchedWeak.add(other);
          next.push(other);
        }
      });
    });
    frontier = next;
  }
  return { hopOf, parent, touchedWeak };
}

function explanationChain(parent, startId, targetId) {
  const path = [targetId];
  let cur = targetId;
  while (parent[cur]) { cur = parent[cur].via; path.unshift(cur); }
  if (path[0] !== startId) return null;
  const chain = [];
  for (let i = 1; i < path.length; i += 1) chain.push({ from: path[i - 1], to: path[i], type: parent[path[i]].edgeType });
  return chain;
}

/**
 * The Consequence Engine. Reachability comes from a BFS over every
 * non-conflict edge; the *tier* assigned to each reached node comes from
 * hop distance capped by whether the path required crossing a "weak"
 * (REFERENCES-only) edge — a 1-hop reference is context, not a direct
 * consequence, regardless of how close it is.
 */
function computeConsequences(edges, isDocument, allIds, startId) {
  const { hopOf, parent, touchedWeak } = bfs(edges, startId, PROPAGATES);

  const tierOf = (id) => {
    if (!(id in hopOf)) return 'unaffected';
    if (touchedWeak.has(id)) return 'potential';
    const h = hopOf[id];
    return h === 1 ? 'direct' : h === 2 ? 'indirect' : 'potential';
  };

  const bucket = (ids) => {
    const out = { direct: [], indirect: [], potential: [], unaffected: [] };
    ids.forEach((id) => { out[tierOf(id)].push(id); });
    return out;
  };

  const docs = bucket(allIds.filter((id) => isDocument(id)));
  const objects = bucket(allIds.filter((id) => !isDocument(id) && id !== startId));
  const explain = (id) => explanationChain(parent, startId, id);
  const conflicts = edges.filter((e) => (e.type === 'CONTRADICTS' || e.type === 'CONSTRAINED_BY') && (e.from === startId || e.to === startId));

  return { hopOf, parent, docs, objects, conflicts, explain };
}

/* -------------------------------------------------------------- */
/* CONTRADICTION FORECAST                                           */
/* -------------------------------------------------------------- */

/**
 * Two independent kinds of conflict are modeled:
 *  - CONTRADICTS: an equality-style clash against another stated term
 *    (Sales Terms' 45-day default). Resolved if the proposed value matches
 *    the other side exactly; otherwise still open.
 *  - CONSTRAINED_BY: a cap/floor a value must respect (the Enterprise
 *    Payment Term ceiling). "Introduced" means the *current* value
 *    satisfies the constraint but the *proposed* value would not — a real
 *    before/after comparison, not a static list.
 */
function forecastContradictions(edges, objects, startId, currentValue, proposedValue) {
  const contradicts = edges.filter((e) => e.type === 'CONTRADICTS' && (e.from === startId || e.to === startId));
  const resolved = [];
  const stillOpen = [];
  contradicts.forEach((edge) => {
    const otherId = edge.from === startId ? edge.to : edge.from;
    const other = objects[otherId];
    if (other && typeof other.value === 'number' && other.value === proposedValue) resolved.push({ edge, otherId });
    else stillOpen.push({ edge, otherId });
  });

  const constraints = edges.filter((e) => e.type === 'CONSTRAINED_BY' && e.from === startId);
  const introduced = [];
  constraints.forEach((edge) => {
    const constraint = objects[edge.to];
    if (!constraint || typeof constraint.capValue !== 'number') return;
    const violates = (v) => (constraint.comparator === 'max' ? v > constraint.capValue : v < constraint.capValue);
    if (violates(proposedValue) && !violates(currentValue)) {
      introduced.push({ edge, otherId: edge.to, constraint });
    }
  });

  return { preExistingCount: contradicts.length, resolved, stillOpen, introduced };
}

/* -------------------------------------------------------------- */
/* INPUT VALIDATION                                                 */
/* -------------------------------------------------------------- */

function validateProposedValue(raw) {
  if (raw === '' || raw === null || raw === undefined) return { valid: false, reason: 'Enter a value.' };
  const n = Number(raw);
  if (Number.isNaN(n)) return { valid: false, reason: 'Must be a number.' };
  if (!Number.isFinite(n)) return { valid: false, reason: 'Must be a finite number.' };
  if (!Number.isInteger(n)) return { valid: false, reason: 'Must be a whole number of days.' };
  if (n <= 0) return { valid: false, reason: 'Must be greater than zero.' };
  if (n > 3650) return { valid: false, reason: 'That is more than 10 years — check the value.' };
  return { valid: true, value: n };
}

/* -------------------------------------------------------------- */
/* SCENARIO STATE MACHINE                                           */
/* -------------------------------------------------------------- */

const SCENARIO_STATES = [
  'DRAFT', 'ANALYZING', 'SIMULATED', 'REVIEW', 'APPROVED',
  'APPLYING', 'VERIFYING', 'COMMITTED', 'REJECTED', 'FAILED', 'ROLLED_BACK',
];
const TRANSITIONS = {
  DRAFT: ['ANALYZING', 'REJECTED'],
  ANALYZING: ['SIMULATED', 'FAILED'],
  SIMULATED: ['REVIEW'],
  REVIEW: ['APPROVED', 'REJECTED'],
  APPROVED: ['APPLYING'],
  APPLYING: ['VERIFYING', 'FAILED'],
  VERIFYING: ['COMMITTED', 'ROLLED_BACK'],
  COMMITTED: [],
  REJECTED: [],
  FAILED: ['ROLLED_BACK'],
  ROLLED_BACK: [],
};
class IllegalTransitionError extends Error {
  constructor(from, to) {
    super(`Illegal scenario transition: ${from} -> ${to}`);
    this.name = 'IllegalTransitionError';
    this.from = from; this.to = to;
  }
}
function nextState(current, requested) {
  const allowed = TRANSITIONS[current];
  if (!allowed) throw new Error(`Unknown state: ${current}`);
  if (!allowed.includes(requested)) throw new IllegalTransitionError(current, requested);
  return requested;
}

/* -------------------------------------------------------------- */
/* VERIFICATION + SAFE APPLY                                        */
/* -------------------------------------------------------------- */

/**
 * Every check here inspects the actual candidate world, the actual
 * baseline world, the actual diff between them, or the actual edge list —
 * none of them is a literal `true` disconnected from what they claim to
 * check.
 */
function runVerification(baseline, candidate, diff, forecast, edges, objects, docMeta, requiredSections) {
  const checks = [];

  const structureOk = Object.keys(docMeta).every((id) => candidate.docs[id] && Array.isArray(candidate.docs[id].sections) && candidate.docs[id].sections.length > 0);
  checks.push({ id: 'structure', label: 'Document structure valid', pass: structureOk });

  const anchorResults = Object.keys(objects).map((id) => resolveEvidence(candidate, objects, id));
  const anchorsOk = anchorResults.every((r) => r.resolved);
  checks.push({ id: 'anchors', label: 'Source anchors resolve', pass: anchorsOk, detail: `${anchorResults.filter((r) => r.resolved).length}/${anchorResults.length} evidence spans resolved against candidate text` });

  const sectionIdsOf = (doc) => {
    const ids = [];
    doc.sections.forEach((s) => { ids.push(s.id); if (s.sub) s.sub.forEach((sub) => ids.push(sub.id)); });
    return ids;
  };
  const sectionsOk = Object.keys(docMeta).every((docId) => {
    const required = requiredSections[docId];
    if (!required) return true;
    const doc = candidate.docs[docId];
    if (!doc) return false;
    const present = sectionIdsOf(doc);
    return required.every((id) => present.includes(id));
  });
  checks.push({ id: 'sections', label: 'Required sections present', pass: sectionsOk });

  checks.push({
    id: 'no-new-conflicts', label: 'No new unresolved conflicts introduced',
    pass: forecast.introduced.length === 0,
    detail: forecast.introduced.length ? `${forecast.introduced.length} constraint violation(s) this change would introduce` : undefined,
  });

  const knownIds = new Set([...Object.keys(docMeta), ...Object.keys(objects)]);
  const graphOk = edges.every((e) => knownIds.has(e.from) && knownIds.has(e.to));
  checks.push({ id: 'graph-sync', label: 'Relationship graph referentially intact', pass: graphOk });

  const unchangedOk = diff.unchangedDocIds.every((docId) => JSON.stringify(baseline.docs[docId]) === JSON.stringify(candidate.docs[docId]));
  checks.push({
    id: 'unchanged-preserved', label: 'Documents outside the change scope are untouched', pass: unchangedOk,
    detail: `${diff.unchangedDocIds.length} document(s) checked byte-for-byte against baseline`,
  });

  return { checks, allPassed: checks.every((c) => c.pass) };
}

/**
 * Confirms a candidate was verified, and only then returns the world/version
 * that should become canonical. Returns a decision — it does not mutate
 * anything itself. On failure it returns { committed: false }, explicitly
 * leaving canonical state and version untouched rather than partially
 * applying anything.
 */
function commitWorld(canonicalVersion, verification, candidateWorld) {
  if (!verification || !verification.allPassed) {
    return { committed: false, world: null, version: canonicalVersion };
  }
  return { committed: true, world: candidateWorld, version: canonicalVersion + 1 };
}

/* -------------------------------------------------------------- */
/* HEALTH SCORE (heuristic, explicitly labeled as such)              */
/* -------------------------------------------------------------- */

/**
 * All five dimensions are computed from the actual world/edge/object
 * tables. The overall score is still an explicitly-labeled heuristic
 * average, not a validated measurement — but none of its inputs are
 * placeholder constants.
 */
function computeHealth(world, edges, objects, entities, requiredSections, docMeta) {
  const conflictCount = edges.filter((e) => e.type === 'CONTRADICTS').length;

  const anchorResults = Object.keys(objects).map((id) => resolveEvidence(world, objects, id));
  const evidenceCoverage = Math.round((anchorResults.filter((r) => r.resolved).length / anchorResults.length) * 100);

  const sectionIdsOf = (doc) => {
    const ids = [];
    doc.sections.forEach((s) => { ids.push(s.id); if (s.sub) s.sub.forEach((sub) => ids.push(sub.id)); });
    return ids;
  };
  const docIds = Object.keys(docMeta);
  const structuralOkCount = docIds.filter((id) => {
    const required = requiredSections[id];
    if (!world.docs[id] || !required) return !!world.docs[id];
    return required.every((sid) => sectionIdsOf(world.docs[id]).includes(sid));
  }).length;
  const structuralIntegrity = Math.round((structuralOkCount / docIds.length) * 100);

  const dependencyObjects = Object.values(objects).filter((o) => o.type === 'Dependency');
  const dependencyResolved = dependencyObjects.filter((o) => edges.some((e) => e.from === o.id && (e.type === 'DEPENDS_ON' || e.type === 'DERIVED_FROM'))).length;
  const dependencyCompleteness = dependencyObjects.length ? Math.round((dependencyResolved / dependencyObjects.length) * 100) : 100;

  const provenanceValidCount = Object.values(objects).filter((o) => docMeta[o.doc] && world.docs[o.doc] && sectionIdsOf(world.docs[o.doc]).includes(o.sectionRef)).length;
  const provenanceCoverage = Math.round((provenanceValidCount / Object.keys(objects).length) * 100);

  const dims = [
    { label: 'Structural integrity', value: structuralIntegrity },
    { label: 'Evidence coverage', value: evidenceCoverage },
    { label: 'Consistency', value: Math.max(0, 100 - conflictCount * 15) },
    { label: 'Dependency completeness', value: dependencyCompleteness },
    { label: 'Provenance coverage', value: provenanceCoverage },
  ];
  const score = Math.max(0, Math.round(dims.reduce((s, d) => s + d.value, 0) / dims.length));
  return { score, dims, conflictCount, entityCount: entities.length };
}

module.exports = {
  fmtTerm, fmtNet, renderTemplate,
  buildWorld, findSection, resolveEvidence, diffWorlds,
  computeConsequences, explanationChain,
  forecastContradictions, validateProposedValue,
  SCENARIO_STATES, TRANSITIONS, IllegalTransitionError, nextState,
  runVerification, commitWorld, computeHealth,
};
