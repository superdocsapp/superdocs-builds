import { useMemo, useState } from "react";
import { exampleInput, makeKitHtml, type KitInput } from "./lib/kit";
import { exportKit, startReview, submitDecisions, type ReviewJob } from "./lib/superdocs";
import { validateTranslations } from "./lib/validation";
import "./styles.css";

const sessionId = () => `localization-${crypto.randomUUID()}`;

export default function App() {
  const [kit, setKit] = useState<KitInput>(exampleInput);
  const [targetText, setTargetText] = useState<Record<string, string>>({});
  const [review, setReview] = useState<ReviewJob | null>(null);
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [status, setStatus] = useState("Ready. The SuperDocs key stays on the local server.");
  const [activeSession, setActiveSession] = useState("");
  const violations = useMemo(() => validateTranslations(kit.strings, targetText, kit.targetLanguage), [kit, targetText, kit.targetLanguage]);
  const errorsFor = (id: string) => violations.filter(item => item.id === id);

  async function sendToSuperDocs() {
    const nextSession = sessionId();
    try {
      setStatus("Sending the generated kit to SuperDocs...");
      setActiveSession(nextSession);
      setStatus("Asking SuperDocs for a translator-readiness review. This can take a minute.");
      const result = await startReview(nextSession, makeKitHtml(kit));
      setReview(result);
      setDecisions(Object.fromEntries(result.changes.map(change => [change.change_id, true])));
      setStatus(result.changes.length ? `${result.changes.length} proposed change(s) ready for your review.` : "Review completed with no proposed changes.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The SuperDocs request failed.");
    }
  }

  async function applyReview() {
    if (!review) return;
    try {
      await submitDecisions(review, decisions);
      setStatus("Your per-change decisions were sent. Export is now available from SuperDocs.");
    } catch (error) { setStatus(error instanceof Error ? error.message : "Could not submit review decisions."); }
  }

  async function download() {
    if (!activeSession) return;
    try { await exportKit(activeSession); setStatus("DOCX export started."); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Export failed."); }
  }

  return <main>
    <header><p className="eyebrow">Localization production desk</p><h1>Kitline</h1><p>Build a handoff a translator can trust, then run a human-reviewed SuperDocs pass before export.</p></header>
    <section className="setup">
      <label>Target language <input value={kit.targetLanguage} onChange={event => setKit({ ...kit, targetLanguage: event.target.value })} /></label>
      <button onClick={sendToSuperDocs}>Create and review kit</button>
      <button className="quiet" disabled={!activeSession} onClick={download}>Export DOCX</button>
      <p className="status">{status}</p>
    </section>

    <section className="context"><div><p className="eyebrow">Translator context</p><h2>{kit.game}</h2><textarea value={kit.world} onChange={event => setKit({ ...kit, world: event.target.value })} /></div><div><p className="eyebrow">Voice direction</p><textarea value={kit.tone} onChange={event => setKit({ ...kit, tone: event.target.value })} /></div></section>
    <section><div className="section-head"><div><p className="eyebrow">String table</p><h2>Source and returned text</h2></div><strong className={violations.length ? "bad" : "good"}>{violations.length ? `${violations.length} issue(s)` : "All clear"}</strong></div>
      <div className="table-wrap"><table><thead><tr><th>ID / source</th><th>Limit</th><th>Speaker and scene</th><th>Returned translation</th></tr></thead><tbody>{kit.strings.map(item => <tr key={item.id}><td><code>{item.id}</code><p>{item.source}</p></td><td>{item.characterLimit} display units</td><td><strong>{item.speaker}</strong><br /><small>{item.scene}</small></td><td><textarea aria-label={`${item.id} translation`} value={targetText[item.id] ?? ""} onChange={event => setTargetText({ ...targetText, [item.id]: event.target.value })} placeholder={`Paste ${kit.targetLanguage} translation`} />{errorsFor(item.id).map(error => <small className="violation" key={error.message}>{error.message}</small>)}</td></tr>)}</tbody></table></div>
    </section>

    <section className="side-by-side"><div><p className="eyebrow">Protected content</p><h2>Do not translate</h2><textarea value={kit.doNotTranslate.join("\n")} onChange={event => setKit({ ...kit, doNotTranslate: event.target.value.split("\n").filter(Boolean) })} /></div><div><p className="eyebrow">Consistency</p><h2>Style sheet</h2><textarea value={kit.styleRules.join("\n")} onChange={event => setKit({ ...kit, styleRules: event.target.value.split("\n").filter(Boolean) })} /></div></section>

    {review && <section className="review"><p className="eyebrow">SuperDocs review</p><h2>Approve each proposed context edit</h2>{review.changes.length === 0 ? <p>No changes proposed.</p> : review.changes.map(change => <article key={change.change_id}><p>{change.ai_explanation}</p><div className="diff"><del dangerouslySetInnerHTML={{ __html: change.old_html ?? "" }} /><ins dangerouslySetInnerHTML={{ __html: change.new_html ?? "" }} /></div><label><input type="checkbox" checked={decisions[change.change_id] ?? false} onChange={event => setDecisions({ ...decisions, [change.change_id]: event.target.checked })} /> Approve this change</label></article>)}<button disabled={!review.changes.length} onClick={applyReview}>Send decisions</button></section>}
  </main>;
}
