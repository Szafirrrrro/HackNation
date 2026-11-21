'use strict';
const icons={
 book:'<path d="M12 6c-3-2-6-2-9-1v14c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1zm0 0v14"/>',
 graph:'<rect x="3" y="3" width="6" height="6" rx="1.4"/><rect x="15" y="15" width="6" height="6" rx="1.4"/><rect x="3" y="15" width="6" height="6" rx="1.4"/><path d="M6 9v6m3-9h6a3 3 0 0 1 3 3v6"/>',
 flow:'<circle cx="5" cy="6" r="2.3"/><circle cx="19" cy="17" r="2.3"/><path d="M7.5 6H15a3 3 0 0 1 0 6H9a2.5 2.5 0 1 0 0 5h7.5"/>',
 data:'<ellipse cx="12" cy="5.5" rx="8" ry="3.5"/><path d="M4 5.5v12c0 4.6 16 4.6 16 0v-12M4 11c0 4.6 16 4.6 16 0"/>',
 layers:'<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
 matching:'<circle cx="5" cy="12" r="2.5"/><circle cx="18" cy="5" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="m7.2 10.8 8.5-4.5m-8.5 7 8.5 4.5"/>',
 ui:'<rect x="3" y="4" width="18" height="15" rx="2"/><path d="M3 9h18m-12 0v10"/>',
 teams:'<circle cx="9" cy="8" r="3"/><path d="M3 19v-2c0-5 12-5 12 0v2M16 5c4 0 4 6 0 6m2 3c2 0 3 2 3 4"/>',
 lab:'<path d="M9 3h6m-5 0v6L4 19a1.4 1.4 0 0 0 1.2 2h13.6a1.4 1.4 0 0 0 1.2-2L14 9V3M7 14h10"/>',
 validation:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7.5 12 3 3 6-7"/>',
 terminal:'<rect x="2.5" y="4" width="19" height="16" rx="2"/><path d="m6 9 3 3-3 3m6 0h5"/>',
 image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 3 4-6 5 7"/>',
 page:'<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8m-8 4h6"/>',
 code:'<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18"/>',
 search:'<circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6"/>',
 expand:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
 close:'<path d="m6 6 12 12M18 6 6 18"/>',menu:'<path d="M3 6h18M3 12h18M3 18h18"/>',
 list:'<path d="M8 6h13M8 12h13M8 18h13M3 6h1m-1 6h1m-1 6h1"/>'
};
const pages={
 overview:['Architektura systemu','Architektura','graph','Od pojedynczej emisji do hipotezy kampanii. Poznaj moduły ScamGraph, przepływ dowodów i odpowiedzialność każdej pary.'],
 flow:['Przepływ analizy','Architektura','flow','Prześledź drogę nowego materiału przez import, ekstrakcję, grupowanie i decyzję dla analityka.'],
 data:['Struktury danych','Architektura','data','Kontrakt v0, zapis strony i pochodzenie dowodu. Sprawdź, jak rekordy przechodzą między modułami.'],
 matching:['Silnik korelacji','Architektura','matching','Porównaj siłę i pokrycie dowodów. Sprawdź, kiedy complete-link scala emisje, a kiedy silnik wstrzymuje przypisanie.'],
 ui:['Graf i oś czasu','Architektura','ui','Wybierz post, połączenie lub zdarzenie. Tak zespół implementuje przejście od grupy do obu źródeł dowodu.'],
 teams:['Plan implementacji','Implementacja','teams','Zakres prac trzech par, punkty przekazania i warunki odbioru od pierwszego importu do demonstratora.'],
 lab:['Laboratorium modeli','Implementacja','lab','Instrukcja benchmarku CPU, pomiar jakości OCR i kryteria wyboru pojedynczego eksperymentu GPU.'],
 validation:['Testy i odbiór','Implementacja','validation','Sprawdź scenariusze regresji, pomiar na odłożonym zbiorze i pakiet do oceny według kryteriów NASK.'],
 onboarding:['Start w projekcie','Zespół','terminal','Pierwszy kwadrans z korpusem, zasady pracy w repozytorium i przewodniki źródłowe dla zespołu.']
};
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ico=n=>'<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'+(icons[n]||'')+'</svg>';
function paintIcons(el=document){el.querySelectorAll('i[data-icon]').forEach(i=>{i.outerHTML=ico(i.dataset.icon)})}
const diagramNodes=[
 {id:'ad',x:20,y:77,w:174,h:64,c:'#e8bf83',icon:'image',title:'Emisje reklam',sub:'Ad · obraz · tekst',to:'data',info:'ID emisji identyfikuje post. SHA-256 identyfikuje dokładną kopię pliku.'},
 {id:'web',x:20,y:184,w:174,h:64,c:'#e8bf83',icon:'page',title:'Zapisy stron',sub:'HTML · HAR · URL',to:'data',info:'Zapis strony pozostaje osobną obserwacją do czasu udokumentowania związku z emisją.'},
 {id:'import',x:242,y:77,w:186,h:64,c:'#80dfb9',icon:'data',title:'Import i źródła',sub:'Ad · PageCapture',to:'flow',info:'Importer zachowuje oryginalne pola, identyfikatory i źródła. Ponowny import tej samej emisji jest idempotentny.'},
 {id:'features',x:242,y:184,w:186,h:64,c:'#80dfb9',icon:'layers',title:'Ekstrakcja cech',sub:'OCR · pHash · TF-IDF',to:'lab',info:'Kadr obrazu i tekst odczytany przez OCR dziedziczą wspólny identyfikator pochodzenia.'},
 {id:'engine',x:477,y:129,w:194,h:72,c:'#baa4fa',icon:'matching',title:'Silnik korelacji',sub:'pary · complete-link',to:'matching',info:'Silnik ocenia pary i scala grupy przy pełnym zestawie mocnych połączeń między członkami.'},
 {id:'groups',x:724,y:77,w:185,h:64,c:'#9ebffc',icon:'graph',title:'Graf kampanii',sub:'Cytoscape.js',to:'ui',info:'Węzeł to emisja, obwiednia to hipoteza kampanii, a relacja prowadzi do dwóch źródeł.'},
 {id:'time',x:724,y:184,w:185,h:64,c:'#9ebffc',icon:'flow',title:'Oś czasu',sub:'vis-timeline',to:'ui',info:'Zdarzenia rozróżniają publikację, pozyskanie i obserwację strony. Wybór zdarzenia wyróżnia post.'}
];
function mapGraphic(){
 const labels=[[21,'ŹRÓDŁA'],[242,'PRZETWARZANIE'],[477,'KORELACJA'],[724,'INTERFEJS']];
 const wire=(d,color='#638879')=>'<path d="'+d+'" fill="none" stroke="'+color+'" stroke-width="1.8" stroke-linejoin="round"/>';
 const segments=wire('M194 109H242','\x238d805f')+wire('M194 216h13q9 0 9-9v-89q0-9 10-9h16','#8d805f')+wire('M335 141v43')+wire('M428 216h17q10 0 10-10v-31q0-10 10-10h12')+wire('M671 165h15q12 0 12-12v-34q0-10 10-10h16','#8c86a8')+wire('M686 165q12 0 12 12v29q0 10 10 10h16','#8c86a8');
 const nodes=diagramNodes.map(n=>'<g class="node" role="button" tabindex="0" aria-label="'+n.title+' — szczegóły modułu" data-n="'+n.id+'"><rect x="'+n.x+'" y="'+n.y+'" width="'+n.w+'" height="'+n.h+'" rx="7" fill="#1a2025" stroke="'+n.c+'" stroke-opacity=".59"/><rect x="'+(n.x+12)+'" y="'+(n.y+13)+'" width="24" height="24" rx="5" fill="'+n.c+'" fill-opacity=".09" stroke="'+n.c+'" stroke-opacity=".25"/><svg x="'+(n.x+16)+'" y="'+(n.y+17)+'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="'+n.c+'" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'+icons[n.icon]+'</svg><text x="'+(n.x+44)+'" y="'+(n.y+30)+'" fill="#e7eaed" font-family="Segoe UI,Arial,sans-serif" font-size="15" font-weight="600">'+n.title+'</text><text x="'+(n.x+13)+'" y="'+(n.y+50)+'" fill="#adb6c0" font-family="Consolas,monospace" font-size="12">'+n.sub+'</text></g>').join('');
 return '<div class="map-scroll"><svg class="system-svg" viewBox="0 0 930 273" role="group" aria-label="Mapa architektury. Wybierz moduł, aby poznać jego zadanie.">'+labels.map(([x,l])=>'<text x="'+x+'" y="43" fill="#9ca6af" font-family="Consolas,monospace" font-size="11" letter-spacing="1.5">'+l+'</text>').join('')+segments+nodes+'</svg></div><div class="map-detail" aria-live="polite" hidden></div>'
}
function overview(){
 const teams=[['A','Dane i źródła','Import, deduplikacja i pochodzenie.','data','#e8bf83','#28231c'],['B','Ekstrakcja i pomiar','Cechy, modele i ewaluacja.','lab','#83dfb9','#192821'],['C','Korelacja i demonstrator','Grupowanie, graf i oś czasu.','matching','#baa4fa','#24212c']];
 return '<section class="map-panel"><div class="map-head"><h2>'+ico('graph')+'Mapa systemu</h2><button class="map-open" data-expand>'+ico('expand')+'Powiększ</button></div>'+mapGraphic()+'<div class="map-bottom"><div class="legend">'+[['Dane','#e8bf83'],['Ekstrakcja','#83dfb9'],['Korelacja','#baa4fa'],['Widok','#9ebffc']].map(([a,b])=>'<span style="--tone:'+b+'">'+a+'</span>').join('')+'</div><span class="map-version">Python / Streamlit</span></div></section><div class="team-head"><h2>Obszary implementacji</h2><a href="#/teams">Pełny plan prac</a></div><div class="team-grid">'+teams.map(([a,t,d,i,c,b])=>'<a class="team-card" href="#/teams/para-'+a.toLowerCase()+'" style="--tone:'+c+';--wash:'+b+'"><div class="team-icon">'+ico(i)+'</div><div><small>PARA '+a+'</small><strong>'+t+'</strong><p>'+d+'</p></div></a>').join('')+'</div>'
}
function hookMap(host){host.querySelectorAll('[data-n]').forEach(node=>{const select=()=>{const n=diagramNodes.find(v=>v.id===node.dataset.n);const panel=host.querySelector('.map-detail');panel.hidden=false;panel.innerHTML='<strong>'+n.title+'</strong><span>'+n.info+'</span><a href="#/'+n.to+'">Otwórz rozdział</a>';panel.querySelector('a').onclick=()=>{if($('#map-dialog').open)$('#map-dialog').close()}};node.onclick=select;node.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();select()}}})}
const keys=Object.keys(pages);let lastRoute=null;
function nav(){let group='';$('#navigation').innerHTML=keys.map(k=>{const [title,cat,icon]=pages[k];const start=cat!==group;const preceding=group;group=cat;return (start?(preceding?'</div>':'')+'<div class="rail-group"><div class="group-title">'+cat+'</div>':'')+'<a href="#/'+k+'" data-link="'+k+'">'+ico(icon)+'<span>'+title+'</span></a>'}).join('')+'</div>'}
const slug=text=>text.toLowerCase().replace(/ł/g,'l').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
function makeHeadings(el){const ids=new Set();el.querySelectorAll('h2,h3').forEach((h,i)=>{let id=h.id||slug(h.textContent)||'sekcja';if(ids.has(id))id+='-'+i;h.id=id;ids.add(id)})}
function menu(open){$('#rail').classList.toggle('open',open);$('#scrim').hidden=!open;$('#menu').setAttribute('aria-expanded',String(open))}
function outline(open){$('#outline').hidden=!open;$('#outline-toggle').setAttribute('aria-expanded',String(open))}
function route(){const [,key,anchor]=location.hash.split('/');const k=pages[key]?key:'overview';menu(false);outline(false);
 if(k!==lastRoute){lastRoute=k;const [name,cat,,intro]=pages[k];$('#heading').textContent=name;$('#section-name').textContent=cat;$('#crumb').textContent=name;$('#intro').textContent=intro;document.title=name+' · ScamGraph Docs';document.querySelectorAll('[data-link]').forEach(a=>a.dataset.link===k?a.setAttribute('aria-current','page'):a.removeAttribute('aria-current'));
 const interactive=$('#interactive');interactive.innerHTML='';if(k==='overview'){interactive.innerHTML=overview();hookMap(interactive);interactive.querySelector('[data-expand]').onclick=()=>{const b=$('#big-map');b.innerHTML=mapGraphic();hookMap(b);$('#map-dialog').showModal()}}else if(window.renderExplorer)window.renderExplorer(k,interactive);
 const a=$('#article');a.innerHTML=window.manual?.[k]||'';a.querySelectorAll('table').forEach(t=>{if(t.parentElement.classList.contains('table-wrap'))return;const d=document.createElement('div');d.className='table-wrap';t.before(d);d.append(t)});makeHeadings(a);const h=[...a.querySelectorAll('h2,h3')].filter(v=>!v.closest('details'));$('#outline').innerHTML=h.map(v=>'<a href="#/'+k+'/'+v.id+'">'+esc(v.textContent)+'</a>').join('');$('#outline-toggle').hidden=!h.length;const idx=keys.indexOf(k);$('#paging').innerHTML=(idx>0?'<a href="#/'+keys[idx-1]+'"><span>Poprzedni rozdział</span>'+pages[keys[idx-1]][0]+'</a>':'')+(idx<keys.length-1?'<a class="next" href="#/'+keys[idx+1]+'"><span>Następny rozdział</span>'+pages[keys[idx+1]][0]+'</a>':'');}
 if(anchor){let target=document.getElementById(anchor);if(!target&&/^para-[abc]$/.test(anchor)){target=[...$('#article').querySelectorAll('h2,h3,h4,summary')].find(h=>new RegExp('para '+anchor.at(-1)+'\\b','i').test(h.textContent))}if(target){for(let p=target.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;target.scrollIntoView({block:'start'})}else window.scrollTo(0,0)}else window.scrollTo(0,0)
}
const norm=s=>s.toLocaleLowerCase('pl').replace(/ł/g,'l').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
function buildSearch(){return keys.flatMap(k=>{const el=document.createElement('article');el.innerHTML=window.manual?.[k]||'';makeHeadings(el);const result=[{k,title:pages[k][0],anchor:'',text:pages[k][3]}];for(const h of el.querySelectorAll('h2,h3')){let t='',node=h.nextElementSibling;while(node&&!/^H[23]$/.test(node.tagName)){t+=' '+node.textContent;node=node.nextElementSibling}result.push({k,title:h.textContent,anchor:h.id,text:t.replace(/\s+/g,' ').trim()})}return result})}
document.querySelector('.skip').addEventListener('click', event => {
 event.preventDefault();
 const main = document.getElementById('main');
 main.focus();
 main.scrollIntoView({block:'start'});
});
let searchIndex;function search(){searchIndex??=buildSearch();const q=norm($('#query').value.trim()), words=q.split(/\s+/).filter(Boolean);const found=q?searchIndex.map(r=>({r,score:words.every(w=>norm(r.title+' '+r.text+' '+pages[r.k][0]).includes(w))?1+words.reduce((s,w)=>s+(norm(r.title).includes(w)?5:0),0):0})).filter(o=>o.score).sort((a,b)=>b.score-a.score).map(v=>v.r):searchIndex.filter(r=>!r.anchor);
 $('#hit-count').textContent=q?'Liczba wyników: '+found.length:'Rozdziały podręcznika';$('#hits').innerHTML=found.slice(0,55).map(r=>'<a href="#/'+r.k+(r.anchor?'/'+r.anchor:'')+'"><strong>'+esc(r.title)+'</strong><small>'+esc(pages[r.k][0]+(r.text?' · '+r.text.slice(0,108):''))+'</small></a>').join('')||'<p style="padding:8px 12px">Brak wyników. Spróbuj nazwy pola, metody albo rozdziału.</p>'}
function openSearch(){search();$('#find').showModal();$('#query').focus();$('#query').select()}
nav();paintIcons();$('#menu').onclick=()=>menu(!$('#rail').classList.contains('open'));$('#scrim').onclick=()=>menu(false);$('#open-search').onclick=openSearch;$('#close-search').onclick=()=>$('#find').close();$('#query').oninput=search;$('#hits').addEventListener('click',e=>{if(e.target.closest('a'))$('#find').close()});$('#close-map').onclick=()=>$('#map-dialog').close();$('#outline-toggle').onclick=()=>outline($('#outline').hidden);$('#outline').onclick=()=>outline(false);document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();if($('#find').open)$('#find').close();else openSearch()}if(e.key==='Escape'){menu(false);outline(false)}});document.addEventListener('click',e=>{if(!e.target.closest('#outline,#outline-toggle'))outline(false)});document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close()}}));window.addEventListener('hashchange',route);route();
