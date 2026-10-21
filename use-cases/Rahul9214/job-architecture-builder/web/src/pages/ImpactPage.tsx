import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import { BeforeAfter } from "../components/BeforeAfter";
import { Disclosure } from "../components/Disclosure";
import { Metric } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { Select } from "../components/Select";
import { Empty, ErrorBanner, Loading } from "../components/Status";
import { useCorpus } from "../corpus";
import { dimensionLabel } from "../labels";
import type { FrameworkPayload, ImpactPayload, UpdatePlanView } from "../types";

export function ImpactPage() {
  const { corpusId, analyzed } = useCorpus();
  const [framework, setFramework] = useState<FrameworkPayload | null>(null);
  const [levelId, setLevelId] = useState("");
  const [dimension, setDimension] = useState("scope");
  const [value, setValue] = useState("");
  const [impact, setImpact] = useState<ImpactPayload | null>(null);
  const [plans, setPlans] = useState<UpdatePlanView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!analyzed) {
      setFramework(null);
      return;
    }
    let cancelled = false;
    api
      .framework(corpusId)
      .then((payload) => {
        if (cancelled) return;
        setFramework(payload);
        const nextLevel = payload.default_occupied_level_id ?? payload.levels[0]?.id ?? "";
        setLevelId(nextLevel);
        setDimension(payload.editable_dimensions?.[0] ?? "scope");
        setValue("");
        setImpact(null);
        setPlans([]);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Unable to load framework.");
      });
    return () => {
      cancelled = true;
    };
  }, [analyzed, corpusId]);

  const selected = framework?.levels.find((item) => item.id === levelId);
  const oldValue = useMemo(() => {
    if (!selected) return "";
    const raw = selected[dimension as keyof typeof selected];
    return typeof raw === "string" ? raw : String(raw ?? "");
  }, [dimension, selected]);

  async function runImpact() {
    setBusy(true);
    setError(null);
    try {
      const payload = await api.impact(corpusId, { level_id: levelId, dimension, value });
      setImpact(payload);
      setPlans([]);
    } catch (err) {
      setImpact(null);
      setPlans([]);
      setError(err instanceof ApiError ? err.message : "Impact analysis failed.");
    } finally {
      setBusy(false);
    }
  }

  async function runPlan() {
    setBusy(true);
    setError(null);
    try {
      const payload = await api.plan(corpusId, { level_id: levelId, dimension, value });
      setImpact(payload.impact);
      setPlans(payload.plans);
    } catch (err) {
      setPlans([]);
      setError(err instanceof ApiError ? err.message : "Update planning failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!analyzed) return <Empty>Analyze the corpus before proposing a canonical level change.</Empty>;
  if (!framework && !error) return <Loading label="Loading occupied levels" />;
  if (!framework) return error ? <ErrorBanner message={error} /> : null;

  const dimensions = framework.editable_dimensions?.length
    ? framework.editable_dimensions
    : ["scope"];

  return (
    <section>
      <PageHeader kicker="Canonical change" title="Change impact">
        Edit one occupied level and one canonical dimension. Dependent profiles are listed. Nothing is
        applied until human review.
      </PageHeader>
      {error ? <ErrorBanner message={error} /> : null}
      <article className="card">
        <div className="grid-2">
          <Select
            id="level"
            label="Occupied level"
            value={levelId}
            options={framework.levels.map((item) => ({
              id: item.id,
              label: `${item.label} v${item.version}`,
            }))}
            onChange={setLevelId}
          />
          <Select
            id="dimension"
            label="Canonical dimension"
            value={dimension}
            options={dimensions.map((item) => ({
              id: item,
              label: dimensionLabel(item),
            }))}
            onChange={setDimension}
          />
        </div>
        <div className="impact-hero">
          <article className="card impact-old">
            <h2>OLD</h2>
            <p>Current {dimensionLabel(dimension)} value.</p>
            <pre className="mono">{oldValue || "—"}</pre>
          </article>
          <article className="card impact-new">
            <h2>NEW</h2>
            <label htmlFor="proposed">
              Proposed value
              <textarea
                id="proposed"
                rows={6}
                value={value}
                onChange={(event) => setValue(event.target.value)}
              />
            </label>
          </article>
        </div>
        <div className="actions">
          <button type="button" className="ghost" onClick={() => void runImpact()} disabled={busy}>
            Analyze impact
          </button>
          <button type="button" className="primary" onClick={() => void runPlan()} disabled={busy}>
            Plan targeted updates
          </button>
        </div>
      </article>
      {impact ? (
        <>
          <div className="metrics">
            <Metric value={impact.affected_profiles_count} label="affected profiles" marker="misfit" />
            <Metric value={impact.unaffected_profiles_count} label="unaffected profiles" marker="fit" />
            <Metric
              value={impact.changed_dimensions.join(", ") || "none"}
              label="canonical dimensions changed"
              marker="tracks"
            />
          </div>
          {impact.reason ? <p>{impact.reason}</p> : null}
          {impact.affected_profiles_count === 0 ? (
            <Empty>No affected profiles for this edit.</Empty>
          ) : (
            <Disclosure title="Dependency path" defaultOpen>
              <h2>Why profiles are affected</h2>
              <ul>
                {impact.affected_sections.map((item) => (
                  <li key={`${item.profile_id}-${item.section_id}-${item.edge_id}`}>
                    {item.profile_id} / {item.section_id}: {item.reason} (edge {item.edge_id})
                  </li>
                ))}
              </ul>
            </Disclosure>
          )}
        </>
      ) : null}
      {plans.length ? (
        <>
          <h2>Targeted update plans</h2>
          <p>Unrelated sections preserved. Only listed fields change.</p>
          <div className="stack">
            {plans.map((plan) => (
              <article className="card" key={plan.plan_id}>
                <h3>
                  {plan.profile_id} · {plan.section_id}
                </h3>
                <p>{plan.reason}</p>
                <p>
                  Dependency {plan.dependency.id} · source v{plan.dependency.source_version}
                </p>
                <BeforeAfter before={plan.before} after={plan.after} />
                <p>
                  Unrelated sections preserved: {plan.preserved_rendered_fields.join(", ") || "none listed"}
                </p>
              </article>
            ))}
          </div>
          <p>
            Continue to <Link to="/review">human review</Link>. No default approval.
          </p>
        </>
      ) : null}
    </section>
  );
}
