import React, { useState, useMemo } from 'react';
import {
  FileText, Network, GitBranch, Zap, Eye, History as HistoryIcon,
  CheckCircle2, AlertTriangle, ArrowRight, Link2, X,
  Undo2, RotateCcw, HelpCircle, XCircle
} from 'lucide-react';

const isDocument = (id) => !!DOC_TEXT[id];
const ALL_IDS = [...Object.keys(DOC_TEXT), ...Object.keys(OBJECTS)];

const TYPE_META = {
  Obligation: { c: 'var(--indigo)', bg: 'var(--indigo-soft)' },
  Requirement: { c: 'var(--indigo)', bg: 'var(--indigo-soft)' },
  Claim: { c: 'var(--amber)', bg: 'var(--amber-soft)' },
  Dependency: { c: 'var(--teal)', bg: 'var(--teal-soft)' },
  Constraint: { c: 'var(--conflict)', bg: 'var(--conflict-soft)' },
};
const STATUS_META = {
  CONFIDENT: { c: 'var(--verified)', label: 'Confident' },
  LIKELY: { c: 'var(--amber)', label: 'Likely' },
};
const STATE_META = {
  DRAFT: { c: 'var(--ink-faint)', label: 'Draft' },
  ANALYZING: { c: 'var(--indigo)', label: 'Analyzing' },
  SIMULATED: { c: 'var(--indigo)', label: 'Simulated' },
  REVIEW: { c: 'var(--amber)', label: 'Review' },
  APPROVED: { c: 'var(--indigo)', label: 'Approved' },
  APPLYING: { c: 'var(--indigo)', label: 'Applying' },
  VERIFYING: { c: 'var(--indigo)', label: 'Verifying' },
  COMMITTED: { c: 'var(--verified)', label: 'Committed' },
  REJECTED: { c: 'var(--ink-faint)', label: 'Rejected' },
  FAILED: { c: 'var(--conflict)', label: 'Failed' },
  ROLLED_BACK: { c: 'var(--conflict)', label: 'Rolled back' },
};

/* ================================================================== */
/* SHARED UI PIECES                                                     */
/* ================================================================== */

function TypeBadge({ type }) {
  const m = TYPE_META[type] || TYPE_META.Obligation;
  return (
    <span className="dos-mono" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: m.c, background: m.bg, padding: '3px 8px', borderRadius: 5 }}>
      {type}
    </span>
  );
}
function StatusDot({ status }) {
  const m = STATUS_META[status] || STATUS_META.CONFIDENT;
  return (
    <span className="dos-mono" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: m.c, fontWeight: 600 }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: m.c, display: 'inline-block' }} />
      {m.label}
    </span>
  );
}
function StateBadge({ state }) {
  const m = STATE_META[state] || STATE_META.DRAFT;
  return (
    <span className="dos-mono" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: m.c, border: `1.5px solid ${m.c}`, padding: '4px 10px', borderRadius: 999 }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: m.c, display: 'inline-block' }} />
      {m.label}
    </span>
  );
}
function DocPill({ id, onOpen, active }) {
  const meta = DOC_META[id];
  if (!meta) return null;
  return (
    <button onClick={() => onOpen(id)} className="dos-mono dos-pill" style={active ? { borderColor: 'var(--indigo)', color: 'var(--indigo)' } : undefined}>
      <FileText size={11} strokeWidth={2.25} /> {meta.label}
    </button>
  );
}
function ObjectCard({ obj, onSelect }) {
  return (
    <button onClick={() => onSelect(obj.id)} className="dos-card dos-card-hover" style={{ textAlign: 'left', width: '100%', display: 'block', cursor: 'pointer' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
        <TypeBadge type={obj.type} />
        <StatusDot status={obj.status} />
      </div>
      <p className="dos-serif" style={{ fontSize: 15, lineHeight: 1.5, color: 'var(--ink)', margin: '0 0 10px' }}>{obj.statement}</p>
      <div className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)', display: 'flex', alignItems: 'center', gap: 6 }}>
        <Link2 size={11} /> {DOC_META[obj.doc].label} &middot; &sect;{obj.section} &middot; {obj.confidence}% confidence
      </div>
    </button>
  );
}
function renderSection(s) {
  return (
    <div key={s.id} style={{ marginBottom: 10 }}>
      {s.heading && <div className="dos-mono" style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-soft)', marginBottom: 3 }}>{s.heading}</div>}
      {s.body && <p className="dos-serif" style={{ fontSize: 14, lineHeight: 1.6, margin: 0 }}>{s.body}</p>}
      {s.sub && s.sub.map((sub) => (
        <p key={sub.id} className="dos-serif" style={{ fontSize: 14, lineHeight: 1.6, margin: '6px 0 0' }}>
          <strong>{sub.label}</strong> {sub.body}
        </p>
      ))}
    </div>
  );
}
function DocPreview({ docId, world, onClose, onSelectObject }) {
  const doc = world.docs[docId];
  if (!doc) return null;
  return (
    <div className="dos-card" style={{ borderColor: 'var(--indigo)', marginBottom: 18, position: 'relative' }}>
      <button onClick={onClose} className="dos-icon-btn" style={{ position: 'absolute', top: 12, right: 12 }} aria-label="Close preview"><X size={14} /></button>
      <div className="dos-mono" style={{ fontSize: 11, color: 'var(--indigo)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Referenced document</div>
      <h3 className="dos-serif" style={{ fontSize: 18, fontWeight: 700, margin: '0 0 2px' }}>{doc.title}</h3>
      <p className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)', margin: '0 0 14px' }}>{doc.subtitle}</p>
      {doc.sections.map((s) => renderSection(s))}
    </div>
  );
}
function Inspector({ objId, world, onClose, onJump }) {
  const obj = OBJECTS[objId];
  if (!obj) return null;
  return (
    <div className="dos-card" style={{ borderColor: 'var(--ink)', marginBottom: 18, position: 'relative', background: 'var(--surface)' }}>
      <button onClick={onClose} className="dos-icon-btn" style={{ position: 'absolute', top: 12, right: 12 }} aria-label="Close inspector"><X size={14} /></button>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <TypeBadge type={obj.type} />
        <StatusDot status={obj.status} />
      </div>
      <p className="dos-serif" style={{ fontSize: 17, lineHeight: 1.5, margin: '0 0 14px', fontWeight: 500 }}>{obj.statement}</p>
      <div className="dos-grid-2">
        <div>
          <div className="dos-mono dos-eyebrow">Source</div>
          <button onClick={() => onJump(obj.doc)} className="dos-mono" style={{ fontSize: 13, color: 'var(--indigo)', fontWeight: 600 }}>{DOC_META[obj.doc].label} &sect;{obj.section}</button>
        </div>
        <div>
          <div className="dos-mono dos-eyebrow">Confidence</div>
          <div className="dos-mono" style={{ fontSize: 13, fontWeight: 600 }}>{obj.confidence}%</div>
        </div>
      </div>
      <div style={{ marginTop: 14 }}>
        <div className="dos-mono dos-eyebrow">Evidence span</div>
        <p className="dos-serif" style={{ fontSize: 13, fontStyle: 'italic', color: 'var(--ink-soft)', borderLeft: '2px solid var(--amber)', paddingLeft: 10, margin: '4px 0 0' }}>
          &ldquo;&hellip;{resolveEvidence(world, OBJECTS, objId).text}&hellip;&rdquo;
        </p>
      </div>
    </div>
  );
}

/* ================================================================== */
/* VIEW: DOCUMENT                                                       */
/* ================================================================== */

function DocumentView({ world, onSelectObject, onOpenPreview }) {
  const doc = world.docs.agreement;
  return (
    <div className="dos-card">
      <div className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Primary document</div>
      <h2 className="dos-serif" style={{ fontSize: 22, fontWeight: 700, margin: '0 0 2px' }}>{doc.title}</h2>
      <p className="dos-mono" style={{ fontSize: 12, color: 'var(--ink-faint)', margin: '0 0 22px' }}>{doc.subtitle}</p>
      {doc.sections.map((s) => (
        <div key={s.id} style={{ marginBottom: 18 }}>
          {s.heading && <div className="dos-mono" style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink-soft)', marginBottom: 6, letterSpacing: '0.01em' }}>{s.heading}</div>}
          {s.body && (
            <p className="dos-serif" style={{ fontSize: 15.5, lineHeight: 1.75, margin: 0 }}>
              {s.body}{' '}
              {s.objectId && <button onClick={() => onSelectObject(s.objectId)} style={{ verticalAlign: 'middle' }}><TypeBadge type={OBJECTS[s.objectId].type} /></button>}
            </p>
          )}
          {s.sub && s.sub.map((item) => (
            <p key={item.id} className="dos-serif" style={{ fontSize: 15.5, lineHeight: 1.75, margin: '10px 0 0' }}>
              <strong>{item.label}</strong> {item.body}{' '}
              {item.objectId && <button onClick={() => onSelectObject(item.objectId)} style={{ verticalAlign: 'middle' }}><TypeBadge type={OBJECTS[item.objectId].type} /></button>}
            </p>
          ))}
          {s.refs && (
            <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <span className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)' }}>References:</span>
              {s.refs.map((r) => <DocPill key={r} id={r} onOpen={onOpenPreview} />)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* ================================================================== */
/* VIEW: INTELLIGENCE (Document Twin)                                   */
/* ================================================================== */

function IntelligenceView({ health, onSelectObject }) {
  const counts = {
    Entities: health.entityCount,
    Obligations: Object.values(OBJECTS).filter((o) => o.type === 'Obligation').length,
    Requirements: Object.values(OBJECTS).filter((o) => o.type === 'Requirement').length,
    Dependencies: Object.values(OBJECTS).filter((o) => o.type === 'Dependency').length,
    Constraints: Object.values(OBJECTS).filter((o) => o.type === 'Constraint').length,
    Conflicts: health.conflictCount,
  };
  return (
    <div>
      <div className="dos-card" style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <div className="dos-mono dos-eyebrow">Document intelligence health</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
              <span className="dos-serif" style={{ fontSize: 34, fontWeight: 700 }}>{health.score}</span>
              <span className="dos-mono" style={{ fontSize: 13, color: 'var(--ink-faint)' }}>/ 100</span>
            </div>
            <div className="dos-mono" style={{ fontSize: 10.5, color: 'var(--ink-faint)', marginTop: 4 }}>Heuristic indicator computed from this corpus — not a validated metric</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, auto)', gap: '10px 22px' }}>
            {Object.entries(counts).map(([k, v]) => (
              <div key={k}>
                <div className="dos-mono" style={{ fontSize: 18, fontWeight: 700, color: k === 'Conflicts' && v > 0 ? 'var(--conflict)' : 'var(--ink)' }}>{v}</div>
                <div className="dos-mono" style={{ fontSize: 10.5, color: 'var(--ink-faint)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{k}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
          {health.dims.map((d) => (
            <div key={d.label}>
              <div className="dos-mono" style={{ fontSize: 10.5, color: 'var(--ink-faint)', marginBottom: 3 }}>{d.label}</div>
              <div style={{ height: 5, background: 'var(--line-soft)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${Math.min(100, d.value)}%`, background: 'var(--indigo)', borderRadius: 3 }} />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="dos-mono dos-eyebrow" style={{ marginBottom: 10 }}>Semantic objects</div>
      <div style={{ display: 'grid', gap: 12 }}>
        {Object.values(OBJECTS).map((o) => <ObjectCard key={o.id} obj={o} onSelect={onSelectObject} />)}
      </div>
    </div>
  );
}

/* ================================================================== */
/* VIEW: GRAPH                                                          */
/* ================================================================== */

const EDGE_STYLE = {
  CONTAINS: { stroke: 'var(--line-strong)', width: 1.5, dash: 'none' },
  DERIVED_FROM: { stroke: 'var(--teal)', width: 1.75, dash: 'none' },
  DEPENDS_ON: { stroke: 'var(--teal)', width: 1.75, dash: 'none' },
  CONTRADICTS: { stroke: 'var(--conflict)', width: 2, dash: '5 4' },
  CONSTRAINED_BY: { stroke: 'var(--conflict)', width: 2, dash: '2 3' },
  REFERENCES: { stroke: 'var(--ink-faint)', width: 1.25, dash: '3 4' },
};
function Legend({ swatch, label, dashed }) {
  return (
    <span className="dos-mono" style={{ fontSize: 10.5, color: 'var(--ink-faint)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={{ width: 14, height: 0, borderTop: `2px ${dashed ? 'dashed' : 'solid'} ${swatch}`, display: 'inline-block' }} />
      {label}
    </span>
  );
}
function GraphView({ onSelectObject, onOpenPreview }) {
  const [hover, setHover] = useState('obl-payment');
  const neighbors = useMemo(() => {
    const set = new Set([hover]);
    EDGES.forEach((e) => { if (e.from === hover) set.add(e.to); if (e.to === hover) set.add(e.from); });
    return set;
  }, [hover]);
  return (
    <div className="dos-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
        <div className="dos-mono dos-eyebrow" style={{ margin: 0 }}>Intelligence graph &middot; hover or tap a node</div>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          <Legend swatch="var(--line-strong)" label="Contains" />
          <Legend swatch="var(--teal)" label="Depends / derives" />
          <Legend swatch="var(--conflict)" dashed label="Contradicts / constrains" />
          <Legend swatch="var(--ink-faint)" dashed label="References" />
        </div>
      </div>
      <svg viewBox="0 0 900 560" style={{ width: '100%', height: 'auto', display: 'block' }}>
        {EDGES.map((e, i) => {
          const [x1, y1] = POS[e.from]; const [x2, y2] = POS[e.to];
          const active = neighbors.has(e.from) && neighbors.has(e.to);
          const style = EDGE_STYLE[e.type];
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={style.stroke} strokeWidth={style.width} strokeDasharray={style.dash === 'none' ? undefined : style.dash} opacity={active ? 0.95 : 0.18} />;
        })}
        {Object.keys(POS).map((id) => {
          const [x, y] = POS[id];
          const isDoc = isDocument(id);
          const isCenter = id === 'obl-payment';
          const dim = !neighbors.has(id);
          const label = isDoc ? DOC_META[id].label : OBJECTS[id].type;
          const r = isCenter ? 40 : isDoc ? 34 : 30;
          return (
            <g key={id} opacity={dim ? 0.3 : 1} style={{ cursor: 'pointer' }} onMouseEnter={() => setHover(id)} onClick={() => { setHover(id); isDoc ? onOpenPreview(id) : onSelectObject(id); }}>
              {isDoc ? (
                <rect x={x - r} y={y - 18} width={r * 2} height={36} rx={8} fill="var(--surface)" stroke={isCenter ? 'var(--ink)' : 'var(--line-strong)'} strokeWidth={isCenter ? 2 : 1.25} />
              ) : (
                <circle cx={x} cy={y} r={r * 0.55} fill={TYPE_META[OBJECTS[id].type].bg} stroke={isCenter ? 'var(--ink)' : TYPE_META[OBJECTS[id].type].c} strokeWidth={isCenter ? 2.5 : 1.5} />
              )}
              <text x={x} y={y + 4} textAnchor="middle" className="dos-mono" fontSize={isDoc ? 10 : 9} fontWeight={isCenter ? 700 : 500} fill="var(--ink)" style={{ pointerEvents: 'none' }}>
                {label.length > 15 ? label.slice(0, 14) + '…' : label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/* ================================================================== */
/* VIEW: CONSEQUENCES — "what does this affect?" + simulation           */
/* ================================================================== */

function NodeChip({ id, chain, onOpen }) {
  const isDoc = isDocument(id);
  const label = isDoc ? DOC_META[id].label : `${OBJECTS[id].type}: ${OBJECTS[id].statement.slice(0, 40)}${OBJECTS[id].statement.length > 40 ? '…' : ''}`;
  return (
    <div style={{ marginBottom: 6 }}>
      <button onClick={() => onOpen(id, isDoc)} className="dos-mono" style={{ fontSize: 11.5, padding: '5px 10px', borderRadius: 6, background: 'var(--line-soft)', color: 'var(--ink)', display: 'inline-flex', alignItems: 'center', gap: 5, border: 'none', cursor: 'pointer' }}>
        {isDoc ? <FileText size={11} /> : null}{label}
      </button>
      {chain && chain.length > 0 && (
        <div className="dos-mono" style={{ fontSize: 10, color: 'var(--ink-faint)', marginTop: 3, paddingLeft: 4 }}>
          why: {chain.map((c, i) => (i === 0 ? c.from : '') + ` \u2192(${c.type.toLowerCase()})\u2192 ` + c.to).join('')}
        </div>
      )}
    </div>
  );
}
function Bucket({ title, ids, tone, explain, onOpen }) {
  if (!ids.length) return null;
  return (
    <div style={{ marginBottom: 14 }}>
      <div className="dos-mono" style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: tone, marginBottom: 6 }}>{title} &middot; {ids.length}</div>
      {ids.map((id) => <NodeChip key={id} id={id} chain={explain ? explain(id) : null} onOpen={onOpen} />)}
    </div>
  );
}

function ConsequencesView({
  canonicalWorld, canonicalValue, exploration, onExplore, onCloseExplore,
  scenario, draftValue, setDraftValue, validationError,
  onPropose, onApprove, onReject, onDiscard, onOpenNode,
}) {
  return (
    <div>
      {!scenario && (
        <div className="dos-card" style={{ marginBottom: 18 }}>
          <TypeBadge type={OBJECTS['obl-payment'].type} />
          <p className="dos-serif" style={{ fontSize: 19, lineHeight: 1.5, margin: '10px 0 4px', fontWeight: 500 }}>{OBJECTS['obl-payment'].statement}</p>
          <p className="dos-mono" style={{ fontSize: 12, color: 'var(--ink-faint)', margin: '0 0 18px' }}>Customer Agreement &sect;4.2 &middot; current value {fmtTerm(canonicalValue)}</p>
          <button onClick={onExplore} className="dos-mono dos-btn"><HelpCircle size={13} /> What does this affect?</button>
        </div>
      )}

      {exploration && !scenario && (
        <div className="dos-card" style={{ marginBottom: 18, borderColor: 'var(--indigo)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div className="dos-mono dos-eyebrow" style={{ marginBottom: 10 }}>Consequence closure &middot; current state, no proposed change</div>
            <button onClick={onCloseExplore} className="dos-icon-btn" aria-label="Close"><X size={14} /></button>
          </div>
          <Bucket title="Direct" ids={exploration.docs.direct.concat(exploration.objects.direct)} tone="var(--conflict)" explain={exploration.explain} onOpen={onOpenNode} />
          <Bucket title="Indirect" ids={exploration.docs.indirect.concat(exploration.objects.indirect)} tone="var(--indigo)" explain={exploration.explain} onOpen={onOpenNode} />
          <Bucket title="Potential / context only" ids={exploration.docs.potential.concat(exploration.objects.potential)} tone="var(--ink-faint)" explain={exploration.explain} onOpen={onOpenNode} />
          {exploration.conflicts.length > 0 && (
            <div style={{ marginTop: 4, padding: 12, background: 'var(--conflict-soft)', borderRadius: 8, display: 'flex', gap: 8 }}>
              <AlertTriangle size={16} color="var(--conflict)" style={{ flexShrink: 0, marginTop: 1 }} />
              <div className="dos-mono" style={{ fontSize: 11.5, color: 'var(--ink-soft)' }}>{exploration.conflicts.length} conflict relationship(s) touch this obligation (Sales Terms default, Enterprise cap) — reported separately from impact, since a conflict is a relationship of tension, not a downstream effect.</div>
            </div>
          )}
        </div>
      )}

      {!scenario && (
        <div className="dos-card">
          <div className="dos-mono dos-eyebrow" style={{ marginBottom: 10 }}>Propose a change</div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
            <label className="dos-mono" style={{ fontSize: 11.5, color: 'var(--ink-soft)' }}>
              New Payment Term (days)
              <input type="number" value={draftValue} onChange={(e) => setDraftValue(e.target.value)}
                className="dos-mono" style={{ display: 'block', marginTop: 6, width: 100, padding: '8px 10px', border: `1.5px solid ${validationError ? 'var(--conflict)' : 'var(--line)'}`, borderRadius: 7, fontSize: 15, background: 'var(--surface)', color: 'var(--ink)' }} />
            </label>
            <button onClick={onPropose} className="dos-mono dos-btn dos-btn-primary"><Zap size={13} /> Simulate change</button>
          </div>
          {validationError && (
            <div className="dos-mono" style={{ fontSize: 11.5, color: 'var(--conflict)', marginTop: 8, display: 'flex', alignItems: 'center', gap: 5 }}>
              <XCircle size={13} /> {validationError}
            </div>
          )}
        </div>
      )}

      {scenario && scenario.state !== 'COMMITTED' && scenario.state !== 'REJECTED' && scenario.state !== 'ROLLED_BACK' && (
        <ScenarioReview scenario={scenario} onApprove={onApprove} onReject={onReject} onOpenNode={onOpenNode} />
      )}
      {scenario && (scenario.state === 'COMMITTED' || scenario.state === 'REJECTED' || scenario.state === 'ROLLED_BACK') && (
        <ScenarioOutcome scenario={scenario} onDiscard={onDiscard} />
      )}
    </div>
  );
}

function ScenarioReview({ scenario, onApprove, onReject, onOpenNode }) {
  const { consequences, forecast, diff, oldValue, newValue, state } = scenario;
  return (
    <div>
      <div className="dos-card" style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
          <div className="dos-mono dos-eyebrow" style={{ margin: 0 }}>Candidate world &middot; not yet canonical</div>
          <StateBadge state={state} />
        </div>
        <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
          <div style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--line-soft)', flex: '1 1 160px' }}>
            <div className="dos-mono" style={{ fontSize: 10, color: 'var(--ink-faint)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Current (canonical)</div>
            <div className="dos-serif" style={{ fontSize: 18, fontWeight: 700 }}>{fmtTerm(oldValue)}</div>
          </div>
          <div style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--indigo-soft)', flex: '1 1 160px' }}>
            <div className="dos-mono" style={{ fontSize: 10, color: 'var(--indigo)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Proposed (candidate world)</div>
            <div className="dos-serif" style={{ fontSize: 18, fontWeight: 700, color: 'var(--indigo)' }}>{fmtTerm(newValue)}</div>
          </div>
        </div>
      </div>

      <div className="dos-card" style={{ marginBottom: 18 }}>
        <div className="dos-mono dos-eyebrow" style={{ marginBottom: 10 }}>Consequences of this change</div>
        <Bucket title="Direct" ids={consequences.docs.direct.concat(consequences.objects.direct)} tone="var(--conflict)" explain={consequences.explain} onOpen={onOpenNode} />
        <Bucket title="Indirect" ids={consequences.docs.indirect.concat(consequences.objects.indirect)} tone="var(--indigo)" explain={consequences.explain} onOpen={onOpenNode} />
        <Bucket title="Potential / context only" ids={consequences.docs.potential.concat(consequences.objects.potential)} tone="var(--ink-faint)" explain={consequences.explain} onOpen={onOpenNode} />
      </div>

      <div className="dos-card" style={{ marginBottom: 18 }}>
        <div className="dos-mono dos-eyebrow" style={{ marginBottom: 10 }}>Contradiction forecast</div>
        <div className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)', marginBottom: 10 }}>{forecast.preExistingCount} pre-existing &middot; {forecast.resolved.length} resolved by this change &middot; {forecast.stillOpen.length} still open &middot; {forecast.introduced.length} newly introduced</div>
        {forecast.resolved.map(({ otherId }) => (
          <div key={otherId} style={{ padding: 12, background: 'var(--verified-soft)', borderRadius: 8, display: 'flex', gap: 8, marginBottom: 8 }}>
            <CheckCircle2 size={16} color="var(--verified)" style={{ flexShrink: 0, marginTop: 1 }} />
            <div className="dos-mono" style={{ fontSize: 11.5, color: 'var(--ink-soft)' }}>Resolved: this value now matches {DOC_META[OBJECTS[otherId].doc].label} &sect;{OBJECTS[otherId].section} exactly.</div>
          </div>
        ))}
        {forecast.stillOpen.map(({ otherId }) => (
          <div key={otherId} style={{ padding: 12, background: 'var(--conflict-soft)', borderRadius: 8, display: 'flex', gap: 8, marginBottom: 8 }}>
            <AlertTriangle size={16} color="var(--conflict)" style={{ flexShrink: 0, marginTop: 1 }} />
            <div className="dos-mono" style={{ fontSize: 11.5, color: 'var(--ink-soft)' }}>Still open: {DOC_META[OBJECTS[otherId].doc].label} &sect;{OBJECTS[otherId].section} specifies {OBJECTS[otherId].value} days — not auto-resolved, flagged for human review.</div>
          </div>
        ))}
        {forecast.introduced.map(({ otherId, constraint }) => (
          <div key={otherId} style={{ padding: 12, background: 'var(--conflict-soft)', borderRadius: 8, display: 'flex', gap: 8, marginBottom: 8 }}>
            <XCircle size={16} color="var(--conflict)" style={{ flexShrink: 0, marginTop: 1 }} />
            <div className="dos-mono" style={{ fontSize: 11.5, color: 'var(--ink-soft)' }}>New: this value exceeds the {DOC_META[constraint.doc].label} &sect;{constraint.section} cap ({fmtTerm(constraint.capValue)}) — the current value did not violate it. Verification will not pass while this stands.</div>
          </div>
        ))}
        {forecast.preExistingCount === 0 && forecast.introduced.length === 0 && (
          <div className="dos-mono" style={{ fontSize: 11.5, color: 'var(--ink-faint)' }}>No conflicts touch this obligation.</div>
        )}
      </div>

      <div className="dos-card" style={{ marginBottom: 18 }}>
        <div className="dos-mono dos-eyebrow" style={{ marginBottom: 10 }}>Text changes &middot; {diff.textChanges.length} section(s) in {diff.changedDocIds.length} document(s)</div>
        {diff.textChanges.map((c) => (
          <DiffLine key={`${c.doc}-${c.section}`} label={`${DOC_META[c.doc].label} — §${c.section}`} oldText={c.before} newText={c.after} />
        ))}
        <div className="dos-mono" style={{ fontSize: 11, color: 'var(--verified)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 5 }}>
          <CheckCircle2 size={12} /> {diff.unchangedDocIds.length} document(s) outside the change — untouched: {diff.unchangedDocIds.map((id) => DOC_META[id].label).join(', ')}
        </div>
        <div className="dos-mono dos-eyebrow" style={{ marginTop: 16, marginBottom: 8 }}>Semantic diff &middot; {diff.semanticChanges.length} change(s)</div>
        {diff.semanticChanges.map((c, i) => (
          <SemanticDiffRow key={i} change={c} />
        ))}
      </div>

      {scenario.state === 'REVIEW' && (
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={onApprove} className="dos-mono dos-btn dos-btn-primary"><CheckCircle2 size={14} /> Approve &amp; apply</button>
          <button onClick={onReject} className="dos-mono dos-btn"><Undo2 size={13} /> Reject</button>
        </div>
      )}
    </div>
  );
}

function ScenarioOutcome({ scenario, onDiscard }) {
  const committed = scenario.state === 'COMMITTED';
  const rolledBack = scenario.state === 'ROLLED_BACK';
  const tone = committed ? 'var(--verified)' : rolledBack ? 'var(--conflict)' : 'var(--ink-faint)';
  const Icon = committed ? CheckCircle2 : rolledBack ? RotateCcw : XCircle;
  const headline = committed ? 'Scenario committed' : rolledBack ? 'Rolled back — verification failed' : 'Scenario rejected';
  return (
    <div>
      <div className="dos-card" style={{ borderColor: tone, marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <Icon size={18} color={tone} />
          <span className="dos-serif" style={{ fontSize: 18, fontWeight: 700 }}>{headline}</span>
        </div>
        {committed && (
          <p className="dos-mono" style={{ fontSize: 12.5, color: 'var(--ink-soft)', margin: 0 }}>
            Payment Term changed <strong>{fmtTerm(scenario.oldValue)} &rarr; {fmtTerm(scenario.newValue)}</strong>. The candidate world replaced canonical state in a single update — there is no intermediate point where some documents reflected the old term and others the new one.
          </p>
        )}
        {rolledBack && (
          <p className="dos-mono" style={{ fontSize: 12.5, color: 'var(--ink-soft)', margin: 0 }}>Canonical state is unchanged — Payment Term remains {fmtTerm(scenario.oldValue)}. The candidate world failed verification and was discarded before anything was committed.</p>
        )}
        {!committed && !rolledBack && (
          <p className="dos-mono" style={{ fontSize: 12.5, color: 'var(--ink-soft)', margin: 0 }}>Canonical state is unchanged — Payment Term remains {fmtTerm(scenario.oldValue)}.</p>
        )}
      </div>
      {scenario.verification && (
        <div className="dos-card" style={{ marginBottom: 18 }}>
          <div className="dos-mono dos-eyebrow">Verification</div>
          <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
            {scenario.verification.checks.map((c) => (
              <div key={c.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                {c.pass ? <CheckCircle2 size={15} color="var(--verified)" style={{ marginTop: 1, flexShrink: 0 }} /> : <XCircle size={15} color="var(--conflict)" style={{ marginTop: 1, flexShrink: 0 }} />}
                <div>
                  <div className="dos-mono" style={{ fontSize: 12.5 }}>{c.label}</div>
                  {c.detail && <div className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)' }}>{c.detail}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      <button onClick={onDiscard} className="dos-mono dos-btn"><RotateCcw size={13} /> Start a new scenario</button>
    </div>
  );
}

function DiffLine({ label, oldText, newText }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)', marginBottom: 3 }}>{label}</div>
      <div className="dos-serif" style={{ fontSize: 13 }}>
        <span style={{ background: 'var(--conflict-soft)', color: 'var(--conflict)', padding: '2px 6px', borderRadius: 4, textDecoration: 'line-through', marginRight: 6, display: 'inline-block' }}>{oldText}</span>
        <span style={{ background: 'var(--verified-soft)', color: 'var(--verified)', padding: '2px 6px', borderRadius: 4, display: 'inline-block' }}>{newText}</span>
      </div>
    </div>
  );
}
function SemanticDiffRow({ change }) {
  const labels = {
    VALUE_CHANGED: ['CHANGED', 'var(--indigo)'],
    DEPENDENT_RESOLUTION_CHANGED: ['DEPENDENT', 'var(--teal)'],
    CONFLICT_RESOLVED: ['RESOLVED', 'var(--verified)'],
    CONFLICT_CREATED: ['NEW CONFLICT', 'var(--conflict)'],
  };
  const [tag, tone] = labels[change.kind] || ['CHANGED', 'var(--indigo)'];
  const obj = OBJECTS[change.objectId];
  let text;
  if (change.kind === 'VALUE_CHANGED') text = `${obj.statement} (${change.before} \u2192 ${change.after} days)`;
  else if (change.kind === 'DEPENDENT_RESOLUTION_CHANGED') text = `${obj.statement} — resolution now depends on the new value of ${OBJECTS[change.dependsOn].type.toLowerCase()} "${OBJECTS[change.dependsOn].statement.slice(0, 36)}…"`;
  else if (change.kind === 'CONFLICT_RESOLVED') text = `${obj.statement} — no longer in conflict with the proposed value`;
  else text = `${obj.statement} — the proposed value now conflicts with this`;
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 6 }}>
      <span className="dos-mono" style={{ fontSize: 10, fontWeight: 700, color: tone, width: 88, flexShrink: 0 }}>{tag}</span>
      <span className="dos-serif" style={{ fontSize: 13.5 }}>{text}</span>
    </div>
  );
}

/* ================================================================== */
/* VIEW: EVIDENCE                                                       */
/* ================================================================== */

function EvidenceView({ world, onOpenPreview }) {
  return (
    <div style={{ display: 'grid', gap: 14 }}>
      {Object.values(OBJECTS).map((obj) => {
        const resolved = resolveEvidence(world, OBJECTS, obj.id);
        return (
          <div key={obj.id} className="dos-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <TypeBadge type={obj.type} />
              <StatusDot status={obj.status} />
            </div>
            <p className="dos-serif" style={{ fontSize: 15, fontWeight: 500, margin: '0 0 12px' }}>{obj.statement}</p>
            <div className="dos-grid-2" style={{ marginBottom: 12 }}>
              <div>
                <div className="dos-mono dos-eyebrow">Supported by</div>
                <button onClick={() => onOpenPreview(obj.doc)} className="dos-mono" style={{ fontSize: 12.5, color: 'var(--indigo)', fontWeight: 600 }}>{DOC_META[obj.doc].label} &sect;{obj.section}</button>
              </div>
              <div>
                <div className="dos-mono dos-eyebrow">Resolution</div>
                <div className="dos-mono" style={{ fontSize: 12.5, color: resolved.resolved ? 'var(--verified)' : 'var(--conflict)', display: 'flex', alignItems: 'center', gap: 5 }}>
                  {resolved.resolved ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                  {resolved.resolved ? 'Resolves against current text' : 'Did not resolve'}
                </div>
              </div>
            </div>
            <div className="dos-mono dos-eyebrow">Source span</div>
            <p className="dos-serif" style={{ fontSize: 13, fontStyle: 'italic', color: 'var(--ink-soft)', borderLeft: '2px solid var(--amber)', paddingLeft: 10, margin: '4px 0 0' }}>&ldquo;&hellip;{resolved.text}&hellip;&rdquo;</p>
          </div>
        );
      })}
    </div>
  );
}

/* ================================================================== */
/* VIEW: HISTORY                                                        */
/* ================================================================== */

function HistoryView({ version, auditLog }) {
  return (
    <div>
      <div className="dos-card" style={{ marginBottom: 18 }}>
        <div className="dos-mono dos-eyebrow" style={{ marginBottom: 10 }}>Canonical world version</div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {Array.from({ length: version }, (_, i) => i + 1).map((v) => (
            <React.Fragment key={v}>
              <span className="dos-mono" style={{ fontSize: 12, fontWeight: 700, padding: '5px 11px', borderRadius: 999, background: v === version ? 'var(--indigo)' : 'var(--line-soft)', color: v === version ? '#fff' : 'var(--ink-soft)' }}>v{v}</span>
              {v < version && <ArrowRight size={13} color="var(--ink-faint)" />}
            </React.Fragment>
          ))}
        </div>
      </div>
      <div className="dos-mono dos-eyebrow" style={{ marginBottom: 10 }}>Audit trail</div>
      {auditLog.length === 0 ? (
        <div className="dos-card"><p className="dos-mono" style={{ fontSize: 12.5, color: 'var(--ink-faint)', margin: 0 }}>No scenarios have run yet. Propose a change from the Consequences view to see it recorded here — committed, rejected, or rolled back.</p></div>
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {auditLog.map((entry) => (
            <div key={entry.id} className="dos-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
                <div>
                  <div className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)' }}>{entry.time.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} &middot; {entry.actor} &middot; {entry.id}</div>
                  <div className="dos-serif" style={{ fontSize: 14.5, fontWeight: 500, margin: '4px 0' }}>{entry.operation}</div>
                  <div className="dos-mono" style={{ fontSize: 12.5, color: 'var(--ink-soft)' }}>{entry.change}</div>
                </div>
                <StateBadge state={entry.finalState} />
              </div>
              {entry.affectedCount != null && <div className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)', marginTop: 8 }}>{entry.affectedCount} document(s) with text changes &middot; {entry.checksRun} verification checks run</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/* APP SHELL                                                            */
/* ================================================================== */

const TABS = [
  { id: 'document', label: 'Document', icon: FileText },
  { id: 'intelligence', label: 'Intelligence', icon: Eye },
  { id: 'consequences', label: 'Consequences', icon: Zap },
  { id: 'evidence', label: 'Evidence', icon: GitBranch },
  { id: 'history', label: 'History', icon: HistoryIcon },
  { id: 'graph', label: 'Graph', icon: Network },
];

export default function SuperDocsRealityEngine() {
  const [view, setView] = useState('document');
  const [inspecting, setInspecting] = useState(null);
  const [previewDoc, setPreviewDoc] = useState(null);
  const [canonicalValue, setCanonicalValue] = useState(30);
  const [draftValue, setDraftValue] = useState('60');
  const [validationError, setValidationError] = useState(null);
  const [exploration, setExploration] = useState(null);
  const [scenario, setScenario] = useState(null);
  const [auditLog, setAuditLog] = useState([]);
  const [version, setVersion] = useState(1);

  const canonicalWorld = useMemo(() => buildWorld(DOC_TEXT, OBJECTS, canonicalValue), [canonicalValue]);
  const health = useMemo(() => computeHealth(canonicalWorld, EDGES, OBJECTS, ENTITIES, REQUIRED_SECTIONS, DOC_META), [canonicalWorld]);

  function explore() {
    setExploration(computeConsequences(EDGES, isDocument, ALL_IDS, 'obl-payment'));
  }

  function propose() {
    const validation = validateProposedValue(draftValue);
    if (!validation.valid) { setValidationError(validation.reason); return; }
    setValidationError(null);
    try {
      let s = nextState('DRAFT', 'ANALYZING');
      const consequences = computeConsequences(EDGES, isDocument, ALL_IDS, 'obl-payment');
      s = nextState(s, 'SIMULATED');
      const candidateWorld = buildWorld(DOC_TEXT, OBJECTS, validation.value);
      const forecast = forecastContradictions(EDGES, OBJECTS, 'obl-payment', canonicalValue, validation.value);
      const diff = diffWorlds(canonicalWorld, candidateWorld, EDGES, OBJECTS, forecast);
      s = nextState(s, 'REVIEW');
      setScenario({ state: s, oldValue: canonicalValue, newValue: validation.value, consequences, forecast, diff, candidateWorld, verification: null });
      setExploration(null);
    } catch (err) {
      setValidationError(err.message);
    }
  }

  function approve() {
    setScenario((sc) => {
      try {
        let s = nextState(sc.state, 'APPROVED');
        s = nextState(s, 'APPLYING');
        const verification = runVerification(canonicalWorld, sc.candidateWorld, sc.diff, sc.forecast, EDGES, OBJECTS, DOC_META, REQUIRED_SECTIONS);
        s = nextState(s, 'VERIFYING');
        const result = commitWorld(version, verification, sc.candidateWorld);
        s = nextState(s, result.committed ? 'COMMITTED' : 'ROLLED_BACK');
        const entry = {
          id: `SCN-${String(auditLog.length + 1).padStart(3, '0')}`,
          time: new Date(), actor: 'Demo User',
          operation: result.committed ? 'Applied scenario' : 'Attempted scenario (rolled back)',
          change: `Payment Term: ${fmtTerm(sc.oldValue)} \u2192 ${fmtTerm(sc.newValue)}`,
          affectedCount: sc.diff.changedDocIds.length,
          checksRun: verification.checks.length,
          finalState: s,
        };
        setAuditLog((log) => [entry, ...log]);
        if (result.committed) { setCanonicalValue(result.world.paymentTermDays); setVersion(result.version); }
        return { ...sc, state: s, verification };
      } catch (err) {
        return { ...sc, state: 'FAILED', error: err.message };
      }
    });
  }

  function reject() {
    setScenario((sc) => {
      const s = nextState(sc.state, 'REJECTED');
      setAuditLog((log) => [{
        id: `SCN-${String(log.length + 1).padStart(3, '0')}`, time: new Date(), actor: 'Demo User',
        operation: 'Rejected scenario', change: `Payment Term: ${fmtTerm(sc.oldValue)} \u2192 ${fmtTerm(sc.newValue)} (not applied)`,
        affectedCount: null, checksRun: 0, finalState: s,
      }, ...log]);
      return { ...sc, state: s };
    });
  }

  function discard() {
    setScenario(null);
    setValidationError(null);
    setDraftValue(String(canonicalValue + 30));
  }

  function selectObject(id) { setInspecting(id); setPreviewDoc(null); }
  function openPreview(id) { setPreviewDoc(id); setInspecting(null); }
  function openNode(id, isDoc) { if (isDoc) jumpToDoc(id); else selectObject(id); }
  function jumpToDoc(id) {
    setInspecting(null);
    if (id === 'agreement') { setPreviewDoc(null); setView('document'); }
    else { setPreviewDoc(id); }
  }

  return (
    <div className="dos-root">
      <style>{`
        .dos-root {
          --paper: #EEF0E9; --surface: #FFFFFF; --ink: #1C2024; --ink-soft: #5B6570; --ink-faint: #8A939B;
          --line: #DADFD9; --line-soft: #E7E9E2; --line-strong: #C7CCC4;
          --amber: #93641A; --amber-soft: #F1E6CC; --indigo: #35507A; --indigo-soft: #E1E7F0;
          --teal: #2E6E68; --teal-soft: #DCEAE6; --conflict: #9C3B32; --conflict-soft: #F3E1DE; --verified: #3D7A5C; --verified-soft: #E1EEE6;
          background: var(--paper); color: var(--ink); font-family: Georgia, 'Iowan Old Style', 'Times New Roman', serif;
          padding: 20px; border-radius: 12px; max-width: 1080px; margin: 0 auto; box-sizing: border-box;
        }
        .dos-root * { box-sizing: border-box; }
        .dos-mono { font-family: ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, monospace; }
        .dos-serif { font-family: Georgia, 'Iowan Old Style', 'Times New Roman', serif; }
        .dos-eyebrow { font-size: 10.5px; color: var(--ink-faint); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 2px; }
        .dos-card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; }
        .dos-card-hover { transition: box-shadow 0.15s ease; border: none; box-shadow: 0 0 0 1px var(--line) inset; }
        .dos-card-hover:hover { box-shadow: 0 0 0 1.5px var(--indigo) inset; }
        .dos-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
        .dos-btn { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 600; padding: 9px 15px; border-radius: 7px; border: 1.5px solid var(--line-strong); background: var(--surface); color: var(--ink); cursor: pointer; transition: background 0.12s ease, border-color 0.12s ease; }
        .dos-btn:hover { border-color: var(--ink-soft); }
        .dos-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .dos-btn-primary { background: var(--ink); border-color: var(--ink); color: var(--paper); }
        .dos-btn-primary:hover { background: var(--indigo); border-color: var(--indigo); }
        .dos-pill { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; padding: 5px 10px; border-radius: 999px; border: 1.5px solid var(--line-strong); background: var(--surface); color: var(--ink-soft); cursor: pointer; }
        .dos-pill:hover { border-color: var(--indigo); color: var(--indigo); }
        .dos-icon-btn { background: none; border: none; color: var(--ink-faint); cursor: pointer; padding: 4px; border-radius: 5px; display: inline-flex; }
        .dos-icon-btn:hover { background: var(--line-soft); color: var(--ink); }
        button { font: inherit; }
        button:focus-visible, input:focus-visible { outline: 2px solid var(--indigo); outline-offset: 2px; }
        .dos-header { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; margin-bottom: 16px; }
        .dos-tabs { display: flex; gap: 4px; margin-bottom: 18px; border-bottom: 1.5px solid var(--line); overflow-x: auto; }
        .dos-tab { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; padding: 9px 13px; border: none; background: none; color: var(--ink-faint); cursor: pointer; border-bottom: 2.5px solid transparent; margin-bottom: -1.5px; white-space: nowrap; }
        .dos-tab:hover { color: var(--ink); }
        .dos-tab-active { color: var(--indigo); border-bottom-color: var(--indigo); }
        @media (max-width: 640px) { .dos-grid-2 { grid-template-columns: 1fr; } .dos-card { padding: 15px; } svg { max-height: 340px; } }
        @media (prefers-reduced-motion: reduce) { .dos-root * { transition: none !important; } }
      `}</style>

      <div className="dos-header">
        <div>
          <div className="dos-mono" style={{ fontSize: 11, color: 'var(--ink-faint)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'flex', alignItems: 'center', gap: 6 }}>
            <Network size={13} /> SuperDocs Reality Engine
          </div>
          <h1 className="dos-serif" style={{ fontSize: 24, fontWeight: 700, margin: '3px 0 0' }}>Northstar Customer Agreement</h1>
          <p className="dos-mono" style={{ fontSize: 10.5, color: 'var(--ink-faint)', margin: '2px 0 0' }}>Understand the change. Simulate the consequences.</p>
        </div>
        <div className="dos-mono" style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 10.5, color: 'var(--ink-faint)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Health</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: health.score >= 85 ? 'var(--verified)' : 'var(--amber)' }}>{health.score}<span style={{ fontSize: 12, color: 'var(--ink-faint)', fontWeight: 500 }}>/100</span></div>
        </div>
      </div>

      <div className="dos-tabs">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button key={t.id} onClick={() => { setView(t.id); setInspecting(null); setPreviewDoc(null); }} className={`dos-mono dos-tab ${view === t.id ? 'dos-tab-active' : ''}`}>
              <Icon size={13} /> {t.label}
            </button>
          );
        })}
      </div>

      <main>
        {inspecting && <Inspector objId={inspecting} world={canonicalWorld} onClose={() => setInspecting(null)} onJump={jumpToDoc} />}
        {previewDoc && <DocPreview docId={previewDoc} world={canonicalWorld} onClose={() => setPreviewDoc(null)} onSelectObject={selectObject} />}

        {view === 'document' && <DocumentView world={canonicalWorld} onSelectObject={selectObject} onOpenPreview={openPreview} />}
        {view === 'intelligence' && <IntelligenceView health={health} onSelectObject={selectObject} />}
        {view === 'graph' && <GraphView onSelectObject={selectObject} onOpenPreview={openPreview} />}
        {view === 'consequences' && (
          <ConsequencesView
            canonicalWorld={canonicalWorld} canonicalValue={canonicalValue} exploration={exploration} onExplore={explore} onCloseExplore={() => setExploration(null)}
            scenario={scenario} draftValue={draftValue} setDraftValue={setDraftValue} validationError={validationError}
            onPropose={propose} onApprove={approve} onReject={reject} onDiscard={discard} onOpenNode={openNode}
          />
        )}
        {view === 'evidence' && <EvidenceView world={canonicalWorld} onOpenPreview={openPreview} />}
        {view === 'history' && <HistoryView version={version} auditLog={auditLog} />}
      </main>
    </div>
  );
}
