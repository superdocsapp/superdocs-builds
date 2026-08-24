const baseViewRun=viewRun;
const baseResults=results;

let summaryRenderPromise=null;

async function renderRecoverySummary(){
  if(summaryRenderPromise)return summaryRenderPromise;
  summaryRenderPromise=renderRecoverySummaryOnce();
  try{return await summaryRenderPromise}finally{summaryRenderPromise=null}
}

async function renderRecoverySummaryOnce(){
  const m=await api('/api/metrics'),g=m.guided_recovery,a=m.applied_verification;
  document.querySelector('#secondary-results')?.remove();
  document.querySelector('#experimental-run-label')?.remove();
  if(!document.querySelector('.primary-metrics'))return;
  const t=m.targeting,search=m.targeting_by_case_type.search,edit=m.targeting_by_case_type.edit;
  const primary=document.querySelector('.primary-metrics');
  primary.className='headline-metrics';
  primary.innerHTML=`<article class="headline-card"><span>Section targeting</span><strong>${(t.accuracy*100).toFixed(1)}%</strong><b>${t.pass} / ${t.total}</b></article><article class="headline-card outcome"><span>Correct final outcome</span><strong>${(m.strict.accuracy*100).toFixed(1)}%</strong><b>${m.strict.pass} / ${m.strict.total}</b></article>`;
  document.querySelector('#strict-summary')?.remove();
  document.querySelector('.metric-explanation')?.remove();
  primary.insertAdjacentHTML('afterend',`<p class="target-breakdown">Search targeting ${(search.accuracy*100).toFixed(1)}% <span>·</span> Edit targeting ${(edit.accuracy*100).toFixed(1)}%</p><p class="metric-explanation">Targeting measures whether SuperDocs found the intended section; final outcome also requires the answer/edit to be correct.</p>`);
  document.querySelector('.page-title h2').textContent='Results';
  document.querySelector('.page-title>div>p')?.remove();
  if(!m.official_run_complete){
    document.querySelector('.page-title h2')?.insertAdjacentHTML('afterend','<p id="experimental-run-label" class="experimental-label">Experimental validation run — not the frozen official benchmark.</p>');
  }
  document.querySelector('.breakdowns')?.remove();
  const runCard=[...document.querySelectorAll('.card.compact')].find(x=>x.querySelector('h3')?.textContent==='Run measurements');
  runCard.innerHTML=`<h3>Run metrics</h3><div class="compact-metrics">${stat('P95 latency',ms(m.p95_latency_ms))}${stat('API-reported operations',m.total_operations_charged)}${stat('Dollar spend','Not reported by API')}</div>`;
  const failureCard=[...document.querySelectorAll('.card.compact')].find(x=>x.querySelector('h3')?.textContent==='Observed failure reasons');
  const failureRows=[...m.by_failure_category,{name:'Cannot determine',count:t.cannot_determine}];
  const maximum=Math.max(1,...failureRows.map(x=>x.count));
  failureCard.classList.add('failure-summary');
  failureCard.innerHTML=`<h3>Observed failures</h3><div class="failure-rows">${failureRows.map(x=>`<div class="failure-row"><span>${esc(x.name)}</span><div><i style="width:${Math.round(x.count/maximum*100)}%"></i></div><strong>${x.count}</strong></div>`).join('')}</div>`;
  failureCard.parentNode.insertBefore(failureCard,runCard);
  const block=`<section id="secondary-results"><h2>Additional experiments</h2><p class="secondary-label">Secondary experiments — separate from official benchmark scores.</p><div class="experiment-grid"><article class="card compact"><h3>Applied edit verification</h3><div class="experiment-values"><p><span>Verified</span><b>${a.verified}</b></p><p><span>Landed correctly</span><b>${a.landed_in_intended_section}</b></p><p><span>Unrelated changes</span><b>${a.unrelated_changes_detected}</b></p></div></article><article class="card compact"><h3>Guided recovery</h3><div class="experiment-values"><p><span>Attempted</span><b>${g.cases_attempted}</b></p><p><span>Recovered</span><b>${g.cases_recovered}</b></p><p><span>Did not recover</span><b>${g.cases_not_recovered}</b></p></div></article></div></section>`;
  runCard.insertAdjacentHTML('afterend',block);
}

results=async function(){
  await baseResults();
  await renderRecoverySummary();
};

// app.js queues its first Results render before this extension is loaded.
// Watch the app container so a full refresh renders secondary results as soon
// as the main Results metrics exist.
const resultsObserver=new MutationObserver(()=>{
  if(document.querySelector('.primary-metrics')&&!document.querySelector('#secondary-results'))renderRecoverySummary();
});
resultsObserver.observe(document.querySelector('#app'),{childList:true,subtree:true});

function guidedRecoveryMarkup(g){
  const label=g.recovery_verdict==='recovered'?'Recovered':g.recovery_verdict==='not_recovered'?'Did not recover':g.recovery_verdict==='ambiguous'?'Cannot determine':'Awaiting evaluation';
  return `<section class="card recovery" id="guided-recovery"><h3>Guided recovery</h3><p class="help">This separate, one-retry experiment never changes the original benchmark result.</p><div class="evidence-meta"><p><strong>Original target:</strong> ${esc(g.original_target_path||'Section path unavailable')}</p><p><strong>Human guidance:</strong> ${esc(g.guidance_text)}</p><p><strong>Recovery target:</strong> ${esc(g.recovery_target_path||'Section path unavailable')}</p><p><strong>Recovery status:</strong> ${esc(words(g.recovery_status))}</p><p><strong>Recovery result:</strong> ${esc(label)}</p><p><strong>Additional API operations:</strong> ${g.recovery_operations||0}</p></div>${(g.recovery_pending_changes||[]).map(changeCard).join('')}${g.error?`<p class="error">${esc(g.error)}</p>`:''}${g.recovery_status==='awaiting_approval'&&!g.recovery_verdict?`<form id="recovery-verdict"><div class="judge-row"><button type="button" data-recovery-verdict="recovered">RECOVERED</button><button type="button" data-recovery-verdict="not_recovered">DID NOT RECOVER</button><button type="button" data-recovery-verdict="ambiguous">CANNOT DETERMINE</button></div><label>Optional recovery note<textarea id="recovery-note"></textarea></label><button id="save-recovery-verdict" class="primary" disabled>Save recovery result</button></form>`:''}<details><summary>Recovery technical details</summary><pre>${esc(JSON.stringify(g.recovery_raw_response,null,2))}</pre></details></section>`;
}

viewRun=async function(id){
  await baseViewRun(id);
  const r=await api(`/api/runs/${id}`),g=r.guided_recovery;
  const proposal=document.querySelector('.evidence-pane .card:nth-of-type(3)');
  if(r.session_id&&r.applied_verification?.approval_status==='completed'){
    const appliedCard=[...document.querySelectorAll('.evidence-pane .card')].find(x=>x.querySelector('h3')?.textContent==='Applied verification');
    appliedCard?.insertAdjacentHTML('beforeend',`<a class="button" href="/api/runs/${id}/export?format=docx">Export DOCX</a>`);
  }
  if(g){
    document.querySelector('#approve-test-edit')?.remove();
    proposal?.insertAdjacentHTML('afterend',guidedRecoveryMarkup(g));
    if(g.recovery_pending_changes?.length){
      document.querySelector('#document-viewer').src=`/api/runs/${id}/viewer?stage=recovery&t=${Date.now()}`;
      document.querySelector('.viewer-heading')?.insertAdjacentHTML('beforeend','<span class="recovery-view-label">Showing recovery proposal</span>');
    }
    let verdict=null;
    document.querySelectorAll('[data-recovery-verdict]').forEach(b=>b.onclick=()=>{verdict=b.dataset.recoveryVerdict;document.querySelectorAll('[data-recovery-verdict]').forEach(x=>x.classList.toggle('selected',x===b));document.querySelector('#save-recovery-verdict').disabled=false});
    document.querySelector('#recovery-verdict')?.addEventListener('submit',async e=>{e.preventDefault();await api(`/api/runs/${id}/guided-recovery/adjudication`,{method:'PUT',body:JSON.stringify({verdict,note:document.querySelector('#recovery-note').value})});msg('Recovery result saved separately.');viewRun(id)});
    return;
  }
  const canReject=!r.benchmark_run_read_only&&r.case.case_type==='edit'&&r.status==='awaiting_approval'&&changes(r.evidence||{}).length&&!r.applied_verification&&((r.raw_response?.job?.metadata||{}).awaiting_kind!=='continue_prompt');
  if(!canReject||!proposal)return;
  document.querySelector('#approve-test-edit')?.insertAdjacentHTML('afterend',' <button id="reject-and-guide">Reject and guide</button>');
  document.querySelector('#reject-and-guide').onclick=()=>{
    if(!confirm('This preserves the original failed proposal and starts a separate guided-recovery attempt.'))return;
    document.querySelector('#recovery-guidance-form')?.remove();
    proposal.insertAdjacentHTML('beforeend',`<form id="recovery-guidance-form"><label>Tell SuperDocs how to correct the target<textarea id="recovery-guidance" required placeholder="Do not edit the incorrect section. Apply this change only in the intended section."></textarea></label><button class="primary">Reject proposal and send guidance</button></form>`);
    document.querySelector('#recovery-guidance-form').onsubmit=async e=>{e.preventDefault();const guidance=document.querySelector('#recovery-guidance').value.trim();if(!guidance)return msg('Enter guidance before submitting.',true);const button=e.submitter;button.disabled=true;button.textContent='Rejecting and requesting one new proposal…';try{await api(`/api/runs/${id}/guided-recovery`,{method:'POST',body:JSON.stringify({guidance})});msg('Guided recovery proposal saved separately.');viewRun(id)}catch(error){msg(error.message,true);viewRun(id)}};
  };
};
