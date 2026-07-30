const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const titles = {dashboard:['Műveleti központ','Áttekintés'],products:['Kínálat','Termékek'],orders:['Értékesítés','Rendelések'],import:['Kínálat','Importálás'],integrations:['Rendszer','Kapcsolatok'],settings:['Rendszer','Beállítások']};
let currentImportId = null;
let deviceTimer = null;

async function api(path, options={}) {
  const response = await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  const data = await response.json().catch(()=>({error:'Érvénytelen szerverválasz.'}));
  if(!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function icon(id){return `<svg><use href="#${id}"/></svg>`}
function escapeHtml(value=''){return String(value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function toast(message,type=''){const el=document.createElement('div');el.className=`toast ${type}`;el.textContent=message;$('#toasts').append(el);setTimeout(()=>el.remove(),4200)}
function formatNumber(value){return new Intl.NumberFormat('hu-HU').format(value||0)}
function formatDate(value){if(!value)return '—';return new Intl.DateTimeFormat('hu-HU',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value))}

function navigate(view){
  if(!titles[view]) view='dashboard';
  $$('.view').forEach(el=>el.classList.toggle('active',el.id===`view-${view}`));
  $$('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.view===view));
  $('#eyebrow').textContent=titles[view][0]; $('#pageTitle').textContent=titles[view][1];
  history.replaceState(null,'',`#${view}`); $('#sidebar').classList.remove('open');
  if(view==='dashboard') loadDashboard(); if(view==='products') loadProducts();
  if(view==='settings') loadSettings(); if(view==='integrations') loadConnectionState();
}

async function loadDashboard(){
  try{
    const data=await api('/api/dashboard'); const s=data.stats;
    $('#statProducts').textContent=formatNumber(s.products); $('#statReady').textContent=formatNumber(s.ready);
    $('#statDrafts').textContent=`${formatNumber(s.drafts)} piszkozat`; $('#statOrders').textContent=formatNumber(s.orders);
    $('#statStock').textContent=formatNumber(s.stock); $('#navProductCount').textContent=s.products;
    $('#environmentLabel').textContent=data.connection.environment==='production'?'Éles mód':'Sandbox mód';
    const ready=[!data.connection.problems.length,s.products>0,data.connection.user_connected];
    const items=[
      ['API-kulcsok beállítása',data.connection.problems.length?data.connection.problems[0]:'Az alkalmazásadatok ki vannak töltve.','settings'],
      ['Első termékimport',s.products?`${s.products} termékváltozat elmentve.`:'Töltsd be a forme.hu CSV-exportját.','import'],
      ['Eladói fiók csatlakoztatása',data.connection.user_connected?'A felhasználói token rendelkezésre áll.':'OAuth jóváhagyás szükséges.','integrations']
    ];
    $('#checklist').innerHTML=items.map((item,i)=>`<div class="check-item ${ready[i]?'done':''}"><div class="check-dot">${icon(ready[i]?'i-check':'i-arrow')}</div><div><strong>${escapeHtml(item[0])}</strong><span>${escapeHtml(item[1])}</span></div>${ready[i]?'':`<button class="text-button" data-go="${item[2]}">Megnyitás</button>`}</div>`).join('');
    const done=ready.filter(Boolean).length; $('#progressLabel').textContent=`${done}/3`; $('#progressBar').style.width=`${done/3*100}%`;
    $('#heroText').textContent=s.products?`${s.products} változat várja a következő műveletet.`:'Kezdésként állítsd be az API-kulcsokat, majd tölts be egy CSV-t.';
    const status=$('#globalStatus'); status.classList.toggle('connected',!data.connection.problems.length); status.querySelector('span').textContent=data.connection.problems.length?'Beállítás szükséges':(data.connection.user_connected?'Allegro csatlakoztatva':'API beállítva');
    $('#activityList').innerHTML=data.activity.length?data.activity.map(a=>`<div class="timeline-item"><div class="timeline-symbol">${icon(a.kind==='import'?'i-upload':a.kind==='connection'?'i-link':'i-settings')}</div><p>${escapeHtml(a.message)}</p><time>${formatDate(a.created_at)}</time></div>`).join(''):'<div class="timeline-empty">Az első műveletek itt jelennek majd meg.</div>';
  }catch(error){toast(error.message,'error')}
}

async function loadProducts(){
  try{
    const q=encodeURIComponent($('#productSearch').value.trim()); const data=await api(`/api/products?q=${q}`); const rows=data.products;
    $('#productResultCount').textContent=`${rows.length} találat`; $('#navProductCount').textContent=rows.length;
    $('#productEmpty').classList.toggle('hidden',rows.length>0);
    $('#productRows').innerHTML=rows.map(row=>`<tr><td><div class="product-cell">${row.image_url?`<img class="product-thumb" src="${escapeHtml(row.image_url)}" alt="" loading="lazy">`:'<div class="product-thumb"></div>'}<div><strong>${escapeHtml(row.title)}</strong><small>${escapeHtml(row.name)}</small></div></div></td><td><strong>${escapeHtml(row.sku)}</strong><small>${escapeHtml(row.parent_sku)}</small></td><td>${escapeHtml(row.color)} · ${escapeHtml(row.size)}</td><td><strong>${formatNumber(Number(row.price_huf))} Ft</strong></td><td>${formatNumber(row.stock)}</td><td><span class="badge neutral">Piszkozat</span></td></tr>`).join('');
  }catch(error){toast(error.message,'error')}
}

async function previewFile(file){
  if(!file)return; if(file.size>10_000_000){toast('A CSV legfeljebb 10 MB lehet.','error');return}
  const drop=$('#dropzone'); drop.classList.add('drag');
  try{const content=await file.text();const data=await api('/api/import/preview',{method:'POST',body:JSON.stringify({filename:file.name,content})});renderPreview(data);toast('A CSV ellenőrzése elkészült.','success')}catch(error){toast(error.message,'error')}finally{drop.classList.remove('drag')}
}
function renderPreview(data){
  currentImportId=data.import_id; const s=data.summary; $('#previewCard').classList.remove('hidden');
  $('#previewSummary').innerHTML=`<span>${s.total} sor</span><span class="ok">${s.valid} megfelelő</span><span class="bad">${s.invalid} hibás · ${s.errors} hiba</span>`;
  $('#commitCount').textContent=`${s.valid} megfelelő sor`; $('#commitImport').disabled=s.valid===0;
  $('#previewRows').innerHTML=data.rows.map(row=>`<tr><td>${row.line}</td><td><strong>${escapeHtml(row.title||row.name)}</strong><small>${escapeHtml(row.name)}</small></td><td>${escapeHtml(row.sku)}</td><td>${formatNumber(Number(row.price_huf))} Ft</td><td>${formatNumber(row.stock)}</td><td>${row.problems.length?`<div class="problem-list">${row.problems.map(escapeHtml).join('<br>')}</div>`:'<span class="badge good">Rendben</span>'}</td></tr>`).join('');
  $('#previewCard').scrollIntoView({behavior:'smooth',block:'start'});
}
async function commitImport(){
  if(!currentImportId)return; const button=$('#commitImport');button.disabled=true;
  try{const data=await api('/api/import/commit',{method:'POST',body:JSON.stringify({import_id:currentImportId})});toast(`${data.imported} termékváltozat importálva.`,'success');setTimeout(()=>navigate('products'),500)}catch(error){toast(error.message,'error');button.disabled=false}
}

async function loadSettings(){
  try{const s=await api('/api/settings');const f=$('#settingsForm');['environment','client_id','user_agent','language','invoice_driver','invoice_prefix'].forEach(k=>{if(f.elements[k])f.elements[k].value=s[k]||''});$('#secretHint').textContent=s.client_secret_set?'Van elmentett titkos kulcs.':'Még nincs elmentett titkos kulcs.';$('#agentHint').textContent=s.szamlazz_agent_key_set?'Van elmentett Agent kulcs.':'Még nincs elmentett Agent kulcs.'}catch(error){toast(error.message,'error')}
}
async function saveSettings(event){
  event.preventDefault();const f=new FormData(event.currentTarget);const body=Object.fromEntries(f.entries());
  try{await api('/api/settings',{method:'PUT',body:JSON.stringify(body)});event.currentTarget.elements.client_secret.value='';event.currentTarget.elements.szamlazz_agent_key.value='';toast('A beállításokat elmentettem.','success');await loadSettings();await loadDashboard()}catch(error){toast(error.message,'error')}
}
async function loadConnectionState(){
  try{const [d,s]=await Promise.all([api('/api/dashboard'),api('/api/settings')]);const c=d.connection;$('#connectionEnvironment').textContent=c.environment==='production'?'Éles':'Sandbox';$('#connectionApp').textContent=c.problems.length?'Beállítás szükséges':'Beállítva';$('#connectionUser').textContent=c.user_connected?'Csatlakoztatva':'Nincs csatlakoztatva';$('#allegroBadge').textContent=c.user_connected?'Csatlakoztatva':c.problems.length?'Nincs beállítva':'Beállítva';$('#allegroBadge').className=`badge ${c.user_connected?'good':c.problems.length?'bad':'neutral'}`;$('#startLogin').disabled=c.problems.length>0}catch(error){toast(error.message,'error')}
}
async function checkConnection(){const b=$('#checkConnection');b.disabled=true;b.textContent='Ellenőrzés…';try{const data=await api('/api/auth/check',{method:'POST',body:'{}'});toast(`Sikeres Allegro-kapcsolat (${data.environment}).`,'success');$('#connectionApp').textContent='Ellenőrizve';await loadDashboard()}catch(error){toast(error.message,'error')}finally{b.disabled=false;b.textContent='Alkalmazás tesztelése'}}
async function startLogin(){
  if(deviceTimer)clearInterval(deviceTimer);try{const data=await api('/api/auth/device/start',{method:'POST',body:'{}'});$('#deviceLogin').classList.remove('hidden');$('#deviceCode').textContent=data.user_code;const link=$('#deviceLink');link.href=data.verification_uri_complete||data.verification_uri;$('#deviceStatus').textContent='Várakozás a jóváhagyásra…';deviceTimer=setInterval(()=>pollLogin(data.device_code),Math.max(4,data.interval)*1000)}catch(error){toast(error.message,'error')}
}
async function pollLogin(code){try{const data=await api('/api/auth/device/poll',{method:'POST',body:JSON.stringify({device_code:code})});if(data.status==='authorized'){clearInterval(deviceTimer);deviceTimer=null;$('#deviceStatus').textContent='Sikeresen csatlakoztatva.';toast('Az eladói fiók csatlakoztatva.','success');loadConnectionState();loadDashboard()}}catch(error){clearInterval(deviceTimer);deviceTimer=null;$('#deviceStatus').textContent=error.message;toast(error.message,'error')}}

document.addEventListener('click',event=>{const go=event.target.closest('[data-go]');if(go)navigate(go.dataset.go);const nav=event.target.closest('[data-view]');if(nav)navigate(nav.dataset.view)});
$$('.nav-item').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.view)));
$('#mobileMenu').addEventListener('click',()=>$('#sidebar').classList.toggle('open'));
$('#refreshDashboard').addEventListener('click',loadDashboard);
let searchTimer;$('#productSearch').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(loadProducts,250)});
$('#csvFile').addEventListener('change',event=>previewFile(event.target.files[0]));
const dz=$('#dropzone');['dragenter','dragover'].forEach(name=>dz.addEventListener(name,event=>{event.preventDefault();dz.classList.add('drag')}));['dragleave','drop'].forEach(name=>dz.addEventListener(name,event=>{event.preventDefault();dz.classList.remove('drag')}));dz.addEventListener('drop',event=>previewFile(event.dataTransfer.files[0]));
$('#useSample').addEventListener('click',async()=>{try{const response=await fetch('/sample.csv');if(!response.ok)throw new Error('A mintafájl nem érhető el.');const blob=await response.blob();previewFile(new File([blob],'export-minta.csv',{type:'text/csv'}))}catch(error){toast(error.message,'error')}});
$('#commitImport').addEventListener('click',commitImport);$('#settingsForm').addEventListener('submit',saveSettings);$('#checkConnection').addEventListener('click',checkConnection);$('#startLogin').addEventListener('click',startLogin);
navigate(location.hash.slice(1)||'dashboard');
