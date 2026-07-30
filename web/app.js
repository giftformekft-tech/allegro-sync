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
let temuProducts = [];
let temuCategoryHistory = [];
let temuSelectedCategory = null;
let temuCategoryTemplate = null;
let temuVariantGroups = [];

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
      ['Temu termékfeltöltés','A pólóvariánsok feltöltési modulja a következő fejlesztési lépés.','upload']
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
    const q=encodeURIComponent($('#productSearch').value.trim()); const data=await api(`/api/products?q=${q}`); const rows=data.products;
    $('#productResultCount').textContent=`${rows.length} találat`; $('#navProductCount').textContent=rows.length;
    $('#productEmpty').classList.toggle('hidden',rows.length>0);
    $('#productRows').innerHTML=rows.map(row=>`<tr><td><div class="product-cell">${row.image_url?`<img class="product-thumb" src="${escapeHtml(row.image_url)}" alt="" loading="lazy">`:'<div class="product-thumb"></div>'}<div><strong>${escapeHtml(row.title)}</strong><small>${escapeHtml(row.name)}</small></div></div></td><td><strong>${escapeHtml(row.sku)}</strong><small>${escapeHtml(row.parent_sku)}</small></td><td>${escapeHtml(row.color)} · ${escapeHtml(row.size)}</td><td><strong>${formatNumber(Number(row.price_huf))} Ft</strong></td><td>${formatNumber(row.stock)}</td><td><span class="badge ${row.status==='inactive'?'good':'neutral'}">${row.status==='inactive'?'Inaktív az Allegrón':'Piszkozat'}</span>${row.allegro_offer_id?`<small>${escapeHtml(row.allegro_offer_id)}</small>`:''}</td></tr>`).join('');
  }catch(error){toast(error.message,'error')}
}

function categoryTrail(item){const names=[];let current=item;while(current){if(current.name)names.unshift(current.name);current=current.parent}return names.join(' / ')}
function temuPropertyValues(property){return (property.values||[]).slice(0,1000).map(value=>`<option value="${escapeHtml(value.spec_id||value.vid)}" data-vid="${escapeHtml(value.vid)}" data-spec-id="${escapeHtml(value.spec_id)}">${escapeHtml(value.value)}${value.group?` · ${escapeHtml(value.group)}`:''}</option>`).join('')}
function selectedTemuFamilyProducts(){const key=$('#temuProductFamily').value;return temuProducts.filter(product=>(product.parent_sku||product.name)===key)}
function temuSourceValues(property,products){const name=String(property.name||'').toLocaleLowerCase('en');const field=name.includes('color')||name.includes('colour')||name.includes('szín')?'color':name.includes('size')||name.includes('méret')?'size':null;return field?[...new Set(products.map(product=>String(product[field]||'').trim()).filter(Boolean))]:['Minden kiválasztott variáns']}
function renderTemuProductFamilies(){
  const groups=new Map();temuProducts.forEach(product=>{const key=product.parent_sku||product.name;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(product)});
  $('#temuProductFamily').innerHTML='<option value="">Válassz importált termékcsaládot…</option>'+[...groups.entries()].map(([key,products])=>{const types=[...new Set(products.map(item=>item.type).filter(Boolean))].join(', ');return `<option value="${escapeHtml(key)}">${escapeHtml(products[0].name)} · ${escapeHtml(types)} · ${products.length} változat</option>`}).join('');
}
function renderTemuVariantRows(){
  const products=selectedTemuFamilyProducts();const rows=new Map();products.forEach(product=>{const key=`${product.type}\u0000${product.color}`;if(!rows.has(key))rows.set(key,[]);rows.get(key).push(product)});temuVariantGroups=[...rows.values()];
  $('#temuVariantRows').innerHTML=temuVariantGroups.length?temuVariantGroups.map((group,index)=>{const first=group[0];const sizes=[...new Set(group.map(item=>item.size).filter(Boolean))];const stock=group.reduce((sum,item)=>sum+Number(item.stock||0),0);return `<label class="temu-variant-row"><input type="checkbox" data-temu-row-index="${index}" checked>${first.image_url?`<img src="${escapeHtml(first.image_url)}" alt="" loading="lazy">`:'<span class="temu-variant-image"></span>'}<span><strong>${escapeHtml(first.type||'Termék')}</strong><small>${escapeHtml(first.color||'Nincs szín')}</small></span><span class="temu-size-chips">${sizes.map(size=>`<span>${escapeHtml(size)}</span>`).join('')}</span><span class="temu-variant-stock">${formatNumber(stock)} db</span></label>`}).join(''):'<div class="wizard-empty">Ehhez a termékcsaládhoz nincs importált variáns.</div>';
  renderTemuMappings();
}
function renderTemuMappings(){
  if(!temuCategoryTemplate)return;const products=selectedTemuFamilyProducts();const sales=temuCategoryTemplate.sales_properties||[];
  $('#temuSaleMappings').innerHTML=sales.length?sales.map(property=>{const sources=temuSourceValues(property,products);return `<div class="temu-mapping-group" data-temu-sale-property="${escapeHtml(property.template_pid||property.pid)}"><strong>${escapeHtml(property.name)}${property.required?' *':''}</strong>${sources.map(source=>`<label class="temu-mapping-row"><span>${escapeHtml(source)}</span><select data-temu-source="${escapeHtml(source)}"><option value="">Válassz Temu-értéket…</option>${temuPropertyValues(property)}</select></label>`).join('')}</div>`}).join(''):'<div class="temu-empty-property">A kategória nem adott vissza külön variánsparamétert.</div>';
  const required=(temuCategoryTemplate.properties||[]).filter(property=>property.required||property.show_type===1);
  $('#temuRequiredProperties').innerHTML=required.length?required.map(temuNormalPropertyField).join(''):'<div class="temu-empty-property">Nincs további kötelező termékadat ebben a kategóriában.</div>';refreshTemuConditionalProperties();
}
function temuNormalPropertyField(property){
  const id=property.template_pid||property.pid;const multiple=property.choose_max_num>1;let field;
  if(property.values?.length)field=`<select data-temu-field ${multiple?'multiple size="4"':''}><option value="">${multiple?'Több érték is választható':'Válassz…'}</option>${temuPropertyValues(property)}</select>`;
  else{const bounds=[property.min_value&&`min. ${property.min_value}`,property.max_value&&`max. ${property.max_value}`].filter(Boolean).join(' · ');field=`<div class="temu-input-unit"><input data-temu-field placeholder="${bounds||'Add meg a Temu által kért értéket'}">${property.value_units?.length?`<select data-temu-unit>${property.value_units.map(unit=>`<option value="${escapeHtml(unit.id)}">${escapeHtml(unit.name)}</option>`).join('')}</select>`:''}</div>`}
  return `<label class="temu-mapping-group" data-temu-property="${escapeHtml(id)}" data-temu-property-index="${temuCategoryTemplate.properties.indexOf(property)}"><strong>${escapeHtml(property.name)}${property.required?' *':' · feltételes'}</strong>${field}</label>`;
}
function temuPropertyVisible(property){
  const condition=property.show_condition||{};const parentRef=String(condition.parentRefPid??condition.parent_ref_pid??'');const parentVids=(condition.parentVids||condition.parent_vids||[]).map(String);if(!parentRef||!parentVids.length)return true;
  const parent=(temuCategoryTemplate.properties||[]).find(item=>String(item.ref_pid)===parentRef);if(!parent)return true;const group=$(`[data-temu-property="${parent.template_pid||parent.pid}"]`);if(!group)return true;const field=group.querySelector('[data-temu-field]');if(!field)return true;const selected=field.tagName==='SELECT'?[...field.selectedOptions].map(option=>String(option.dataset.vid||'')):[String(field.value||'')];return selected.some(value=>parentVids.includes(value));
}
function refreshTemuConditionalProperties(){$$('[data-temu-property]').forEach(group=>{const property=temuCategoryTemplate?.properties?.[Number(group.dataset.temuPropertyIndex)];if(property)group.classList.toggle('hidden',!temuPropertyVisible(property))})}
async function loadTemuCategories(parentId=0){
  const results=$('#temuCategoryResults');results.innerHTML='<div class="wizard-empty">A Temu kategóriák betöltése…</div>';
  $('#temuBreadcrumb').textContent=['Főkategóriák',...temuCategoryHistory.map(item=>item.name)].join(' / ');
  try{const data=await api(`/api/temu/categories?parent_id=${encodeURIComponent(parentId)}`);results.innerHTML=data.categories.length?data.categories.map(category=>`<div class="category-result"><div><strong>${escapeHtml(category.name)}</strong><small>${category.leaf?'Végső kategória':`${category.level}. szint · további kategóriák`}</small></div><button class="secondary" data-temu-category-id="${escapeHtml(category.id)}" data-temu-category-name="${escapeHtml(category.name)}" data-temu-category-leaf="${category.leaf?'true':'false'}">${category.leaf?'Kiválasztás':'Megnyitás'}</button></div>`).join(''):'<div class="wizard-empty">Ebben az ágban nincs további kategória.</div>'}catch(error){results.innerHTML=`<div class="wizard-empty">${escapeHtml(error.message)}<br><button class="secondary" data-go="settings">Temu-beállítások megnyitása</button></div>`;toast(error.message,'error')}
}
async function inspectTemuCategory(category){
  try{const data=await api(`/api/temu/categories/${encodeURIComponent(category.id)}/template`);temuSelectedCategory=category;temuCategoryTemplate=data.template;$('#temuCategoryName').textContent=category.name;const required=data.template.properties.filter(item=>item.required).length;$('#temuTemplateSummary').textContent=`${data.template.sales_properties.length} variánsparaméter · ${required} kötelező termékadat · legfeljebb ${data.template.single_spec_value_num||'—'} variánsérték`;$('#temuTemplateInspector').classList.remove('hidden');renderTemuMappings();$('#temuTemplateInspector').scrollIntoView({behavior:'smooth',block:'start'});toast('A Temu kategóriaséma betöltve.','success')}catch(error){toast(error.message,'error')}
}
async function loadTemuUpload(){
  try{const [products,settings]=await Promise.all([api('/api/products'),api('/api/settings')]);temuProducts=products.products;renderTemuProductFamilies();if(!settings.temu_ready){$('#temuCategoryResults').innerHTML='<div class="wizard-empty">Előbb add meg az App Key, App Secret és Access Token értékét.<br><button class="secondary" data-go="settings">Temu-beállítások megnyitása</button></div>';return}if(!temuCategoryHistory.length&&!temuSelectedCategory)await loadTemuCategories(0)}catch(error){toast(error.message,'error')}
}
function previewTemuSelection(){
  if(!temuSelectedCategory||!temuCategoryTemplate){toast('Előbb válassz végső Temu-kategóriát.','error');return}const family=$('#temuProductFamily').value;if(!family){toast('Válassz importált termékcsaládot.','error');return}
  const selectedGroups=temuVariantGroups.filter((_group,index)=>$(`[data-temu-row-index="${index}"]`)?.checked);if(!selectedGroups.length){toast('Legalább egy teljes variánssort válassz ki.','error');return}
  const saleMappings=$$('[data-temu-sale-property]').map(group=>({property_id:group.dataset.temuSaleProperty,name:group.querySelector('strong').textContent.replace(' *',''),values:$$('select',group).map(select=>({source:select.dataset.temuSource,value:select.selectedOptions[0]?.textContent||'',spec_id:select.selectedOptions[0]?.dataset.specId||'',vid:select.selectedOptions[0]?.dataset.vid||''}))}));
  const missingSale=saleMappings.flatMap(item=>item.values).some(item=>!item.spec_id&&!item.vid);const properties=$$('[data-temu-property]').filter(group=>!group.classList.contains('hidden')).map(group=>{const field=group.querySelector('[data-temu-field]');const options=field.tagName==='SELECT'?[...field.selectedOptions].filter(option=>option.value):[];const unit=group.querySelector('[data-temu-unit]');return{property_id:group.dataset.temuProperty,name:group.querySelector('strong').textContent.replace(' *','').replace(' · feltételes',''),values:options.length?options.map(option=>({value:option.textContent,vid:option.dataset.vid||''})):[{value:field.value,vid:''}],unit:unit?{id:unit.value,name:unit.selectedOptions[0]?.textContent||''}:null}});if(missingSale||properties.some(item=>item.values.some(value=>!value.value||value.value==='Válassz…'))){toast('Töltsd ki az összes kötelező Temu-megfeleltetést.','error');return}
  const plan={api_method:'bg.local.goods.add',ready_to_publish:false,category:{id:temuSelectedCategory.id,name:temuSelectedCategory.name},family,variant_rows:selectedGroups.map(group=>({type:group[0].type,color:group[0].color,sizes:group.map(item=>item.size),skus:group.map(item=>item.sku),stock:group.reduce((sum,item)=>sum+Number(item.stock||0),0)})),sale_mappings:saleMappings,properties};$('#temuSelectionPayload').textContent=JSON.stringify(plan,null,2);$('#temuSelectionWrap').classList.remove('hidden');toast('A Temu feltöltési terv elkészült; még nem küldtünk adatot.','success');
}
async function loadUpload(){
  if(activePlatform==='temu'){loadTemuUpload();return}
  try{
    const [products,settings,templates]=await Promise.all([api('/api/products'),api('/api/settings'),api('/api/templates')]);uploadProducts=products.products;uploadTemplates=templates.templates;
    const select=$('#offerProduct');const previous=select.value;select.innerHTML='<option value="">Válassz importált terméket…</option>'+uploadProducts.map(p=>`<option value="${p.id}">${escapeHtml(p.title)} · ${escapeHtml(p.sku)}</option>`).join('');if(previous)select.value=previous;
    renderTemplateOptions(activeTemplate?.id);
    $('#uploadEnvironment').textContent=settings.environment==='production'?'ÉLES':'SANDBOX';$('#uploadEnvironment').classList.toggle('production',settings.environment==='production');
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
  if(uploadMarketplace?.currency==='HUF'&&product)$('#offerPrice').value=product.price_huf||'';
  else if(!product)$('#offerPrice').value='';
  if($('#stockFromProduct').checked)$('#offerStock').value=product?.stock??'';
}
function renderTemplateOptions(selectedId=''){
  const select=$('#offerTemplate');select.innerHTML='<option value="">Válassz sablont…</option>'+uploadTemplates.map(template=>`<option value="${template.id}">${escapeHtml(template.name)} · ${escapeHtml(template.category_name)}</option>`).join('');if(selectedId)select.value=String(selectedId);
}
async function reloadTemplates(selectedId=''){
  const data=await api('/api/templates');uploadTemplates=data.templates;renderTemplateOptions(selectedId);
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
  $('#previewSummary').innerHTML=`<span>${s.total} sor</span><span class="ok">${s.valid} megfelelő</span><span class="bad">${s.invalid} hibás · ${s.errors} hiba</span>`;
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

async function loadSettings(){
  try{const s=await api('/api/settings');const f=$('#settingsForm');['environment','client_id','user_agent','language','temu_endpoint','temu_app_key','invoice_driver','invoice_prefix'].forEach(k=>{if(f.elements[k])f.elements[k].value=s[k]||''});f.elements.invoice_email_fallback.value=String(Boolean(s.invoice_email_fallback));$('#secretHint').textContent=s.client_secret_set?'Van elmentett titkos kulcs.':'Még nincs elmentett titkos kulcs.';$('#temuSecretHint').textContent=s.temu_app_secret_set?'Van elmentett App Secret.':'Még nincs elmentett App Secret.';$('#temuTokenHint').textContent=s.temu_access_token_set?'Van elmentett Access Token.':'Még nincs elmentett Access Token.';$('#agentHint').textContent=s.szamlazz_agent_key_set?'Van elmentett Agent kulcs.':'Még nincs elmentett Agent kulcs.'}catch(error){toast(error.message,'error')}
}
async function saveSettings(event){
  event.preventDefault();const form=event.currentTarget;const f=new FormData(form);const body=Object.fromEntries(f.entries());
  try{await api('/api/settings',{method:'PUT',body:JSON.stringify(body)});form.elements.client_secret.value='';form.elements.temu_app_secret.value='';form.elements.temu_access_token.value='';form.elements.szamlazz_agent_key.value='';toast('A beállításokat elmentettem.','success');await loadSettings();await loadDashboard()}catch(error){toast(error.message,'error')}
}
async function loadConnectionState(){
  try{const [d,s]=await Promise.all([api('/api/dashboard'),api('/api/settings')]);const c=d.connection;$('#connectionEnvironment').textContent=c.environment==='production'?'Éles':'Sandbox';$('#connectionApp').textContent=c.problems.length?'Beállítás szükséges':'Beállítva';$('#connectionUser').textContent=c.user_connected?'Csatlakoztatva':'Nincs csatlakoztatva';$('#allegroBadge').textContent=c.user_connected?'Csatlakoztatva':c.problems.length?'Nincs beállítva':'Beállítva';$('#allegroBadge').className=`badge ${c.user_connected?'good':c.problems.length?'bad':'neutral'}`;$('#temuAppState').textContent=s.temu_app_key?'Megadva':'Nincs megadva';$('#temuTokenState').textContent=s.temu_access_token_set?'Megadva':'Nincs megadva';$('#temuBadge').textContent=s.temu_ready?'Beállítva':'Nincs beállítva';$('#temuBadge').className=`badge ${s.temu_ready?'good':'neutral'}`;$('#invoiceBadge').textContent=s.invoice_ready?'Működésre kész':s.invoice_driver==='szamlazz'?'Agent kulcs hiányzik':'Kikapcsolva';$('#invoiceBadge').className=`badge ${s.invoice_ready?'good':s.invoice_driver==='szamlazz'?'bad':'neutral'}`;const login=$('#startLogin');login.disabled=false;login.title=c.problems.join(' ')}catch(error){toast(error.message,'error')}
}
async function checkConnection(){const b=$('#checkConnection');b.disabled=true;b.textContent='Ellenőrzés…';try{const data=await api('/api/auth/check',{method:'POST',body:'{}'});toast(`Sikeres Allegro-kapcsolat (${data.environment}).`,'success');$('#connectionApp').textContent='Ellenőrizve';$('#startLogin').disabled=false;await loadDashboard()}catch(error){toast(error.message,'error')}finally{b.disabled=false;b.textContent='Alkalmazás tesztelése'}}
async function checkTemuConnection(){const b=$('#checkTemuConnection');b.disabled=true;b.textContent='Ellenőrzés…';try{await api('/api/temu/check',{method:'POST',body:'{}'});toast('Sikeres Temu Open Platform kapcsolat.','success');$('#temuBadge').textContent='Kapcsolódva';$('#temuBadge').className='badge good';await loadDashboard()}catch(error){toast(error.message,'error')}finally{b.disabled=false;b.textContent='Temu-kapcsolat tesztelése'}}
async function startLogin(){
  if(deviceTimer)clearInterval(deviceTimer);try{const data=await api('/api/auth/device/start',{method:'POST',body:'{}'});$('#deviceLogin').classList.remove('hidden');$('#deviceCode').textContent=data.user_code;const link=$('#deviceLink');link.href=data.verification_uri_complete||data.verification_uri;$('#deviceStatus').textContent='Várakozás a jóváhagyásra…';deviceTimer=setInterval(()=>pollLogin(data.device_code),Math.max(4,data.interval)*1000)}catch(error){toast(error.message,'error')}
}
async function pollLogin(code){try{const data=await api('/api/auth/device/poll',{method:'POST',body:JSON.stringify({device_code:code})});if(data.status==='authorized'){clearInterval(deviceTimer);deviceTimer=null;$('#deviceStatus').textContent='Sikeresen csatlakoztatva.';toast('Az eladói fiók csatlakoztatva.','success');loadConnectionState();loadDashboard()}}catch(error){clearInterval(deviceTimer);deviceTimer=null;$('#deviceStatus').textContent=error.message;toast(error.message,'error')}}

document.addEventListener('click',event=>{const go=event.target.closest('[data-go]');if(go)navigate(go.dataset.go);const nav=event.target.closest('[data-view]');if(nav)navigate(nav.dataset.view);const category=event.target.closest('[data-category-id]');if(category){activeTemplate=null;$('#offerTemplate').value='';$('#templateName').value='';inspectCategory(category.dataset.categoryId,null)}const temuCategory=event.target.closest('[data-temu-category-id]');if(temuCategory){const item={id:temuCategory.dataset.temuCategoryId,name:temuCategory.dataset.temuCategoryName};if(temuCategory.dataset.temuCategoryLeaf==='true')inspectTemuCategory(item);else{temuCategoryHistory.push(item);temuSelectedCategory=null;temuCategoryTemplate=null;$('#temuTemplateInspector').classList.add('hidden');loadTemuCategories(Number(item.id))}}const invoice=event.target.closest('[data-invoice-order]');if(invoice)createInvoice(invoice.dataset.invoiceOrder,invoice)});
document.addEventListener('change',event=>{const dynamic=event.target.closest('[data-dynamic-param]');if(dynamic){const field=$$('[data-parameter]',$('#parameterFields')).find(item=>item.dataset.parameter===dynamic.dataset.dynamicParam);if(field&&dynamic.checked)field.value=field.dataset.suggested||'';dynamic.closest('.parameter-field').classList.toggle('dynamic',dynamic.checked)}if(dynamic||event.target.closest('[data-parameter]'))refreshConditionalParameters();if(event.target.closest('[data-temu-field]'))refreshTemuConditionalProperties()});
$$('.nav-item').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.view)));
$('#mobileMenu').addEventListener('click',()=>$('#sidebar').classList.toggle('open'));
$('#platformSelect').addEventListener('change',event=>setPlatform(event.target.value));
$('#temuCategoryRoot').addEventListener('click',()=>{temuCategoryHistory=[];temuSelectedCategory=null;temuCategoryTemplate=null;$('#temuTemplateInspector').classList.add('hidden');loadTemuCategories(0)});
$('#temuCategoryBack').addEventListener('click',()=>{temuCategoryHistory.pop();temuSelectedCategory=null;temuCategoryTemplate=null;$('#temuTemplateInspector').classList.add('hidden');loadTemuCategories(temuCategoryHistory.length?Number(temuCategoryHistory[temuCategoryHistory.length-1].id):0)});
$('#temuProductFamily').addEventListener('change',renderTemuVariantRows);$('#previewTemuSelection').addEventListener('click',previewTemuSelection);
$('#refreshDashboard').addEventListener('click',loadDashboard);
let searchTimer;$('#productSearch').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(loadProducts,250)});
$('#csvFile').addEventListener('change',event=>previewFile(event.target.files[0]));
const dz=$('#dropzone');['dragenter','dragover'].forEach(name=>dz.addEventListener(name,event=>{event.preventDefault();dz.classList.add('drag')}));['dragleave','drop'].forEach(name=>dz.addEventListener(name,event=>{event.preventDefault();dz.classList.remove('drag')}));dz.addEventListener('drop',event=>previewFile(event.dataTransfer.files[0]));
$('#useSample').addEventListener('click',async()=>{try{const response=await fetch('/sample.csv');if(!response.ok)throw new Error('A mintafájl nem érhető el.');const blob=await response.blob();previewFile(new File([blob],'export-minta.csv',{type:'text/csv'}))}catch(error){toast(error.message,'error')}});
$('#commitImport').addEventListener('click',commitImport);$('#settingsForm').addEventListener('submit',saveSettings);$('#checkConnection').addEventListener('click',checkConnection);$('#checkTemuConnection').addEventListener('click',checkTemuConnection);$('#startLogin').addEventListener('click',startLogin);
$('#searchCategories').addEventListener('click',searchCategories);$('#categoryPhrase').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();searchCategories()}});$('#offerProduct').addEventListener('change',()=>{syncOfferPrice();if(selectedCategory)inspectCategory(selectedCategory.id,activeTemplate)});$('#stockFromProduct').addEventListener('change',()=>{if($('#stockFromProduct').checked)syncOfferPrice()});$('#applyTemplate').addEventListener('click',applySelectedTemplate);$('#saveTemplate').addEventListener('click',saveTemplate);$('#deleteTemplate').addEventListener('click',deleteTemplate);$('#previewOffer').addEventListener('click',previewOffer);$('#createOffer').addEventListener('click',createOffer);
$('#preorder').addEventListener('change',togglePreorder);$('#responsibleProducer').addEventListener('change',updateProducerHint);
$('#refreshOrders').addEventListener('click',loadOrders);
setPlatform(activePlatform,false);navigate(location.hash.slice(1)||'dashboard');
