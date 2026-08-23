import { useMemo, useState } from "react";
import { exampleInput, filterStrings, kitTemplates, makeKitHtml, type KitInput } from "./lib/kit";
import { exportKit, startReview, submitDecisions, type ReviewJob } from "./lib/superdocs";
import { validateTranslations } from "./lib/validation";
import "./styles.css";

const sessionId = () => `localization-${crypto.randomUUID()}`;

export default function App() {
  const [kit, setKit] = useState<KitInput>(exampleInput);
  const [targetText, setTargetText] = useState<Record<string, string>>({});
  const [review, setReview] = useState<ReviewJob | null>(null);
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [approvedHtml, setApprovedHtml] = useState<string | null>(null);
  const [status, setStatus] = useState("Ready. The SuperDocs key stays on the local server.");
  const [activeSession, setActiveSession] = useState("");
  const [search, setSearch] = useState("");
  const violations = useMemo(() => validateTranslations(kit.strings, targetText, kit.targetLanguage, kit.doNotTranslate), [kit, targetText, kit.targetLanguage]);
  const visibleStrings = useMemo(() => filterStrings(kit.strings, search), [kit.strings, search]);
  const errorsFor = (id: string) => violations.filter(item => item.id === id);

  function applyTemplate(templateId: string) {
    const template = kitTemplates.find(item => item.id === templateId);
    if (!template) return;
    setKit(template.input);
    setTargetText({});
    setReview(null);
    setDecisions({});
    setApprovedHtml(null);
    setActiveSession("");
    setSearch("");
    setStatus(`${template.label} loaded. Add returned translations, then request review.`);
  }

  async function sendToSuperDocs() {
    const nextSession = sessionId();
    try {
      setStatus("Sending the generated kit to SuperDocs...");
      setActiveSession(nextSession);
      setApprovedHtml(null);
      setStatus("Asking SuperDocs for a translator-readiness review. This can take a minute.");
      const result = await startReview(nextSession, makeKitHtml(kit, targetText));
      setReview(result);
      setDecisions(Object.fromEntries(result.changes.map(change => [change.change_id, true])));
      setApprovedHtml(result.updatedHtml);
      setStatus(result.changes.length ? `${result.changes.length} proposed change(s) ready for your review.` : "Review completed with no proposed changes.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The SuperDocs request failed.");
    }
  }

  async function applyReview() {
    if (!review) return;
    try {
      const updated = await submitDecisions(review, decisions);
      setApprovedHtml(updated);
      setStatus(updated ? "Your per-change decisions were applied. The approved document is shown below and ready to export." : "Your decisions were sent. SuperDocs completed the review, but did not return updated HTML in the polling payload. Export remains available.");
    } catch (error) { setStatus(error instanceof Error ? error.message : "Could not submit review decisions."); }
  }

  async function download() {
    if (!activeSession) return;
    try { await exportKit(activeSession); setStatus("DOCX export started."); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Export failed."); }
  }

  return <main>
    <header className="app-header">
      <div><p className="eyebrow">Game localization handoff</p><h1>Kitline</h1><p className="lede">Prepare the file a translator receives, check the returned strings, then create an approval record before export. Kitline is a preflight workspace, not a translation engine.</p></div>
      <aside className="quick-guide"><p className="eyebrow">First time here?</p><ol><li>Choose a starting kit and target locale.</li><li>Add the context and translations you received.</li><li>Review the warnings, then ask SuperDocs to check the handoff.</li></ol></aside>
    </header>
    <nav className="workflow" aria-label="Kitline workflow"><a href="#setup"><span>01</span> Set up</a><a href="#brief"><span>02</span> Brief translator</a><a href="#strings"><span>03</span> Check strings</a><a href="#protect"><span>04</span> Protect terms</a><a href="#review"><span>05</span> Review and export</a></nav>

    <section id="setup" className="setup">
      <div className="section-copy"><p className="eyebrow">Step 1</p><h2>Start a handoff</h2><p>Use a sample kit as a working starting point. Changing templates clears the target-text fields so content from two jobs cannot get mixed together.</p></div>
      <div className="setup-fields"><label>Kit template <select aria-label="Kit template" defaultValue="ashfall" onChange={event => applyTemplate(event.target.value)}>{kitTemplates.map(template => <option value={template.id} key={template.id}>{template.label}</option>)}</select></label><label>Target language <input value={kit.targetLanguage} onChange={event => setKit({ ...kit, targetLanguage: event.target.value })} /></label></div>
      <div className="actions"><button onClick={sendToSuperDocs}>Send handoff for review</button><button className="quiet" disabled={!activeSession} onClick={download}>Export approved DOCX</button></div>
      <p className="status" aria-live="polite">{status}</p>
    </section>

    <section id="brief" className="context"><div><p className="eyebrow">Step 2: world and intent</p><h2>Brief the translator</h2><p className="field-help">Explain the game situation and why the player sees these strings. This removes guesswork that a bare spreadsheet creates.</p><label>Project context <textarea value={kit.world} onChange={event => setKit({ ...kit, world: event.target.value })} /></label></div><div><p className="eyebrow">Step 2: voice</p><h2>{kit.game}</h2><p className="field-help">Give the translator practical voice direction, including what needs to stay short on screen.</p><label>Voice direction <textarea value={kit.tone} onChange={event => setKit({ ...kit, tone: event.target.value })} /></label></div></section>
    <section id="strings"><div className="section-head"><div><p className="eyebrow">Step 3</p><h2>Paste and check returned translations</h2><p className="field-help">Paste the vendor's result in the matching row. Warnings are local checks only. They flag work for a producer or linguist to inspect.</p></div><strong className={violations.length ? "bad" : "good"}>{violations.length ? `${violations.length} issue(s)` : "Ready for review"}</strong></div>
      <div className="string-search"><label>Find a string<input aria-label="Find strings" value={search} onChange={event => setSearch(event.target.value)} placeholder="ID, source, speaker or scene" /></label><small>{visibleStrings.length} of {kit.strings.length} string(s) shown</small></div>
      <div className="table-wrap"><table><thead><tr><th>ID / source</th><th>Limit</th><th>Speaker and scene</th><th>Returned translation</th></tr></thead><tbody>{visibleStrings.map(item => <tr key={item.id}><td><code>{item.id}</code><p>{item.source}</p></td><td>{item.characterLimit} display units</td><td><strong>{item.speaker}</strong><br /><small>{item.scene}</small></td><td><textarea aria-label={`${item.id} translation`} value={targetText[item.id] ?? ""} onChange={event => setTargetText({ ...targetText, [item.id]: event.target.value })} placeholder={`Paste ${kit.targetLanguage} translation`} />{errorsFor(item.id).map(error => <small className="violation" key={error.message}>{error.message}</small>)}</td></tr>)}</tbody></table></div>
    </section>

    <section id="protect" className="side-by-side"><div><p className="eyebrow">Step 4: preserve exactly</p><h2>Do not translate</h2><p className="field-help">One term per line. Include product names, variables, UI tags and any term the game must keep unchanged.</p><textarea aria-label="Do not translate list" value={kit.doNotTranslate.join("\n")} onChange={event => setKit({ ...kit, doNotTranslate: event.target.value.split("\n").filter(Boolean) })} /></div><div><p className="eyebrow">Step 4: keep consistent</p><h2>Style sheet</h2><p className="field-help">One instruction per line. Keep it short enough that a vendor can apply it while working in the string table.</p><textarea aria-label="Style sheet" value={kit.styleRules.join("\n")} onChange={event => setKit({ ...kit, styleRules: event.target.value.split("\n").filter(Boolean) })} /></div></section>

    {review && <section id="review" className="review"><p className="eyebrow">Step 5: human approval</p><h2>Inspect every proposed edit</h2><p className="field-help">SuperDocs may suggest clearer context or style instructions. It is not allowed to rewrite your source strings, IDs, limits or protected content. Select only the changes you want to apply.</p>{review.changes.length === 0 ? <p className="empty-state">No edits were proposed. You can export this reviewed handoff.</p> : review.changes.map(change => <article key={change.change_id}><p>{change.ai_explanation}</p><div className="diff"><del dangerouslySetInnerHTML={{ __html: change.old_html ?? "" }} /><ins dangerouslySetInnerHTML={{ __html: change.new_html ?? "" }} /></div><label><input type="checkbox" checked={decisions[change.change_id] ?? false} onChange={event => setDecisions({ ...decisions, [change.change_id]: event.target.checked })} /> Apply this edit</label></article>)}<button disabled={!review.changes.length} onClick={applyReview}>Apply selected edits</button></section>}
    {approvedHtml && <section className="approved-document"><p className="eyebrow">Reviewed output</p><h2>Approved handoff document</h2><p className="field-help">This is the document that will be exported as DOCX. Check it once, then use “Export approved DOCX” at the top.</p><iframe title="Approved localization kit" sandbox="" srcDoc={approvedHtml} /></section>}
  </main>;
}
