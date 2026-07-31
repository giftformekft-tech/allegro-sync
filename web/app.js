const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const titles = {dashboard:['Műveleti központ','Áttekintés'],products:['Kínálat','Termékek'],upload:['Allegro','Tesztfeltöltés'],orders:['Értékesítés','Rendelések'],import:['Kínálat','Importálás'],integrations:['Rendszer','Kapcsolatok'],settings:['Rendszer','Beállítások']};
let activePlatform = localStorage.getItem('marketplace-platform') === 'temu' ? 'temu' : 'allegro';
let currentImportId = null;
let deviceTimer = null;
let selectedCategory = null;
let uploadProducts = [];
let uploadMarketplace = null;
let uploadOptions = null;
let uploadTemplates = [];
let activeTemplate = null;
let allegroImportBatches = [];
let bulkImportProducts = [];
let temuProducts = [];
let temuVariantGroups = [];
let selectedTemuInvoiceOrder = '';
let selectedTemuShipmentOrder = '';
let temuOrders = [];

async function api(path, options={}) {
  const response = await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  const data = await response.json().catch(()=>({error:'Érvénytelen szerverválasz.'}));
  if(!response.ok){const error=new Error(data.error || `HTTP ${response.status}`);error.details=data.details;throw error}
  return data;
}
function icon(id){return `<svg><use href="#${id}"/></svg>`}
function escapeHtml(value=''){return String(value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function toast(message,type=''){const el=document.createElement('div');el.className=`toast ${type}`;el.textContent=message;$('#toasts').append(el);setTimeout(()=>el.remove(),4200)}
function formatNumber(value){return new Intl.NumberFormat('hu-HU').format(value||0)}
function formatDate(value){if(!value)return '—';return new Intl.DateTimeFormat('hu-HU',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value))}

function setPlatform(platform, refresh=true){
  activePlatform=platform==='temu'?'temu':'allegro';localStorage.setItem('marketplace-platform',activePlatform);document.body.dataset.platform=activePlatform;
  $('#platformSelect').value=activePlatform;$('#brandMark').textContent=activePlatform==='temu'?'t':'a';$('#brandName').textContent=activePlatform==='temu'?'Temu Sync':'Allegro Sync';$('#uploadNavLabel').textContent=activePlatform==='temu'?'Temu feltöltés':'Tesztfeltöltés';
  if(refresh)navigate(location.hash.slice(1)||'dashboard');
}

function navigate(view){
  if(!titles[view]) view='dashboard';
  $$('.view').forEach(el=>el.classList.toggle('active',el.id===`view-${view}`));
  $$('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.view===view));
  const title=activePlatform==='temu'&&view==='upload'?['Temu','Termékfeltöltés']:titles[view];
  $('#eyebrow').textContent=title[0]; $('#pageTitle').textContent=title[1];
  history.replaceState(null,'',`#${view}`); $('#sidebar').classList.remove('open');
  if(view==='dashboard') loadDashboard(); if(view==='products') loadProducts();
  if(view==='upload') loadUpload();
  if(view==='orders'&&activePlatform==='allegro') loadOrders();
  if(view==='orders'&&activePlatform==='temu') loadTemuOrders();
  if(view==='settings') loadSettings(); if(view==='integrations') loadConnectionState();
}

async function loadDashboard(){
  try{
    const [data,settings]=await Promise.all([api('/api/dashboard'),api('/api/settings')]); const s=data.stats;const temu=activePlatform==='temu';
    $('#statProducts').textContent=formatNumber(s.products); $('#statReady').textContent=formatNumber(s.ready);
    $('#statDrafts').textContent=`${formatNumber(s.drafts)} piszkozat`; $('#statOrders').textContent=formatNumber(s.orders);
    $('#statStock').textContent=formatNumber(s.stock); $('#navProductCount').textContent=s.products;
    $('#environmentLabel').textContent=temu?'Temu · EU':data.connection.environment==='production'?'Éles mód':'Sandbox mód';
    const ready=temu?[settings.temu_ready,s.products>0,false]:[!data.connection.problems.length,s.products>0,data.connection.user_connected];
    const items=temu?[
      ['Temu API-kulcsok beállítása',settings.temu_ready?'Az App Key, App Secret és Access Token el van mentve.':'Add meg a Temu Open Platform alkalmazásadatait.','settings'],
      ['Első termékimport',s.products?`${s.products} termékváltozat elmentve.`:'Töltsd be a forme.hu exportját.','import'],
      ['Temu V3 termékfeltöltés','A pólóvariánsok előnézete, feltöltése és állapotkövetése elkészült.','upload']
    ]:[
      ['API-kulcsok beállítása',data.connection.problems.length?data.connection.problems[0]:'Az alkalmazásadatok ki vannak töltve.','settings'],
      ['Első termékimport',s.products?`${s.products} termékváltozat elmentve.`:'Töltsd be a forme.hu CSV-exportját.','import'],
      ['Eladói fiók csatlakoztatása',data.connection.user_connected?'A felhasználói token rendelkezésre áll.':'OAuth jóváhagyás szükséges.','integrations']
    ];
    $('#checklist').innerHTML=items.map((item,i)=>`<div class="check-item ${ready[i]?'done':''}"><div class="check-dot">${icon(ready[i]?'i-check':'i-arrow')}</div><div><strong>${escapeHtml(item[0])}</strong><span>${escapeHtml(item[1])}</span></div>${ready[i]?'':`<button class="text-button" data-go="${item[2]}">Megnyitás</button>`}</div>`).join('');
    const done=ready.filter(Boolean).length; $('#progressLabel').textContent=`${done}/3`; $('#progressBar').style.width=`${done/3*100}%`;
    $('#heroTitle').textContent=temu?'Jó reggelt! Innen indul a Temu működésed.':'Jó reggelt! Innen indul az Allegro működésed.';
    $('#heroText').textContent=s.products?`${s.products} változat várja a következő műveletet.`:'Kezdésként állítsd be az API-kulcsokat, majd tölts be egy CSV-t.';
    const connected=temu?settings.temu_ready:!data.connection.problems.length;const status=$('#globalStatus'); status.classList.toggle('connected',connected); status.querySelector('span').textContent=temu?(settings.temu_ready?'Temu API beállítva':'Temu beállítás szükséges'):(data.connection.problems.length?'Beállítás szükséges':(data.connection.user_connected?'Allegro csatlakoztatva':'API beállítva'));
    $('#activityList').innerHTML=data.activity.length?data.activity.map(a=>`<div class="timeline-item"><div class="timeline-symbol">${icon(a.kind==='import'?'i-upload':a.kind==='connection'?'i-link':'i-settings')}</div><p>${escapeHtml(a.message)}</p><time>${formatDate(a.created_at)}</time></div>`).join(''):'<div class="timeline-empty">Az első műveletek itt jelennek majd meg.</div>';
  }catch(error){toast(error.message,'error')}
}

async function loadProducts(){
  try{
    const q=encodeURIComponent($('#productSearch').value.trim());const marketplace=activePlatform==='temu'?'temu_api_v3':'allegro'; const data=await api(`/api/products?q=${q}&marketplace=${marketplace}`); const rows=data.products;
    $('#productResultCount').textContent=`${rows.length} találat`; $('#navProductCount').textContent=rows.length;
    $('#productEmpty').classList.toggle('hidden',rows.length>0);
    $('#productRows').innerHTML=rows.map(row=>`<tr><td><div class="product-cell">${row.image_url?`<img class="product-thumb" src="${escapeHtml(row.image_url)}" alt="" loading="lazy">`:'<div class="product-thumb"></div>'}<div><strong>${escapeHtml(row.title)}</strong><small>${escapeHtml(row.name)}</small></div></div></td><td><strong>${escapeHtml(row.sku)}</strong><small>${escapeHtml(row.parent_sku)}</small></td><td>${escapeHtml(row.color)} · ${escapeHtml(row.size)}</td><td><strong>${formatNumber(Number(row.price_huf))} Ft</strong></td><td>${formatNumber(row.stock)}</td><td><span class="badge ${row.status==='inactive'?'good':'neutral'}">${row.status==='inactive'?'Inaktív az Allegrón':'Piszkozat'}</span>${row.allegro_offer_id?`<small>${escapeHtml(row.allegro_offer_id)}</small>`:''}</td></tr>`).join('');
  }catch(error){toast(error.message,'error')}
}

function categoryTrail(item){const names=[];let current=item;while(current){if(current.name)names.unshift(current.name);current=current.parent}return names.join(' / ')}
function selectedTemuFamilyProducts(){const key=$('#temuProductFamily').value;return temuProducts.filter(product=>(product.parent_sku||product.name)===key)}
function renderTemuProductFamilies(){
  const groups=new Map();temuProducts.forEach(product=>{const key=product.parent_sku||product.name;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(product)});
  $('#temuProductFamily').innerHTML='<option value="">Válassz importált termékcsaládot…</option>'+[...groups.entries()].map(([key,products])=>{const types=[...new Set(products.map(item=>item.type).filter(Boolean))].join(', ');return `<option value="${escapeHtml(key)}">${escapeHtml(products[0].name)} · ${escapeHtml(types)} · ${products.length} változat</option>`}).join('');
}
function temuSuggestedCategory(products){
  const words=products.map(product=>`${product.type||''} ${product.type_label||''}`).join(' ').toLocaleLowerCase('hu');
  if(words.includes('gyerek')||words.includes('child')||words.includes('kid'))return "Kids' Clothing / T-Shirts";
  if(words.includes('nő')||words.includes('noi')||words.includes('women'))return "Women's Clothing / T-Shirts";
  return "Men's Clothing / T-Shirts";
}
function renderTemuV3VariantRows(){
  const products=selectedTemuFamilyProducts();const rows=new Map();products.forEach(product=>{const key=`${product.type}\u0000${product.color}`;if(!rows.has(key))rows.set(key,[]);rows.get(key).push(product)});temuVariantGroups=[...rows.values()];
  $('#temuVariantRows').innerHTML=temuVariantGroups.length?temuVariantGroups.map((group,index)=>{const first=group[0];const sizes=[...new Set(group.map(item=>item.size).filter(Boolean))];const stock=group.reduce((sum,item)=>sum+Number(item.stock||0),0);return `<label class="temu-variant-row"><input type="checkbox" data-temu-row-index="${index}" checked>${first.image_url?`<img src="${escapeHtml(first.image_url)}" alt="" loading="lazy">`:'<span class="temu-variant-image"></span>'}<span><strong>${escapeHtml(first.type||'Termék')}</strong><small>${escapeHtml(first.color||'Nincs szín')}</small></span><span class="temu-size-chips">${sizes.map(size=>`<span>${escapeHtml(size)}</span>`).join('')}</span><span class="temu-variant-stock">${formatNumber(stock)} db</span></label>`}).join(''):'<div class="wizard-empty">Ehhez a termékcsaládhoz nincs importált variáns.</div>';
  const commonImages=[...new Set(products.map(item=>item.common_image_url).filter(Boolean))];const common=$('#temuCommonImage');common.classList.toggle('empty',!commonImages.length);common.innerHTML=commonImages.length?`<img src="${escapeHtml(commonImages[0])}" alt="" loading="lazy"><div><strong>Közös termékkép</strong><small>${commonImages.length===1?'Egyszer kerül a Temu galériába.':`${commonImages.length} különböző kép van az importban; ellenőrizd a Woo terméket.`}</small></div>`:'<span class="temu-common-image-preview"></span><div><strong>Nincs közös termékkép</strong><small>A variánsképek ettől még közvetlen URL-lel feltölthetők.</small></div>';
  if(products.length){$('#temuGoodsName').value=products[0].name||products[0].title||'';$('#temuExternalCategory').value=products[0].temu_category_name||temuSuggestedCategory(products)}
  $('#temuSelectionWrap').classList.add('hidden');
}
function selectedTemuV3Products(){return temuVariantGroups.filter((_group,index)=>$(`[data-temu-row-index="${index}"]`)?.checked).flat()}
function temuV3Request(includeConfirmation=false){
  const family=$('#temuProductFamily').value;if(!family)throw new Error('Válassz importált termékcsaládot.');const products=selectedTemuV3Products();if(!products.length)throw new Error('Legalább egy teljes típus- és színsort válassz ki.');
  const options={external_goods_id:family,goods_name:$('#temuGoodsName').value.trim(),category_name:$('#temuExternalCategory').value.trim(),currency:$('#temuCurrency').value,language:$('#temuLanguage').value.trim(),product_type:Number($('#temuProductType').value),shipment_limit_day:Number($('#temuShipmentDays').value),weight_g:$('#temuPackageWeight').value.trim(),length_cm:$('#temuPackageLength').value.trim(),width_cm:$('#temuPackageWidth').value.trim(),height_cm:$('#temuPackageHeight').value.trim(),origin_country:$('#temuOriginCountry').value.trim(),manufacturer:$('#temuManufacturer').value.trim()};
  const request={product_ids:products.map(product=>product.id),options};if(includeConfirmation)request.confirmation=$('#temuConfirmation').value;return request;
}
function renderTemuUploads(rows){
  $('#temuUploadHistory').innerHTML=rows.length?rows.map(row=>`<div class="temu-upload-row"><div><strong>${escapeHtml(row.external_goods_id)}</strong><small>${row.goods_id?`Temu goodsId: ${escapeHtml(row.goods_id)}`:'Nem jött létre Temu-azonosító'}${row.error?` · ${escapeHtml(row.error)}`:''}</small></div><span class="badge ${row.error?'bad':String(row.status).toLowerCase()==='created'?'good':'neutral'}">${escapeHtml(row.status||'ismeretlen')}</span><time>${formatDate(row.updated_at)}</time>${row.goods_id?`<button class="secondary" data-temu-refresh="${row.id}">Állapot frissítése</button>`:''}</div>`).join(''):'<div class="wizard-empty">Még nincs API-n feltöltött Temu-termék.</div>';
}
async function loadTemuUploads(){try{const data=await api('/api/temu/uploads');renderTemuUploads(data.uploads||[])}catch(error){toast(error.message,'error')}}
async function loadTemuV3Upload(){
  try{const [products,settings,uploads]=await Promise.all([api('/api/products?marketplace=temu_api_v3'),api('/api/settings'),api('/api/temu/uploads')]);temuProducts=products.products;renderTemuProductFamilies();renderTemuUploads(uploads.uploads||[]);if(!temuProducts.length)toast('Előbb készíts külön Temu API Export CSV-t a Woo-bővítményben, majd importáld ide.','error');if(!settings.temu_ready)toast('A feltöltéshez add meg a Temu App Key, App Secret és Access Token értékét a Beállításokban.','error')}catch(error){toast(error.message,'error')}
}
async function previewTemuV3Selection(){
  try{const data=await api('/api/temu/products/preview',{method:'POST',body:JSON.stringify(temuV3Request())});$('#temuSelectionPayload').textContent=JSON.stringify(data.payload,null,2);$('#temuSelectionWrap').classList.remove('hidden');toast(`A V3 kérés rendben: ${data.summary.sku_count} SKU, ${data.summary.image_count} kép. Még semmit nem küldtünk a Temunak.`,'success')}catch(error){toast(error.message,'error')}
}
async function createTemuV3Product(){
  try{const data=await api('/api/temu/products/create',{method:'POST',body:JSON.stringify(temuV3Request(true))});const result=$('#temuUploadResult');result.classList.remove('hidden');result.innerHTML=`${icon('i-check')}<div><strong>A Temu V3 termékfeltöltés elküldve.</strong><span>goodsId: ${escapeHtml(data.goods_id||'feldolgozás alatt')} · requestId: ${escapeHtml(data.request_id||'—')}</span></div>`;$('#temuConfirmation').value='';toast('A Temu termékfeltöltést elfogadta.','success');await loadTemuUploads();loadProducts();loadDashboard()}catch(error){toast(error.message,'error')}
}
async function refreshTemuUpload(id){
  try{const data=await api(`/api/temu/uploads/${id}/refresh`,{method:'POST',body:'{}'});toast(`Temu állapot: ${data.status||'ismeretlen'}.`,'success');await loadTemuUploads()}catch(error){toast(error.message,'error')}
}
async function loadUpload(){
  if(activePlatform==='temu'){loadTemuV3Upload();return}
  try{
    const [products,settings,templates,imports]=await Promise.all([api('/api/products?marketplace=allegro'),api('/api/settings'),api('/api/templates'),api('/api/imports?marketplace=allegro')]);uploadProducts=products.products;uploadTemplates=templates.templates;allegroImportBatches=imports.imports||[];
    const select=$('#offerProduct');const previous=select.value;select.innerHTML='<option value="">Válassz importált terméket…</option>'+uploadProducts.map(p=>`<option value="${p.id}">${escapeHtml(p.title)} · ${escapeHtml(p.sku)}</option>`).join('');if(previous)select.value=previous;
    renderTemplateOptions(activeTemplate?.id);
    renderBulkImportBatches();
    $('#uploadEnvironment').textContent=settings.environment==='production'?'ÉLES':'SANDBOX';$('#uploadEnvironment').classList.toggle('production',settings.environment==='production');
    $('#bulkUploadEnvironment').textContent=settings.environment==='production'?'ÉLES':'SANDBOX';$('#bulkUploadEnvironment').classList.toggle('production',settings.environment==='production');
    if(!uploadProducts.length)toast('Előbb importálj legalább egy megfelelő terméket.','error');
    try{
      const data=await api('/api/offer-options');uploadOptions=data;uploadMarketplace=data.marketplace;
      $('#marketplaceId').textContent=uploadMarketplace.id;$('#marketplaceCurrency').textContent=uploadMarketplace.currency;
      renderOfferOptions(data);
      syncOfferPrice();
    }catch(error){uploadOptions=null;uploadMarketplace=null;$('#marketplaceId').textContent='Eladói fiók szükséges';$('#marketplaceCurrency').textContent='—';toast(error.message,'error')}
  }catch(error){toast(error.message,'error')}
}
function renderOfferOptions(data){
  const rates=data.shipping_rates||[];const producers=data.responsible_producers||[];const persons=data.responsible_persons||[];
  $('#shippingRate').innerHTML='<option value="">Válassz árlistát…</option>'+rates.map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} · ${escapeHtml((item.marketplaces||[]).map(m=>m.id).join(', '))}</option>`).join('');
  $('#responsibleProducer').innerHTML='<option value="">Válassz gyártót…</option>'+producers.map(item=>{const country=item.producerData?.address?.countryCode||'';return `<option value="${escapeHtml(item.id)}" data-country="${escapeHtml(country)}">${escapeHtml(item.name)}${country?` · ${escapeHtml(country)}`:''}</option>`}).join('');
  $('#responsiblePerson').innerHTML='<option value="">Nem szükséges / nincs kiválasztva</option>'+persons.map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  if(rates.length===1)$('#shippingRate').value=String(rates[0].id);if(producers.length===1)$('#responsibleProducer').value=String(producers[0].id);
  if(!rates.length)toast('Nincs használható szállítási árlista az alappiacon.','error');
  if(!producers.length)toast('Előbb ments el gyártói adatokat az Allegro-fiókban.','error');
  updateProducerHint();
}
function updateProducerHint(){const option=$('#responsibleProducer').selectedOptions[0];const country=option?.dataset.country||'';const eu=['AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR','DE','GR','HU','IE','IT','LV','LT','LU','MT','NL','PL','PT','RO','SK','SI','ES','SE'];$('#producerHint').textContent=country&&!eu.includes(country)?`${country}: EU-n kívüli gyártó, a felelős személy kötelező.`:country?`${country}: EU-s gyártó, külön felelős személy általában nem szükséges.`:'Az Allegro-fiókban elmentett gyártói rekord.'}
function togglePreorder(){$('#preorderDateWrap').classList.toggle('hidden',!$('#preorder').checked)}
function syncOfferPrice(){
  const product=uploadProducts.find(item=>String(item.id)===$('#offerProduct').value);
  if($('#priceFromProduct').checked&&uploadMarketplace?.currency==='HUF'&&product)$('#offerPrice').value=product.price_huf||'';
  else if($('#priceFromProduct').checked&&!product)$('#offerPrice').value='';
  if($('#stockFromProduct').checked)$('#offerStock').value=product?.stock??'';
}
function renderTemplateOptions(selectedId=''){
  const select=$('#offerTemplate');select.innerHTML='<option value="">Válassz sablont…</option>'+uploadTemplates.map(template=>`<option value="${template.id}">${escapeHtml(template.name)} · ${escapeHtml(template.category_name)}</option>`).join('');if(selectedId)select.value=String(selectedId);
}
async function reloadTemplates(selectedId=''){
  const data=await api('/api/templates');uploadTemplates=data.templates;renderTemplateOptions(selectedId);renderBulkTemplateAssignments(true);
}

function renderBulkImportBatches(){
  const select=$('#bulkImportBatch');const previous=select.value;
  select.innerHTML='<option value="">Válassz importcsomagot…</option>'+allegroImportBatches.map(batch=>`<option value="${batch.id}">${escapeHtml(batch.filename)} · ${batch.product_count} variáns · ${escapeHtml(formatDate(batch.created_at))}</option>`).join('');
  if(previous&&allegroImportBatches.some(batch=>String(batch.id)===previous)){select.value=previous;loadBulkImportBatch()}else{bulkImportProducts=[];renderBulkTemplateAssignments();renderBulkImportStats()}
}
function renderBulkImportStats(){
  const batch=allegroImportBatches.find(item=>String(item.id)===$('#bulkImportBatch').value);const target=$('#bulkImportStats');
  if(!batch){target.innerHTML='<span>Válassz egy véglegesített Allegro-importot.</span>';return}
  target.innerHTML=`<span><strong>${batch.product_count}</strong> variáns</span><span><strong>${batch.remaining_count}</strong> feltöltendő</span><span><strong>${batch.uploaded_count}</strong> már feltöltve</span>`;
}
function bulkTemplateSelections(){const result={};$$('[data-bulk-template]',$('#bulkTemplateAssignments')).forEach(select=>{if(select.value)result[select.dataset.bulkTemplate]=select.value});return result}
function renderBulkTemplateAssignments(preserve=false){
  const target=$('#bulkTemplateAssignments');const previous=preserve?bulkTemplateSelections():{};const types=[...new Set(bulkImportProducts.map(product=>product.type))].sort();
  if(!types.length){target.innerHTML='<div class="wizard-empty">A csomag kiválasztása után itt jelennek meg a terméktípusok.</div>';return}
  target.innerHTML=types.map(type=>{const count=bulkImportProducts.filter(product=>product.type===type).length;const automatic=previous[type]||(uploadTemplates.length===1?String(uploadTemplates[0].id):'');const options=uploadTemplates.map(template=>`<option value="${template.id}" ${String(template.id)===automatic?'selected':''}>${escapeHtml(template.name)} · ${escapeHtml(template.category_name)}</option>`).join('');return `<label class="bulk-template-row"><span><strong>${escapeHtml(type)}</strong><small>${count} variáns ebben a csomagban</small></span><select data-bulk-template="${escapeHtml(type)}"><option value="">Válassz feltöltési sablont…</option>${options}</select></label>`}).join('');
}
async function loadBulkImportBatch(hideResult=false){
  const importId=Number($('#bulkImportBatch').value||0);renderBulkImportStats();if(hideResult)$('#bulkOfferResult').classList.add('hidden');
  if(!importId){bulkImportProducts=[];renderBulkTemplateAssignments();return}
  try{const data=await api(`/api/imports/${importId}/products?marketplace=allegro`);bulkImportProducts=data.products||[];renderBulkTemplateAssignments()}catch(error){bulkImportProducts=[];renderBulkTemplateAssignments();toast(error.message,'error')}
}
function bulkOfferRequest(includeConfirmation=false){
  const importId=Number($('#bulkImportBatch').value||0);if(!importId)throw new Error('Válassz importcsomagot.');if(!bulkImportProducts.length)throw new Error('A csomagban nincs feltölthető Allegro-termék.');
  const templateAssignments=bulkTemplateSelections();const types=[...new Set(bulkImportProducts.map(product=>product.type))];const missing=types.filter(type=>!templateAssignments[type]);if(missing.length)throw new Error(`Válassz sablont ehhez: ${missing.join(', ')}`);
  const request={import_id:importId,template_assignments:templateAssignments};if(includeConfirmation)request.confirmation=$('#bulkUploadConfirmation').value;return request;
}
function renderBulkOfferResult(data,created=false){
  const summary=data.summary||{};const target=$('#bulkOfferResult');target.classList.remove('hidden');
  const headline=created?`${summary.created||0} ajánlat létrejött`:`${summary.ready||0} variáns feltölthető`;
  const rows=(data.rows||[]).map(row=>{const label=row.state==='created'?'Létrehozva':row.state==='ready'?'Feltölthető':row.state==='skipped'?'Kihagyva':'Hiba';return `<tr><td><strong>${escapeHtml(row.title)}</strong><small>${escapeHtml(row.sku)}</small></td><td>${escapeHtml(row.type)} · ${escapeHtml(row.color)} · ${escapeHtml(row.size)}</td><td><span class="badge ${row.state==='created'||row.state==='ready'?'good':row.state==='error'?'bad':'neutral'}">${label}</span>${row.message?`<small>${escapeHtml(row.message)}</small>`:''}</td></tr>`}).join('');
  target.innerHTML=`<div class="bulk-result-head"><strong>${headline}</strong><span>${summary.skipped||0} kihagyva · ${summary.errors||0} hibás</span></div><div class="table-wrap"><table><thead><tr><th>Termék</th><th>Variáns</th><th>Állapot</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
async function previewBulkOffers(){
  let request;try{request=bulkOfferRequest()}catch(error){toast(error.message,'error');return}const button=$('#previewBulkOffers');button.disabled=true;button.textContent='Ellenőrzés…';
  try{const data=await api('/api/offers/bulk-preview',{method:'POST',body:JSON.stringify(request)});renderBulkOfferResult(data);toast(`${data.summary.ready} variáns feltölthető.`,'success')}catch(error){toast(error.message,'error')}finally{button.disabled=false;button.textContent='Csomag ellenőrzése'}
}
async function createBulkOffers(){
  let request;try{request=bulkOfferRequest(true)}catch(error){toast(error.message,'error');return}if($('#bulkUploadEnvironment').classList.contains('production')&&!confirm(`Ez az ÉLES Allegro-fiókban indítja el a csomag ${bulkImportProducts.length} variánsának feltöltését INAKTÍV ajánlatként. Folytatod?`))return;
  const button=$('#createBulkOffers');button.disabled=true;button.textContent='Csomag feltöltése…';
  try{const data=await api('/api/offers/bulk-create',{method:'POST',body:JSON.stringify(request)});renderBulkOfferResult(data,true);$('#bulkUploadConfirmation').value='';toast(`${data.summary.created} ajánlat létrejött, ${data.summary.errors} hibás.`,data.summary.errors?'':'success');await loadProducts();await loadDashboard();await loadUpload()}catch(error){toast(error.message,'error')}finally{button.disabled=false;button.innerHTML=`${icon('i-upload')}Összes variáns feltöltése`}
}
async function searchCategories(){
  const phrase=$('#categoryPhrase').value.trim();const button=$('#searchCategories');button.textContent='Keresés…';
  try{const data=await api(`/api/categories/suggest?q=${encodeURIComponent(phrase)}`);$('#categoryResults').innerHTML=data.categories.length?data.categories.map(c=>`<div class="category-result"><div><strong>${escapeHtml(c.name)}</strong><small>${escapeHtml(categoryTrail(c))}</small></div><button class="secondary" data-category-id="${escapeHtml(c.id)}">Ellenőrzés</button></div>`).join(''):'<div class="wizard-empty">Nincs találat. Próbálj pontosabb terméknevet.</div>'}catch(error){toast(error.message,'error')}finally{button.textContent='Kategóriák keresése'}
}
async function inspectCategory(categoryId,template=undefined){
  try{
    if(template!==undefined)activeTemplate=template;
    const productId=$('#offerProduct').value;const suffix=productId?`?product_id=${encodeURIComponent(productId)}`:'';const data=await api(`/api/categories/${encodeURIComponent(categoryId)}${suffix}`);selectedCategory=data.category;renderCategory(data.category,activeTemplate);$('#categoryInspector').classList.remove('hidden');$('#offerPreviewCard').classList.remove('hidden');$('#categoryInspector').scrollIntoView({behavior:'smooth',block:'start'});return true;
  }catch(error){toast(error.message,'error');return false}
}
function renderCategory(category,template=null){
  $('#selectedCategoryName').textContent=category.name;$('#selectedCategoryPath').textContent=category.path.map(p=>p.name).join(' / ');
  renderCategoryFacts(category,category.gtin_required);
  const visible=category.parameters.filter(p=>(p.is_gtin?p.required_for_product:(p.required||p.required_for_product))||p.suggested_source);$('#parameterFields').innerHTML=visible.length?visible.map(parameterField).join(''):'<div class="wizard-empty">Ebben a kategóriában nincs automatikusan kitölthető vagy kötelező paraméter.</div>';
  applyTemplateRules(template);
  refreshConditionalParameters();
}
function renderCategoryFacts(category,gtinRequired){
  const usable=category.leaf&&category.product_creation_enabled&&category.offer_creation_enabled&&!gtinRequired;const verdict=$('#categoryVerdict');verdict.textContent=usable?'GTIN nélkül folytatható':gtinRequired?'GTIN kötelező':'Korlátozott';verdict.className=`badge ${usable?'good':gtinRequired?'bad':'neutral'}`;
  const facts=[['Levélkategória',category.leaf],['Saját termék',category.product_creation_enabled],['Termékajánlat',category.offer_creation_enabled],['GTIN nem kötelező',!gtinRequired]];$('#verdictGrid').innerHTML=facts.map(([label,ok])=>`<div class="verdict-item ${ok?'ok':'bad'}"><span>${icon(ok?'i-check':'i-alert')}</span><div><strong>${escapeHtml(label)}</strong><small>${ok?'Rendben':'Nem teljesül'}</small></div></div>`).join('');
}
function conditionMatches(condition){
  if(!condition)return true;const values={};$$('[data-parameter]',$('#parameterFields')).forEach(field=>values[field.dataset.parameter]=field.value);
  const withValues=Array.isArray(condition.parametersWithValue)?condition.parametersWithValue:[];const withoutValues=Array.isArray(condition.parametersWithoutValue)?condition.parametersWithoutValue:[];
  return withValues.every(rule=>(rule.oneOfValueIds||[]).map(String).includes(String(values[String(rule.id)]||'')))&&withoutValues.every(rule=>!String(values[String(rule.id)]||'').trim());
}
function effectiveRequired(parameter){return Boolean((parameter.required||parameter.required_for_product)&&conditionMatches(parameter.required_if))}
function refreshConditionalParameters(){
  if(!selectedCategory)return;selectedCategory.parameters.forEach(parameter=>{const field=$$('[data-parameter]',$('#parameterFields')).find(item=>item.dataset.parameter===String(parameter.id));if(!field)return;const required=effectiveRequired(parameter);const card=field.closest('.parameter-field');card.classList.toggle('gtin-field',Boolean(parameter.is_gtin&&required));card.classList.toggle('optional-field',!required);const mark=card.querySelector('.required-mark');if(mark)mark.classList.toggle('hidden',!required);const state=card.querySelector('.requirement-state');if(state)state.textContent=required?'Kötelező':parameter.is_gtin?'Nincs GTIN – opcionális':parameter.required_if?'Feltételesen opcionális':'Opcionális'});
  const gtinRequired=selectedCategory.parameters.filter(parameter=>parameter.is_gtin).some(effectiveRequired);renderCategoryFacts(selectedCategory,gtinRequired);
}
function parameterField(parameter){
  const meta=`${parameter.describes_product||parameter.required_for_product?'Termékadat':'Ajánlatadat'}${parameter.unit?` · ${parameter.unit}`:''}`;const dynamic=Boolean(parameter.suggested_source);let control;
  if(parameter.type==='dictionary')control=`<select data-parameter="${escapeHtml(parameter.id)}" data-suggested="${escapeHtml(parameter.suggested_value||'')}"><option value="">Válassz…</option>${parameter.dictionary.map(v=>`<option value="${escapeHtml(v.id)}" ${String(v.id)===String(parameter.suggested_value)?'selected':''}>${escapeHtml(v.value)}</option>`).join('')}</select>`;
  else control=`<input data-parameter="${escapeHtml(parameter.id)}" data-suggested="${escapeHtml(parameter.suggested_value||'')}" value="${escapeHtml(parameter.suggested_value||'')}" placeholder="Add meg az értéket">`;
  const dynamicLabel=parameter.suggested_source==='allegro_default'?'Allegro-alapértékből frissül':'Termékből frissül';const source=dynamic?`<span class="parameter-source"><input type="checkbox" data-dynamic-param="${escapeHtml(parameter.id)}" checked> ${dynamicLabel}</span>`:'<span class="parameter-source manual-source">Kézzel vagy sablonból megadható</span>';
  return `<label class="parameter-field ${dynamic?'dynamic':''}"><span>${escapeHtml(parameter.name)} <b class="required-mark">*</b></span>${control}<small>${escapeHtml(meta)} · ID ${escapeHtml(parameter.id)} · <em class="requirement-state">Kötelező</em></small>${source}</label>`;
}
function applyTemplateRules(template){
  const rules=new Map((template?.rules||[]).map(rule=>[String(rule.parameter_id),rule]));
  $$('[data-parameter]',$('#parameterFields')).forEach(field=>{const rule=rules.get(field.dataset.parameter);if(!rule)return;const dynamic=$(`[data-dynamic-param="${field.dataset.parameter}"]`,$('#parameterFields'));if(dynamic)dynamic.checked=rule.mode==='product';if(rule.mode==='fixed'||!dynamic)field.value=rule.value;else field.value=field.dataset.suggested||'';field.closest('.parameter-field').classList.toggle('dynamic',Boolean(dynamic?.checked))});
  const priceRule=rules.get('__price__');$('#priceFromProduct').checked=!priceRule||priceRule.mode==='product';if(priceRule?.mode==='fixed')$('#offerPrice').value=priceRule.value;else syncOfferPrice();
  const stockRule=rules.get('__stock__');if(stockRule){$('#stockFromProduct').checked=stockRule.mode==='product';if(stockRule.mode==='fixed')$('#offerStock').value=stockRule.value;else syncOfferPrice()}
  const fixedFields={__shipping_rate__:'#shippingRate',__handling_time__:'#handlingTime',__producer__:'#responsibleProducer',__responsible_person__:'#responsiblePerson',__safety_information__:'#safetyInformation'};Object.entries(fixedFields).forEach(([key,selector])=>{const rule=rules.get(key);if(rule&&rule.mode==='fixed')$(selector).value=rule.value});
  const preorderRule=rules.get('__preorder__');if(preorderRule)$('#preorder').checked=preorderRule.value==='true';togglePreorder();updateProducerHint();
  refreshConditionalParameters();
}
function offerRequest(){const parameters={};$$('[data-parameter]',$('#parameterFields')).forEach(field=>{if(field.value)parameters[field.dataset.parameter]=field.value});let shipmentDate='';if($('#preorder').checked){const raw=$('#shipmentDate').value;if(!raw)throw new Error('Előrendelésnél add meg a várható feladási dátumot.');shipmentDate=new Date(raw).toISOString()}return{product_id:Number($('#offerProduct').value||0),category_id:selectedCategory?.id||'',price_amount:$('#offerPrice').value.trim(),stock_available:$('#offerStock').value.trim(),shipping_rate_id:$('#shippingRate').value,handling_time:$('#handlingTime').value,shipment_date:shipmentDate,responsible_producer_id:$('#responsibleProducer').value,responsible_person_id:$('#responsiblePerson').value,safety_information:$('#safetyInformation').value.trim(),parameters}}
async function previewOffer(){
  if(!selectedCategory){toast('Előbb válassz és ellenőrizz egy kategóriát.','error');return}if(!$('#offerProduct').value){toast('Válassz egy importált terméket.','error');return}
  try{const request=offerRequest();const data=await api('/api/offers/preview',{method:'POST',body:JSON.stringify(request)});uploadMarketplace=data.marketplace;$('#marketplaceId').textContent=data.marketplace.id;$('#marketplaceCurrency').textContent=data.marketplace.currency;$('#offerPayload').textContent=JSON.stringify(data.payload,null,2);$('#payloadWrap').classList.remove('hidden');toast('A feltöltési payload elkészült.','success')}catch(error){toast(error.message,'error')}
}
async function createOffer(){
  if(!selectedCategory){toast('Előbb válassz kategóriát.','error');return}let request;try{request={...offerRequest(),confirmation:$('#uploadConfirmation').value}}catch(error){toast(error.message,'error');return}
  if($('#uploadEnvironment').classList.contains('production')&&!confirm('Ez az ÉLES Allegro-fiókban hoz létre egy INAKTÍV ajánlatot. Folytatod?'))return;
  const button=$('#createOffer');button.textContent='Feltöltés folyamatban…';
  try{const data=await api('/api/offers/create',{method:'POST',body:JSON.stringify(request)});const result=$('#offerResult');result.classList.remove('hidden');result.innerHTML=`${icon('i-check')}<div><strong>Az inaktív ajánlat létrejött.</strong><span>Ajánlatazonosító: ${escapeHtml(data.offer_id||'feldolgozás alatt')} · HTTP ${data.status}</span></div>`;toast('Az Allegro tesztajánlat létrejött.','success');loadProducts();loadDashboard()}catch(error){toast(error.message,'error')}finally{button.innerHTML=`${icon('i-upload')}Inaktív tesztajánlat létrehozása`}
}
async function applySelectedTemplate(){
  const template=uploadTemplates.find(item=>String(item.id)===$('#offerTemplate').value);if(!template){toast('Válassz egy mentett sablont.','error');return}
  activeTemplate=template;$('#templateName').value=template.name;
  if(await inspectCategory(template.category_id,template))toast(`A(z) ${template.name} sablon betöltve.`,'success');
}
function collectTemplateRules(){
  const rules=$$('[data-parameter]',$('#parameterFields')).map(field=>{const dynamic=$(`[data-dynamic-param="${field.dataset.parameter}"]`,$('#parameterFields'));return{parameter_id:field.dataset.parameter,mode:dynamic?.checked?'product':'fixed',value:dynamic?.checked?'':field.value}});
  rules.push({parameter_id:'__price__',mode:$('#priceFromProduct').checked?'product':'fixed',value:$('#priceFromProduct').checked?'':$('#offerPrice').value.trim()});
  rules.push({parameter_id:'__stock__',mode:$('#stockFromProduct').checked?'product':'fixed',value:$('#stockFromProduct').checked?'':$('#offerStock').value.trim()});
  [['__shipping_rate__','#shippingRate'],['__handling_time__','#handlingTime'],['__producer__','#responsibleProducer'],['__responsible_person__','#responsiblePerson'],['__safety_information__','#safetyInformation']].forEach(([parameter,selector])=>rules.push({parameter_id:parameter,mode:'fixed',value:$(selector).value}));rules.push({parameter_id:'__preorder__',mode:'fixed',value:String($('#preorder').checked)});return rules;
}
async function saveTemplate(){
  if(!selectedCategory){toast('Előbb válassz és ellenőrizz egy kategóriát.','error');return}const name=$('#templateName').value.trim();
  try{const data=await api('/api/templates',{method:'POST',body:JSON.stringify({name,category_id:selectedCategory.id,category_name:selectedCategory.name,rules:collectTemplateRules()})});activeTemplate=data.template;await reloadTemplates(data.template.id);toast('A feltöltési sablon elmentve.','success')}catch(error){toast(error.message,'error')}
}
async function deleteTemplate(){
  const template=uploadTemplates.find(item=>String(item.id)===$('#offerTemplate').value);if(!template){toast('Válassz törlendő sablont.','error');return}if(!confirm(`Törlöd ezt a sablont: ${template.name}?`))return;
  try{await api(`/api/templates/${template.id}`,{method:'DELETE'});if(activeTemplate?.id===template.id)activeTemplate=null;$('#templateName').value='';await reloadTemplates();toast('A sablon törölve.','success')}catch(error){toast(error.message,'error')}
}

async function previewFile(file){
  if(!file)return; if(file.size>10_000_000){toast('A CSV legfeljebb 10 MB lehet.','error');return}
  const drop=$('#dropzone'); drop.classList.add('drag');
  try{const content=await file.text();const data=await api('/api/import/preview',{method:'POST',body:JSON.stringify({filename:file.name,content})});renderPreview(data);toast('A CSV ellenőrzése elkészült.','success')}catch(error){toast(error.message,'error')}finally{drop.classList.remove('drag')}
}
function renderPreview(data){
  currentImportId=data.import_id; const s=data.summary; $('#previewCard').classList.remove('hidden');
  const targets=[...new Set(data.rows.map(row=>row.marketplace).filter(Boolean))];const targetLabel=targets.length===1?(targets[0]==='temu_api_v3'?'Temu API V3':'Allegro'):'Vegyes / hibás export';
  $('#previewSummary').innerHTML=`<span>${escapeHtml(targetLabel)}</span><span>${s.total} sor</span><span class="ok">${s.valid} megfelelő</span><span class="bad">${s.invalid} hibás · ${s.errors} hiba</span>`;
  $('#commitCount').textContent=`${s.valid} megfelelő sor`; $('#commitImport').disabled=s.valid===0;
  $('#previewRows').innerHTML=data.rows.map(row=>`<tr><td>${row.line}</td><td><strong>${escapeHtml(row.title||row.name)}</strong><small>${escapeHtml(row.name)}</small></td><td>${escapeHtml(row.sku)}</td><td>${formatNumber(Number(row.price_huf))} Ft</td><td>${formatNumber(row.stock)}</td><td>${row.problems.length?`<div class="problem-list">${row.problems.map(escapeHtml).join('<br>')}</div>`:'<span class="badge good">Rendben</span>'}</td></tr>`).join('');
  $('#previewCard').scrollIntoView({behavior:'smooth',block:'start'});
}
async function commitImport(){
  if(!currentImportId)return; const button=$('#commitImport');button.disabled=true;
  try{const data=await api('/api/import/commit',{method:'POST',body:JSON.stringify({import_id:currentImportId})});toast(`${data.imported} termékváltozat importálva.`,'success');setTimeout(()=>navigate('products'),500)}catch(error){toast(error.message,'error');button.disabled=false}
}

function orderStatus(status){return {READY_FOR_PROCESSING:'Feldolgozásra kész',BOUGHT:'Megvásárolva',FILLED_IN:'Kitöltve',CANCELLED:'Törölve'}[status]||status||'—'}
function invoiceStatus(row){
  if(row.invoice_status==='uploaded')return '<span class="badge good">Allegróra feltöltve</span>';
  if(row.invoice_status==='upload_failed')return '<span class="badge bad">Feltöltési hiba</span>';
  if(['created','uploading'].includes(row.invoice_status))return '<span class="badge processing">Feltöltésre vár</span>';
  return '<span class="badge neutral">Nincs számla</span>';
}
async function loadOrders(){
  const refresh=$('#refreshOrders');refresh.disabled=true;
  try{
    const data=await api('/api/orders');const rows=data.orders||[];
    $('#orderEmpty').classList.toggle('hidden',rows.length>0);
    $('#orderRows').innerHTML=rows.map(row=>{
      const retry=['upload_failed','created','uploading'].includes(row.invoice_status);
      const canCreate=row.status==='READY_FOR_PROCESSING'&&row.invoice_status!=='uploaded';
      const action=canCreate?`<button class="${retry?'secondary':'primary'}" data-invoice-order="${escapeHtml(row.id)}">${retry?'Feltöltés újrapróbálása':'Számla kiállítása'}</button>`:`<span class="muted">${row.invoice_status==='uploaded'?'Kész':'Még nem számlázható'}</span>`;
      const error=row.invoice_error?`<small title="${escapeHtml(row.invoice_error)}">${escapeHtml(row.invoice_error)}</small>`:'';
      return `<tr><td><strong>${formatDate(row.updated_at)}</strong><small class="order-id">${escapeHtml(row.id)}</small></td><td><strong>${escapeHtml(row.buyer_name||'Allegro vevő')}</strong><small>${escapeHtml(row.buyer_email)}</small></td><td><strong>${escapeHtml(row.total_amount)} ${escapeHtml(row.currency)}</strong><small>${formatNumber(row.item_count)} db</small></td><td><span class="badge ${row.status==='READY_FOR_PROCESSING'?'good':'neutral'}">${escapeHtml(orderStatus(row.status))}</span></td><td>${invoiceStatus(row)}${row.invoice_number?`<small>${escapeHtml(row.invoice_number)}</small>`:''}</td><td><div class="order-action">${action}${error}</div></td></tr>`;
    }).join('');
  }catch(error){$('#orderRows').innerHTML='';$('#orderEmpty').classList.remove('hidden');toast(error.message,'error')}finally{refresh.disabled=false}
}
async function createInvoice(orderId,button){
  if(!confirm('A Számlázz.hu éles számlát állít ki, majd a PDF-et feltöltjük az Allegro rendeléshez. Folytatod?'))return;
  const original=button.textContent;button.disabled=true;button.textContent='Számlázás és feltöltés…';
  try{
    const data=await api(`/api/orders/${encodeURIComponent(orderId)}/invoice`,{method:'POST',body:'{}'});
    toast(`${data.invoice_number} elkészült és felkerült az Allegro rendeléshez.`,'success');
    await loadOrders();loadDashboard();
  }catch(error){toast(error.message,'error');await loadOrders()}finally{button.disabled=false;button.textContent=original}
}

function temuInvoiceStatus(row){
  if(row.invoice_status==='uploaded')return '<span class="badge good">Temuhoz feltöltve</span>';
  if(row.invoice_status==='upload_failed')return '<span class="badge bad">Feltöltési hiba</span>';
  if(row.invoice_status==='created')return '<span class="badge processing">Feltöltésre vár</span>';
  return '<span class="badge neutral">Nincs számla</span>';
}
function temuShipmentStatus(row){
  if(row.shipment_status==='temu_confirmed')return `<span class="badge good">Feladva</span>${row.parcel_number?`<small>${escapeHtml(row.parcel_number)}</small>`:''}`;
  if(row.shipment_status==='temu_failed')return `<span class="badge bad">Temu-visszaírási hiba</span>${row.parcel_number?`<small>${escapeHtml(row.parcel_number)}</small>`:''}`;
  if(row.shipment_status==='label_created')return '<span class="badge processing">Címke elkészült</span>';
  return '<span class="badge neutral">Nincs feladva</span>';
}
async function loadTemuOrders(){
  const refresh=$('#refreshTemuOrders');refresh.disabled=true;
  try{
    const data=await api('/api/temu/orders');const rows=data.orders||[];temuOrders=rows;
    $('#temuOrderEmpty').classList.toggle('hidden',rows.length>0);
    $('#temuOrderRows').innerHTML=rows.map(row=>{
      const products=(row.product_names||[]).join(', ');
      const shipmentAction=row.status===3?'':row.shipment_status==='temu_confirmed'?`<a class="secondary" href="/api/temu/orders/${encodeURIComponent(row.id)}/label.pdf" target="_blank">Címke</a><button class="secondary" data-temu-tracking="${escapeHtml(row.id)}">Nyomkövetés</button>`:`<button class="primary" data-temu-shipment-preview="${escapeHtml(row.id)}">${row.shipment_status==='temu_failed'?'Feladás újrapróbálása':'Express One feladás'}</button>`;
      const invoiceAction=row.status===3?'<span class="muted">Törölt rendelés</span>':`<button class="secondary" data-temu-invoice-preview="${escapeHtml(row.id)}">Számlaadatok</button>`;
      const numbers=(row.invoice_numbers||[]).join(', ');
      const error=[row.invoice_error,row.shipment_error].filter(Boolean).map(value=>`<small title="${escapeHtml(value)}">${escapeHtml(value)}</small>`).join('');
      const selectable=row.status!==3||row.label_ready;
      return `<tr><td><input type="checkbox" data-temu-order-select="${escapeHtml(row.id)}" aria-label="${escapeHtml(row.id)} kijelölése" ${selectable?'':'disabled'}></td><td><strong>${formatDate(row.updated_at)}</strong><small class="order-id">${escapeHtml(row.id)}</small></td><td><strong>${escapeHtml(products||'Temu termék')}</strong></td><td><strong>${formatNumber(row.item_count)} db</strong></td><td><span class="badge ${[2,4,5,41,51].includes(row.status)?'good':'neutral'}">${escapeHtml(row.status_label)}</span></td><td>${temuShipmentStatus(row)}</td><td>${temuInvoiceStatus(row)}${numbers?`<small>${escapeHtml(numbers)}</small>`:''}</td><td><div class="order-action">${shipmentAction}${invoiceAction}${error}</div></td></tr>`;
    }).join('');
    $('#selectAllTemuOrders').checked=false;updateTemuBulkActions();
  }catch(error){temuOrders=[];$('#temuOrderRows').innerHTML='';$('#temuOrderEmpty').classList.remove('hidden');updateTemuBulkActions();toast(error.message,'error')}finally{refresh.disabled=false}
}
function selectedTemuOrderIds(){return $$('[data-temu-order-select]:checked').map(input=>input.dataset.temuOrderSelect)}
function updateTemuBulkActions(){
  const selected=selectedTemuOrderIds();const selectedRows=selected.map(id=>temuOrders.find(row=>row.id===id)).filter(Boolean);
  $('#temuSelectedCount').textContent=selected.length;$('#bulkCreateTemuShipments').disabled=!selected.length;
  $('#printTemuLabels').disabled=!selected.length||selectedRows.some(row=>!row.label_ready);
  const enabled=$$('[data-temu-order-select]:not(:disabled)');$('#selectAllTemuOrders').checked=enabled.length>0&&enabled.every(input=>input.checked);$('#selectAllTemuOrders').indeterminate=selected.length>0&&!$('#selectAllTemuOrders').checked;
}
function toggleAllTemuOrders(checked){$$('[data-temu-order-select]:not(:disabled)').forEach(input=>{input.checked=checked});updateTemuBulkActions()}
async function bulkCreateTemuShipments(){
  const orderIds=selectedTemuOrderIds();if(!orderIds.length)return;
  if(!confirm(`${orderIds.length} Temu-rendeléshez készítünk Express One címkét és visszaírjuk a csomagszámokat. Folytatod?`))return;
  const button=$('#bulkCreateTemuShipments');const original=button.textContent;button.disabled=true;button.textContent='Tömeges feladás…';
  try{const data=await api('/api/temu/shipments/bulk',{method:'POST',body:JSON.stringify({order_ids:orderIds,weight_kg:$('#temuBulkWeight').value,confirmation:$('#temuBulkConfirmation').value})});const firstError=(data.results||[]).find(row=>!row.ok);toast(`${data.success_count}/${data.total} rendelés feladva.${firstError?` Első hiba: ${firstError.error}`:''}`,data.error_count?'error':'success');$('#temuBulkConfirmation').value='';await loadTemuOrders();loadDashboard()}catch(error){toast(error.message,'error')}finally{button.disabled=false;button.textContent=original;updateTemuBulkActions()}
}
function printSelectedTemuLabels(){
  const orderIds=selectedTemuOrderIds();if(!orderIds.length)return;const params=new URLSearchParams();orderIds.forEach(id=>params.append('order_id',id));window.open(`/api/temu/shipments/labels.pdf?${params.toString()}`,'_blank','noopener');
}
async function previewTemuShipment(orderId){
  try{
    const weight=$('#temuShipmentWeight').value||'';const data=await api(`/api/temu/orders/${encodeURIComponent(orderId)}/shipment-preview?weight_kg=${encodeURIComponent(weight)}`);
    selectedTemuShipmentOrder=orderId;$('#temuShipmentPreviewTitle').textContent=`${orderId} · Express One`;
    const recipient=data.recipient||{};const existing=data.existing||{};
    $('#temuShipmentDetails').innerHTML=`<div><b>01</b><span><strong>${escapeHtml(recipient.name||'—')}</strong><small>${escapeHtml(recipient.post_code||'')} ${escapeHtml(recipient.city||'')}, ${escapeHtml(recipient.street||'')}</small></span></div><div><b>02</b><span><strong>${formatNumber(data.item_count)} termék · ${escapeHtml(data.weight_kg)} kg</strong><small>Express One 24H · Temu carrier ID: ${escapeHtml(data.carrier_id)}</small></span></div>${existing.parcel_number?`<div><b>03</b><span><strong>Meglévő csomagszám: ${escapeHtml(existing.parcel_number)}</strong><small>Újrapróbáláskor nem készül új címke.</small></span></div>`:''}`;
    $('#temuShipmentWeight').value=data.weight_kg;$('#temuShipmentConfirmation').value='';
    const button=$('#createTemuShipment');button.dataset.orderId=orderId;button.textContent=existing.parcel_number?'Temu-visszaírás újrapróbálása':'Címke létrehozása és feladás';
    $('#temuShipmentPreview').classList.remove('hidden');$('#temuShipmentPreview').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(error){toast(error.message,'error')}
}
async function createTemuShipment(){
  const button=$('#createTemuShipment');const orderId=button.dataset.orderId||selectedTemuShipmentOrder;if(!orderId)return;
  if(!confirm('Ez éles Express One címkét készít, majd feladottnak jelöli a rendelést a Temun. Folytatod?'))return;
  const original=button.textContent;button.disabled=true;button.textContent='Címke készítése és feladás…';
  try{const data=await api(`/api/temu/orders/${encodeURIComponent(orderId)}/shipment`,{method:'POST',body:JSON.stringify({weight_kg:$('#temuShipmentWeight').value,confirmation:$('#temuShipmentConfirmation').value})});toast(`Feladva. Express One csomagszám: ${data.parcel_number}`,'success');$('#temuShipmentPreview').classList.add('hidden');await loadTemuOrders();loadDashboard()}catch(error){toast(error.message,'error');await loadTemuOrders()}finally{button.disabled=false;button.textContent=original}
}
function findTrackingText(value){if(!value)return'';if(Array.isArray(value)){for(const item of value){const found=findTrackingText(item);if(found)return found}}else if(typeof value==='object'){for(const key of ['event_name','eventName','state','status','description'])if(value[key])return String(value[key]);for(const item of Object.values(value)){const found=findTrackingText(item);if(found)return found}}return''}
async function refreshTemuTracking(orderId,button){button.disabled=true;try{const data=await api(`/api/temu/orders/${encodeURIComponent(orderId)}/tracking`,{method:'POST',body:'{}'});toast(`${data.parcel_number}: ${findTrackingText(data.tracking)||'az állapot lekérve'}`,'success')}catch(error){toast(error.message,'error')}finally{button.disabled=false}}
async function previewTemuInvoices(orderId){
  try{
    const data=await api(`/api/temu/orders/${encodeURIComponent(orderId)}/invoice-preview`);
    selectedTemuInvoiceOrder=orderId;$('#temuInvoicePreviewTitle').textContent=`${orderId} számlái`;
    const documents=data.documents||[];
    $('#temuInvoiceDocuments').innerHTML=documents.map((doc,index)=>{
      const buyer=doc.buyer||{};const items=(doc.items||[]).map(item=>`${escapeHtml(item.name)} · ${escapeHtml(item.gross)} ${escapeHtml(doc.currency)}`).join('<br>');
      const problems=(doc.problems||[]).length?`<small class="problem-list">${doc.problems.map(escapeHtml).join('<br>')}</small>`:'<small>Az API-adatok teljesek, kiállítható.</small>';
      const state=doc.status==='uploaded'?' · már feltöltve':doc.invoice_number?` · ${escapeHtml(doc.invoice_number)}`:'';
      const apiAddress=buyer.api_address?`<small><strong>Temu API-cím:</strong> ${escapeHtml(buyer.api_address)}</small>${buyer.api_address_approved?'<small class="badge good">Cím jóváhagyva</small>':`<button class="secondary" data-approve-temu-platform="${escapeHtml(orderId)}">API-cím ellenőrizve, jóváhagyom</button>`}`:'';
      return `<div><b>${String(index+1).padStart(2,'0')}</b><span><strong>${escapeHtml(doc.recipient_label)} · ${escapeHtml(doc.total)} ${escapeHtml(doc.currency)}${state}</strong><small>${escapeHtml(buyer.name||'—')} · ${escapeHtml(buyer.email||'nincs e-mail')}</small>${apiAddress}${items?`<small>${items}</small>`:''}${problems}</span></div>`;
    }).join('');
    const create=$('#createTemuInvoices');create.disabled=!documents.length||documents.some(doc=>!doc.ready)||documents.every(doc=>doc.status==='uploaded');create.dataset.orderId=orderId;
    $('#temuInvoicePreview').classList.remove('hidden');$('#temuInvoicePreview').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(error){toast(error.message,'error')}
}
async function approveTemuPlatformAddress(orderId,button){
  if(!confirm('Ellenőrizted, hogy a Temu API által küldött platformcím megegyezik a szerződéses számlázási címmel?'))return;
  button.disabled=true;
  try{await api(`/api/temu/orders/${encodeURIComponent(orderId)}/platform-address/approve`,{method:'POST',body:'{}'});toast('A Temu platformcímét elmentettem és jóváhagytam.','success');await previewTemuInvoices(orderId)}catch(error){toast(error.message,'error')}finally{button.disabled=false}
}
async function createTemuInvoices(){
  const button=$('#createTemuInvoices');const orderId=button.dataset.orderId||selectedTemuInvoiceOrder;if(!orderId)return;
  if(!confirm('A Számlázz.hu éles számlát vagy számlákat állít ki, majd a PDF-eket feltölti a Temu rendeléshez. Folytatod?'))return;
  const original=button.textContent;button.disabled=true;button.textContent='Számlázás és feltöltés…';
  try{const data=await api(`/api/temu/orders/${encodeURIComponent(orderId)}/invoices`,{method:'POST',body:'{}'});toast(`${(data.invoices||[]).length} Temu-számla elkészült és feltöltve.`,'success');await loadTemuOrders();await previewTemuInvoices(orderId);loadDashboard()}catch(error){toast(error.message,'error');await previewTemuInvoices(orderId)}finally{button.textContent=original}
}

async function loadSettings(){
  try{const s=await api('/api/settings');const f=$('#settingsForm');['environment','client_id','user_agent','language','temu_endpoint','temu_app_key','invoice_driver','invoice_prefix','temu_invoice_prefix','temu_invoice_public_base_url','temu_platform_name','temu_platform_country','temu_platform_zip','temu_platform_city','temu_platform_street','temu_platform_tax_id','temu_platform_email','express_one_endpoint','express_one_company_id','express_one_user_name','express_one_default_weight_kg','temu_express_one_carrier_id'].forEach(k=>{if(f.elements[k])f.elements[k].value=s[k]||''});f.elements.invoice_email_fallback.value=String(Boolean(s.invoice_email_fallback));$('#secretHint').textContent=s.client_secret_set?'Van elmentett titkos kulcs.':'Még nincs elmentett titkos kulcs.';$('#temuSecretHint').textContent=s.temu_app_secret_set?'Van elmentett App Secret.':'Még nincs elmentett App Secret.';$('#temuTokenHint').textContent=s.temu_access_token_set?'Van elmentett Access Token.':'Még nincs elmentett Access Token.';$('#agentHint').textContent=s.szamlazz_agent_key_set?'Van elmentett Agent kulcs.':'Még nincs elmentett Agent kulcs.';$('#expressOnePasswordHint').textContent=s.express_one_password_set?'Van elmentett Express One jelszó.':'Még nincs elmentett Express One jelszó.'}catch(error){toast(error.message,'error')}
}
async function saveSettings(event){
  event.preventDefault();const form=event.currentTarget;const f=new FormData(form);const body=Object.fromEntries(f.entries());
  try{await api('/api/settings',{method:'PUT',body:JSON.stringify(body)});form.elements.client_secret.value='';form.elements.temu_app_secret.value='';form.elements.temu_access_token.value='';form.elements.szamlazz_agent_key.value='';form.elements.express_one_password.value='';toast('A beállításokat elmentettem.','success');await loadSettings();await loadDashboard()}catch(error){toast(error.message,'error')}
}
async function loadConnectionState(){
  try{const [d,s]=await Promise.all([api('/api/dashboard'),api('/api/settings')]);const c=d.connection;$('#connectionEnvironment').textContent=c.environment==='production'?'Éles':'Sandbox';$('#connectionApp').textContent=c.problems.length?'Beállítás szükséges':'Beállítva';$('#connectionUser').textContent=c.user_connected?'Csatlakoztatva':'Nincs csatlakoztatva';$('#allegroBadge').textContent=c.user_connected?'Csatlakoztatva':c.problems.length?'Nincs beállítva':'Beállítva';$('#allegroBadge').className=`badge ${c.user_connected?'good':c.problems.length?'bad':'neutral'}`;$('#temuAppState').textContent=s.temu_app_key?'Megadva':'Nincs megadva';$('#temuTokenState').textContent=s.temu_access_token_set?'Megadva':'Nincs megadva';$('#temuBadge').textContent=s.temu_ready?'Beállítva':'Nincs beállítva';$('#temuBadge').className=`badge ${s.temu_ready?'good':'neutral'}`;$('#expressOneCompanyState').textContent=s.express_one_company_id?'Megadva':'Nincs megadva';$('#expressOneUserState').textContent=s.express_one_user_name?'Megadva':'Nincs megadva';$('#expressOneBadge').textContent=s.express_one_ready?'Beállítva':'Nincs beállítva';$('#expressOneBadge').className=`badge ${s.express_one_ready?'good':'neutral'}`;$('#invoiceBadge').textContent=s.invoice_ready?'Működésre kész':s.invoice_driver==='szamlazz'?'Agent kulcs hiányzik':'Kikapcsolva';$('#invoiceBadge').className=`badge ${s.invoice_ready?'good':s.invoice_driver==='szamlazz'?'bad':'neutral'}`;const login=$('#startLogin');login.disabled=false;login.title=c.problems.join(' ')}catch(error){toast(error.message,'error')}
}
async function checkConnection(){const b=$('#checkConnection');b.disabled=true;b.textContent='Ellenőrzés…';try{const data=await api('/api/auth/check',{method:'POST',body:'{}'});toast(`Sikeres Allegro-kapcsolat (${data.environment}).`,'success');$('#connectionApp').textContent='Ellenőrizve';$('#startLogin').disabled=false;await loadDashboard()}catch(error){toast(error.message,'error')}finally{b.disabled=false;b.textContent='Alkalmazás tesztelése'}}
async function checkTemuConnection(){const b=$('#checkTemuConnection');b.disabled=true;b.textContent='Ellenőrzés…';try{await api('/api/temu/check',{method:'POST',body:'{}'});toast('Sikeres Temu Open Platform kapcsolat.','success');$('#temuBadge').textContent='Kapcsolódva';$('#temuBadge').className='badge good';await loadDashboard()}catch(error){toast(error.message,'error')}finally{b.disabled=false;b.textContent='Temu-kapcsolat tesztelése'}}
async function checkExpressOneConnection(){const b=$('#checkExpressOneConnection');b.disabled=true;b.textContent='Ellenőrzés…';try{await api('/api/express-one/check',{method:'POST',body:'{}'});toast('Sikeres Express One API-kapcsolat.','success');$('#expressOneBadge').textContent='Kapcsolódva';$('#expressOneBadge').className='badge good'}catch(error){toast(error.message,'error')}finally{b.disabled=false;b.textContent='Express One tesztelése'}}
async function startLogin(){
  if(deviceTimer)clearInterval(deviceTimer);try{const data=await api('/api/auth/device/start',{method:'POST',body:'{}'});$('#deviceLogin').classList.remove('hidden');$('#deviceCode').textContent=data.user_code;const link=$('#deviceLink');link.href=data.verification_uri_complete||data.verification_uri;$('#deviceStatus').textContent='Várakozás a jóváhagyásra…';deviceTimer=setInterval(()=>pollLogin(data.device_code),Math.max(4,data.interval)*1000)}catch(error){toast(error.message,'error')}
}
async function pollLogin(code){try{const data=await api('/api/auth/device/poll',{method:'POST',body:JSON.stringify({device_code:code})});if(data.status==='authorized'){clearInterval(deviceTimer);deviceTimer=null;$('#deviceStatus').textContent='Sikeresen csatlakoztatva.';toast('Az eladói fiók csatlakoztatva.','success');loadConnectionState();loadDashboard()}}catch(error){clearInterval(deviceTimer);deviceTimer=null;$('#deviceStatus').textContent=error.message;toast(error.message,'error')}}

document.addEventListener('click',event=>{const go=event.target.closest('[data-go]');if(go)navigate(go.dataset.go);const nav=event.target.closest('[data-view]');if(nav)navigate(nav.dataset.view);const category=event.target.closest('[data-category-id]');if(category){activeTemplate=null;$('#offerTemplate').value='';$('#templateName').value='';inspectCategory(category.dataset.categoryId,null)}const invoice=event.target.closest('[data-invoice-order]');if(invoice)createInvoice(invoice.dataset.invoiceOrder,invoice);const temuRefresh=event.target.closest('[data-temu-refresh]');if(temuRefresh)refreshTemuUpload(temuRefresh.dataset.temuRefresh)});
document.addEventListener('change',event=>{const dynamic=event.target.closest('[data-dynamic-param]');if(dynamic){const field=$$('[data-parameter]',$('#parameterFields')).find(item=>item.dataset.parameter===dynamic.dataset.dynamicParam);if(field&&dynamic.checked)field.value=field.dataset.suggested||'';dynamic.closest('.parameter-field').classList.toggle('dynamic',dynamic.checked)}if(dynamic||event.target.closest('[data-parameter]'))refreshConditionalParameters();if(event.target.closest('[data-temu-order-select]'))updateTemuBulkActions()});
document.addEventListener('click',event=>{const preview=event.target.closest('[data-temu-invoice-preview]');if(preview)previewTemuInvoices(preview.dataset.temuInvoicePreview);const approve=event.target.closest('[data-approve-temu-platform]');if(approve)approveTemuPlatformAddress(approve.dataset.approveTemuPlatform,approve);const shipment=event.target.closest('[data-temu-shipment-preview]');if(shipment)previewTemuShipment(shipment.dataset.temuShipmentPreview);const tracking=event.target.closest('[data-temu-tracking]');if(tracking)refreshTemuTracking(tracking.dataset.temuTracking,tracking)});
$$('.nav-item').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.view)));
$('#mobileMenu').addEventListener('click',()=>$('#sidebar').classList.toggle('open'));
$('#platformSelect').addEventListener('change',event=>setPlatform(event.target.value));
$('#temuProductFamily').addEventListener('change',renderTemuV3VariantRows);$('#previewTemuSelection').addEventListener('click',previewTemuV3Selection);$('#createTemuProduct').addEventListener('click',createTemuV3Product);$('#refreshTemuUploads').addEventListener('click',loadTemuUploads);
$('#refreshDashboard').addEventListener('click',loadDashboard);
let searchTimer;$('#productSearch').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(loadProducts,250)});
$('#csvFile').addEventListener('change',event=>previewFile(event.target.files[0]));
const dz=$('#dropzone');['dragenter','dragover'].forEach(name=>dz.addEventListener(name,event=>{event.preventDefault();dz.classList.add('drag')}));['dragleave','drop'].forEach(name=>dz.addEventListener(name,event=>{event.preventDefault();dz.classList.remove('drag')}));dz.addEventListener('drop',event=>previewFile(event.dataTransfer.files[0]));
$('#useSample').addEventListener('click',async()=>{try{const response=await fetch('/sample.csv');if(!response.ok)throw new Error('A mintafájl nem érhető el.');const blob=await response.blob();previewFile(new File([blob],'export-minta.csv',{type:'text/csv'}))}catch(error){toast(error.message,'error')}});
$('#commitImport').addEventListener('click',commitImport);$('#settingsForm').addEventListener('submit',saveSettings);$('#checkConnection').addEventListener('click',checkConnection);$('#checkTemuConnection').addEventListener('click',checkTemuConnection);$('#checkExpressOneConnection').addEventListener('click',checkExpressOneConnection);$('#startLogin').addEventListener('click',startLogin);
$('#searchCategories').addEventListener('click',searchCategories);$('#categoryPhrase').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();searchCategories()}});$('#offerProduct').addEventListener('change',()=>{syncOfferPrice();if(selectedCategory)inspectCategory(selectedCategory.id,activeTemplate)});$('#priceFromProduct').addEventListener('change',()=>{if($('#priceFromProduct').checked)syncOfferPrice()});$('#stockFromProduct').addEventListener('change',()=>{if($('#stockFromProduct').checked)syncOfferPrice()});$('#applyTemplate').addEventListener('click',applySelectedTemplate);$('#saveTemplate').addEventListener('click',saveTemplate);$('#deleteTemplate').addEventListener('click',deleteTemplate);$('#previewOffer').addEventListener('click',previewOffer);$('#createOffer').addEventListener('click',createOffer);
$('#bulkImportBatch').addEventListener('change',loadBulkImportBatch);$('#previewBulkOffers').addEventListener('click',previewBulkOffers);$('#createBulkOffers').addEventListener('click',createBulkOffers);
$('#preorder').addEventListener('change',togglePreorder);$('#responsibleProducer').addEventListener('change',updateProducerHint);
$('#refreshOrders').addEventListener('click',loadOrders);
$('#refreshTemuOrders').addEventListener('click',loadTemuOrders);$('#createTemuInvoices').addEventListener('click',createTemuInvoices);$('#createTemuShipment').addEventListener('click',createTemuShipment);
$('#selectAllTemuOrders').addEventListener('change',event=>toggleAllTemuOrders(event.target.checked));$('#bulkCreateTemuShipments').addEventListener('click',bulkCreateTemuShipments);$('#printTemuLabels').addEventListener('click',printSelectedTemuLabels);
setPlatform(activePlatform,false);navigate(location.hash.slice(1)||'dashboard');
