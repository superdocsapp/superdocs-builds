import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorBanner, Loading } from "../components/Status";
import { useCorpus } from "../corpus";
import { useDialogA11y } from "../hooks/useDialogA11y";
import type { ProfileDetail, ProfileSummary } from "../types";

export function ProfilesPage() {
  const { corpusId, analyzed } = useCorpus();
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [artifacts, setArtifacts] = useState<ProfileDetail[]>([]);
  const [selected, setSelected] = useState<ProfileDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analyzed) {
      setProfiles([]);
      setArtifacts([]);
      setSelected(null);
      return;
    }
    let cancelled = false;
    api
      .profiles(corpusId)
      .then((payload) => {
        if (cancelled) return;
        setProfiles(payload.profiles);
        setArtifacts(payload.review_artifacts);
        setSelected(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Unable to load profiles.");
      });
    return () => {
      cancelled = true;
    };
  }, [analyzed, corpusId]);

  async function openProfile(profileId: string) {
    try {
      setSelected(await api.profile(corpusId, profileId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load profile.");
    }
  }

  if (!analyzed) return <Empty>Analyze the corpus to browse generated profiles.</Empty>;
  if (error) return <ErrorBanner message={error} />;
  if (!profiles.length && !artifacts.length) return <Loading label="Loading profiles" />;

  return (
    <section>
      <PageHeader title="Role profiles">
        Employee-readable profiles for classified roles. Provisional profiles stay marked as such.
      </PageHeader>
      {profiles.length === 0 ? <Empty>No normalized profiles in this corpus.</Empty> : null}
      {profiles.length ? (
        <div className="profile-list">
          {profiles.map((item) => (
            <article className="profile-row" key={item.profile_id}>
              <div>
                <h2>{item.display_title}</h2>
                <p>
                  {item.family_name} · {item.track_name} · {item.level_label}
                </p>
              </div>
              <div className="actions">
                <span className={`chip ${item.is_provisional ? "warn" : "good"}`}>
                  {item.is_provisional ? "provisional" : item.classification}
                </span>
                <button type="button" className="ghost" onClick={() => void openProfile(item.profile_id)}>
                  Open profile
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : null}
      <h2>Review artifacts</h2>
      {artifacts.length === 0 ? (
        <Empty>No misfit or unclassified provisional artifacts.</Empty>
      ) : (
        <div className="profile-list">
          {artifacts.map((item) => (
            <article className="profile-row" key={item.role_id}>
              <div>
                <h2>{item.title ?? item.display_title}</h2>
                <p>{item.summary ?? item.message}</p>
                <p>Shown as a review artifact, not a fabricated normalized profile.</p>
              </div>
            </article>
          ))}
        </div>
      )}
      {selected ? <ProfilePanel profile={selected} onClose={() => setSelected(null)} /> : null}
    </section>
  );
}

function ProfilePanel({ profile, onClose }: { profile: ProfileDetail; onClose: () => void }) {
  const rootRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useDialogA11y(true, onClose, rootRef, closeRef);

  if (profile.kind === "review_artifact" || profile.normalized_profile === false) {
    return (
      <>
        <button type="button" className="backdrop" aria-label="Close profile" onClick={onClose} />
        <aside ref={rootRef} className="drawer" role="dialog" aria-modal="true" aria-labelledby="profile-title">
          <div className="drawer-head">
            <h2 id="profile-title">{profile.title ?? profile.display_title}</h2>
            <button ref={closeRef} type="button" className="ghost" onClick={onClose}>
              Close
            </button>
          </div>
          <div className="drawer-body scroll-hidden">
            <p>{profile.message ?? profile.summary}</p>
          </div>
        </aside>
      </>
    );
  }
  return (
    <>
      <button type="button" className="backdrop" aria-label="Close profile" onClick={onClose} />
      <aside
        ref={rootRef}
        className="drawer profile-doc"
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-title"
      >
        <div className="drawer-head">
          <h2 id="profile-title">{profile.display_title}</h2>
          <button ref={closeRef} type="button" className="ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="drawer-body scroll-hidden">
          <p>
            {profile.family_name} · {profile.track_name} · {profile.level_label}
          </p>
          <span className={`chip ${profile.is_provisional ? "warn" : "good"}`}>
            {profile.is_provisional ? "provisional" : profile.classification}
          </span>
          <h3>Role purpose</h3>
          <p>{profile.role_purpose}</p>
          <h3>Responsibilities</h3>
          <ul>
            {profile.responsibilities.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <h3>Scope / decision making</h3>
          <p>{profile.scope_decision_making}</p>
          <h3>Core competencies</h3>
          <p>{profile.core_competencies}</p>
          <h3>Level expectations</h3>
          <pre className="mono">{profile.level_expectations}</pre>
          <h3>Progression</h3>
          <p>{profile.progression}</p>
          <div className="evidence-meta">
            <h3>Evidence metadata</h3>
            <p className="meta-line">{profile.source_evidence_note}</p>
          </div>
        </div>
      </aside>
    </>
  );
}
