"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Campaign } from "@/lib/api";
import { IconArrowRight } from "./icons";
import ProcessFlow from "./ProcessFlow";

// The animated castle/petals/stars scene used to live here, inline, which
// is why it only ever rendered on "/" -- it now lives in BackgroundScene.tsx
// and is rendered once from layout.tsx so every route gets it (see .shell's
// position:relative in globals.css for how it stacks above the scene).
//
// The old static 5-card "how it works" grid that used to live here (a
// FLOW_STEPS array + .feature-strip markup) was replaced with the animated,
// centered <ProcessFlow /> diagram below -- same five steps, but it now
// also labels which steps are an actual SuperDocs API call versus logic
// this app computes itself. See ProcessFlow.tsx.

export default function CampaignsHomePage() {
  const router = useRouter();
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [genre, setGenre] = useState("");
  const [setting, setSetting] = useState("");
  const [description, setDescription] = useState("");
  const [coverImage, setCoverImage] = useState<File | null>(null);

  const load = useCallback(() => {
    api
      .listCampaigns()
      .then(setCampaigns)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const campaign = await api.createCampaign({ name: name.trim(), genre: genre.trim(), setting: setting.trim(), description: description.trim() });
      if (coverImage) {
        try {
          await api.uploadCampaignCoverImage(campaign.id, coverImage);
        } catch {
          // non-fatal -- the campaign itself was created fine, cover image can be added later
        }
      }
      router.push(`/campaigns/${campaign.id}`);
    } catch (e) {
      setError(String(e));
      setCreating(false);
    }
  }

  return (
    <>
        <section className="hero">
          <div className="hero-content">
            <div className="hero-eyebrow">TTRPG CAMPAIGN BUILDER</div>
            <h1>
              Build worlds that <span className="shimmer">stay coherent</span>
            </h1>
            <p className="hero-lede">
              Every campaign starts empty. You write or import the Bible, characters, NPCs, and locations -- and every edit
              runs through an approval step before it becomes canon.
            </p>
            {campaigns && (
              <div className="hero-stats">
                <div>
                  <div className="hero-stat-value">{campaigns.length}</div>
                  <div className="hero-stat-label">Campaigns</div>
                </div>
              </div>
            )}
          </div>
        </section>

        <ProcessFlow />

        {error && (
          <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 16 }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "28px 0 14px" }}>
          <h2 style={{ margin: 0 }}>Your campaigns</h2>
          <button className="btn primary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "New campaign"}
          </button>
        </div>

        {showForm && (
          <form className="card" onSubmit={handleCreate} style={{ marginBottom: 20, display: "grid", gap: 10 }}>
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="The Shattered Crown" required />
            </label>
            <label>
              Genre
              <input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="Dark fantasy" />
            </label>
            <label>
              Setting
              <input value={setting} onChange={(e) => setSetting(e.target.value)} placeholder="A fractured empire" />
            </label>
            <label>
              Description
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
            </label>
            <label>
              Cover image (optional)
              <input type="file" accept="image/*" onChange={(e) => setCoverImage(e.target.files?.[0] || null)} />
            </label>
            <button className="btn primary" type="submit" disabled={creating}>
              {creating ? "Creating…" : "Create empty campaign"}
            </button>
          </form>
        )}

        {campaigns === null && !error && <p>Loading campaigns…</p>}

        {campaigns && campaigns.length === 0 && (
          <div className="card">
            <p>No campaigns yet. Create one above -- it starts completely empty, ready for you to fill in.</p>
          </div>
        )}

        {campaigns && campaigns.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
            {campaigns.map((c) => (
              <a key={c.id} href={`/campaigns/${c.id}`} className="card hoverable" style={{ textDecoration: "none", color: "inherit" }}>
                {c.cover_image && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={c.cover_image} alt={c.name} style={{ width: "100%", height: 120, objectFit: "cover", borderRadius: 8, marginBottom: 8 }} />
                )}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
                  <h3 style={{ margin: "0 0 4px" }}>{c.name}</h3>
                  <IconArrowRight size={16} />
                </div>
                {c.genre && <div className="badge bible">{c.genre}</div>}
                {c.description && <p style={{ color: "var(--text-muted)", marginTop: 8 }}>{c.description}</p>}
                <div style={{ marginTop: 10, fontSize: 13, color: "var(--text-muted)" }}>
                  {c.document_count ?? 0} documents · {c.character_count ?? 0} characters
                </div>
              </a>
            ))}
          </div>
        )}
    </>
  );
}
