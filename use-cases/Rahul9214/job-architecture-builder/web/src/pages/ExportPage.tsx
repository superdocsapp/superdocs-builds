import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { ArtifactCard } from "../components/ArtifactCard";
import { Combobox } from "../components/Combobox";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorBanner, Loading } from "../components/Status";
import { useCorpus } from "../corpus";
import type { ProfileSummary, SuperDocsStatus } from "../types";

export function ExportPage() {
  const { corpusId, analyzed } = useCorpus();
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileId, setProfileId] = useState("");
  const [status, setStatus] = useState<SuperDocsStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [downloadHref, setDownloadHref] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError(null);
      setMessage(null);
      setDownloadHref(null);
      try {
        const superdocs = await api.superdocs();
        if (!cancelled) setStatus(superdocs);
        if (analyzed && corpusId) {
          const payload = await api.profiles(corpusId);
          if (!cancelled) {
            setProfiles(payload.profiles);
            setProfileId(payload.profiles[0]?.profile_id ?? "");
          }
        } else if (!cancelled) {
          setProfiles([]);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Unable to load export status.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [analyzed, corpusId]);

  async function exportKind(kind: "framework" | "profile") {
    setError(null);
    setMessage(null);
    setDownloadHref(null);
    try {
      const result = await api.exportLocal(corpusId, kind, kind === "profile" ? profileId : undefined);
      if (!result.ok) {
        setError("Export did not produce an artifact.");
        return;
      }
      setMessage(`Local ${kind} artifact written: ${result.filename}. SuperDocs was not called.`);
      setDownloadHref(`/api/export/${corpusId}/download/${encodeURIComponent(result.filename)}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Export failed.");
    }
  }

  if (error && !status) return <ErrorBanner message={error} />;
  if (!status) return <Loading label="Loading export status" />;

  return (
    <section>
      <PageHeader title="Export">
        Local DOCX files are written by this web app. Live SuperDocs export is a verified CLI workflow, not a
        browser action.
      </PageHeader>
      {error ? <ErrorBanner message={error} /> : null}
      {!analyzed ? <Empty>Analyze the corpus before exporting framework or profiles.</Empty> : null}
      <h2 className="export-local">Local artifacts</h2>
      <p className="helper">Web app local DOCX. These downloads do not call SuperDocs.</p>
      <div className="grid-2">
        <ArtifactCard
          title="Framework"
          status={
            <span className={`chip ${analyzed ? "good" : "warn"}`}>
              {analyzed ? "available" : "analyze first"}
            </span>
          }
        >
          <p>Canonical levels, tracks, families, and competency matrices.</p>
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={!analyzed}
              onClick={() => void exportKind("framework")}
            >
              Export framework
            </button>
          </div>
        </ArtifactCard>
        <ArtifactCard
          title="Selected role profile"
          status={
            <span className={`chip ${analyzed && profileId ? "good" : "warn"}`}>
              {analyzed && profileId ? "available" : "unavailable"}
            </span>
          }
        >
          {profiles.length === 0 ? (
            <Empty>No profile available to export.</Empty>
          ) : (
            <>
              <Combobox
                id="export-profile"
                label="Profile"
                value={profileId}
                options={profiles.map((item) => ({
                  id: item.profile_id,
                  label: item.display_title,
                  secondary: item.level_label,
                }))}
                onChange={setProfileId}
              />
              <div className="actions">
                <button
                  type="button"
                  className="primary"
                  disabled={!analyzed || !profileId}
                  onClick={() => void exportKind("profile")}
                >
                  Export selected profile
                </button>
              </div>
            </>
          )}
        </ArtifactCard>
      </div>
      {message ? <p>{message}</p> : null}
      {downloadHref ? (
        <p>
          <a href={downloadHref}>Download generated DOCX</a>
        </p>
      ) : null}
      <h2 className="export-live">Live SuperDocs</h2>
      <ArtifactCard
        title="SuperDocs live export"
        status={
          <span className={`chip ${status.configured ? "good" : "warn"}`}>
            {status.configured ? "configured" : "not configured"}
          </span>
        }
      >
        <p>Live API workflow is available through the verified CLI path. This screen does not start a live export.</p>
        <p className="helper">{status.live_export_reason}</p>
        <div className="actions">
          <button type="button" className="ghost" disabled>
            Live SuperDocs export unavailable
          </button>
        </div>
      </ArtifactCard>
    </section>
  );
}
