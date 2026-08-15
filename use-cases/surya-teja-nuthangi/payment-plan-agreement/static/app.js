const $=selector=>document.querySelector(selector);
let previewData=null,currentRun=null,timer=null,operationStarted=0;
const money=(value,currency)=>new Intl.NumberFormat('en-US',{style:'currency',currency}).format(Number(value));
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const prettyDate=value=>new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}).format(new Date(`${value}T00:00:00Z`));

function requestBody(){
  const form=new FormData($('#terms-form')),kind=form.get('late_fee_kind');
  const fee={kind,grace_days:Number(form.get('grace_days')||0)},value=form.get('late_fee_value');
  if(kind==='fixed')fee.amount=value;
  if(kind==='percent')fee.percent=value;
  return {creditor:{legal_name:form.get('creditor')},debtor:{legal_name:form.get('debtor')},terms:{currency:form.get('currency'),original_balance:form.get('original_balance'),upfront_payment:form.get('upfront_payment'),installment_count:Number(form.get('installment_count')),frequency:form.get('frequency'),first_due_date:form.get('first_due_date'),agreement_date:form.get('agreement_date'),late_fee:fee,reference_id:form.get('reference_id')||null,additional_terms:form.get('additional_terms')||null}};
}
function validate(body){
  if(!body.creditor.legal_name.trim())throw new Error('Creditor name is required.');
  if(!body.debtor.legal_name.trim())throw new Error('Debtor name is required.');
  if(Number(body.terms.original_balance)<=0)throw new Error('Original balance must be greater than zero.');
  if(Number(body.terms.upfront_payment)<0)throw new Error('Upfront payment cannot be negative.');
  if(Number(body.terms.upfront_payment)>=Number(body.terms.original_balance))throw new Error('Upfront payment must be lower than the original balance.');
  if(!Number.isInteger(body.terms.installment_count)||body.terms.installment_count<1)throw new Error('Installment count must be at least one.');
  if(!body.terms.first_due_date)throw new Error('A valid first due date is required.');
  if(!body.terms.agreement_date)throw new Error('A valid agreement date is required.');
  if(body.terms.late_fee.kind!=='none'&&!body.terms.late_fee.amount&&!body.terms.late_fee.percent)throw new Error('Enter a value for the selected late fee.');
}
async function api(path,options={}){const response=await fetch(path,{headers:{'Content-Type':'application/json'},...options});const data=(response.headers.get('content-type')||'').includes('json')?await response.json():await response.blob();if(!response.ok)throw new Error(data.error||`Request failed with status ${response.status}.`);return data;}
function fail(error){$('#error').textContent=error.message;$('#error').hidden=false;stopTimer();}
function setState(label,waiting=false){$('#job-state').textContent=label;$('#processing-note').hidden=!waiting;}
function startTimer(message){operationStarted=Date.now();$('#review-panel').hidden=false;$('#processing-title').textContent=message;$('#processing-note').hidden=false;clearInterval(timer);const tick=()=>{$('#elapsed').textContent=`Elapsed: ${Math.floor((Date.now()-operationStarted)/1000)}s`};tick();timer=setInterval(tick,1000);}
function stopTimer(){clearInterval(timer);timer=null;$('#processing-note').hidden=true;}

async function preview(){
  try{
    $('#error').hidden=true;const body=requestBody();validate(body);$('#preview').disabled=true;$('#preview').textContent='CALCULATING…';$('#schedule-state').textContent='CALCULATING';
    previewData=await api('/api/preview',{method:'POST',body:JSON.stringify(body)});
    const plan=previewData.plan,currency=plan.terms.currency,difference=Number(plan.total_scheduled)-Number(plan.financed_balance);
    $('#empty').hidden=true;$('#schedule').hidden=false;$('#financed').textContent=money(plan.financed_balance,currency);$('#count').textContent=`${plan.installments.length} × ${plan.terms.frequency}`;$('#total').textContent=money(plan.total_scheduled,currency);$('#difference').textContent=money(difference,currency);
    $('#schedule-body').innerHTML=plan.installments.map(item=>`<tr><td>${item.number}</td><td>${prettyDate(item.due_date)}</td><td>${money(item.amount,currency)}</td><td>${money(item.balance_after,currency)}</td></tr>`).join('');
    $('#canonical-summary').textContent=`${plan.installments.length} ${plan.terms.frequency} installments · ${money(plan.financed_balance,currency)} financed · ${prettyDate(plan.installments[0].due_date)} to ${prettyDate(plan.final_due_date)}`;
    $('#canonical-fingerprint').textContent=`Fingerprint: ${plan.semantic_fingerprint.slice(0,12)}…${plan.semantic_fingerprint.slice(-8)}`;
    $('#schedule-state').textContent='AGREEMENT SEED VERIFIED';$('#schedule-state').className='status pass';
  }catch(error){fail(error);$('#schedule-state').textContent='VALIDATION REQUIRED';$('#schedule-state').className='status neutral'}finally{$('#preview').disabled=false;$('#preview').textContent='Recalculate schedule'}
}
function verifierMarkup(data){const final=data.state==='final_verified'||data.state==='exported',passed=data.verification?.status==='pass',checkLabel=final&&passed?'PASS':'PRECHECK PASS',noneLabel=final&&passed?'NONE':'PRECHECK NONE';const labels=['Schedule rows','Installment amounts','Due dates','Schedule total','Prose / table agreement','Protected facts'];return labels.map(label=>`<div class="check">✓ ${label}<b>${checkLabel}</b></div>`).join('')+`<div class="check">✓ Unsupported money / dates<b>${noneLabel}</b></div><div class="check">Findings<b>${data.verification?.findings?.length??0}</b></div>${final?'<div class="check">Final document<b>VERIFIED</b></div>':''}`;}
function showRun(data){
  stopTimer();currentRun=data;$('#review-panel').hidden=false;$('#review-panel').scrollIntoView({behavior:'smooth'});
  const proposals=data.job?.proposals||[],blocked=proposals.filter(item=>item.blocked).length,approved=data.decisions.filter(item=>item.approved).length,rejected=data.decisions.filter(item=>!item.approved).length;
  const state={awaiting_human:'AWAITING_REVIEW',superdocs_processing:'SUPERDOCS_PROCESSING',applying_approvals:'APPLYING_DECISIONS',final_verified:'READY_TO_EXPORT',exported:'EXPORTED',blocked:'BLOCKED'}[data.state]||data.state.replaceAll('_',' ').toUpperCase();setState(state,false);
  $('#batch-summary').textContent=`Batch ${data.batch_number||1} · ${proposals.length} current proposals · ${approved} approved · ${rejected} rejected · ${blocked} blocked`;
  $('#fingerprint').textContent=`Canonical fingerprint: ${data.plan.semantic_fingerprint}`;$('#document-hash').textContent=data.verification?.document_hash?`Document hash: ${data.verification.document_hash}`:'';$('#verification-checks').innerHTML=verifierMarkup(data);
  $('#proposals').innerHTML=proposals.length?proposals.map((proposal,index)=>`<article class="proposal ${proposal.blocked?'blocked':''}"><div class="proposal-head"><strong>Batch ${data.batch_number||1} · Change ${index+1} · ${esc(proposal.operation)}</strong><code>${esc(proposal.chunk_id||'document')}</code></div><span class="proposal-state">${proposal.blocked?'BLOCKED':'SAFE'}</span><p>${esc(proposal.ai_explanation||'Clarity edit proposed by SuperDocs.')}</p><div class="diff"><div><small>BEFORE</small><br>${esc(proposal.old_html||'—')}</div><div><small>AFTER</small><br>${esc(proposal.new_html||'—')}</div></div>${proposal.blocked?'<p><b>Protected fact mismatch. This proposal cannot be approved. Source: canonical PaymentPlan.</b></p>':''}<div class="decision"><label><input type="radio" name="decision-${index}" value="true" ${proposal.blocked?'disabled':'checked'}> Approve change ${index+1}</label><label><input type="radio" name="decision-${index}" value="false" ${proposal.blocked?'checked':''}> Reject change ${index+1}</label></div></article>`).join(''):'<p>No wording changes were needed. The independently verified agreement is ready.</p>';
  const awaiting=data.state==='awaiting_human';$('#apply').hidden=!awaiting;$('#apply').disabled=false;$('#export').hidden=!['final_verified','exported'].includes(data.state);
  const final=Boolean(data.final_html)&&data.verification?.status==='pass';$('#final-panel').hidden=!final;if(final)$('#final-document').srcdoc=data.final_html;
  if(data.state==='blocked'){$('#error').hidden=false;$('#error').textContent='Final verification blocked export. The run and findings are preserved; review the verifier details before retrying.'}
}
async function generate(){try{if(!previewData)await preview();if(!previewData)return;const body=requestBody();validate(body);body.mode=$('#live-mode').checked?'live':'fake';$('#error').hidden=true;$('#generate').disabled=true;$('#generate').textContent='SUBMITTING…';setState('SUBMITTING_TO_SUPERDOCS',true);startTimer(body.mode==='live'?'SuperDocs is processing the agreement.':'Offline adapter is preparing proposals.');showRun(await api('/api/runs',{method:'POST',body:JSON.stringify(body)}));}catch(error){fail(error)}finally{$('#generate').disabled=false;$('#generate').textContent='Generate agreement'}}
async function applyReview(){try{const proposals=currentRun.job?.proposals||[],decisions=proposals.map((item,index)=>({change_id:item.change_id,approved:document.querySelector(`input[name="decision-${index}"]:checked`)?.value==='true'}));$('#apply').disabled=true;setState('APPLYING_DECISIONS',true);startTimer('SuperDocs is processing the approved changes.');showRun(await api(`/api/runs/${currentRun.run_id}/review`,{method:'POST',body:JSON.stringify({decisions})}));}catch(error){fail(error);$('#apply').disabled=false}}
async function exportDoc(){try{$('#export').disabled=true;setState('EXPORTING_DOCX',true);const response=await fetch(`/api/runs/${currentRun.run_id}/export`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!response.ok)throw new Error((await response.json()).error);const blob=await response.blob(),disposition=response.headers.get('Content-Disposition')||'',filename=disposition.match(/filename="?([^";]+)"?/i)?.[1]||`payment-plan-${currentRun.run_id}.docx`,link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=filename;link.click();URL.revokeObjectURL(link.href);stopTimer();$('#job-state').textContent='EXPORTED';$('#export-result').textContent=`Exported successfully · ${filename} · ${blob.size.toLocaleString()} bytes`;}catch(error){fail(new Error(`${error.message} The verified final document remains available; retry export only.`))}finally{$('#export').disabled=false}}

$('#preview').onclick=preview;$('#generate').onclick=generate;$('#apply').onclick=applyReview;$('#export').onclick=exportDoc;
$('#live-mode').onchange=event=>{const badge=$('#mode-badge');badge.textContent=event.target.checked?'LIVE SUPERDOCS':'OFFLINE TEST MODE';badge.className=`badge ${event.target.checked?'live':'fake'}`};
api('/api/config').then(config=>{if(!config.live_available){$('#live-mode').disabled=true;$('#live-mode').parentElement.title='Set SUPERDOCS_API_KEY on the server to enable live mode'}}).catch(fail);
preview();
