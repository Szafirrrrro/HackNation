(() => {
  "use strict";

  const css = `
    .sgx { --sx-bg:#101318; --sx-panel:#171b22; --sx-line:#30353e; --sx-ink:#e4e7ec; --sx-muted:#a4abba; --sx-a:#69dfc2; --sx-b:#b5a0ff; color:var(--sx-ink); background:var(--sx-bg); border:1px solid var(--sx-line); border-radius:14px; padding:clamp(14px,2.6vw,30px); min-width:0; text-align:left; container-type:inline-size; font:inherit; }
    .sgx *, .sgx *::before, .sgx *::after { box-sizing:border-box; }
    .sgx h3,.sgx h4,.sgx p,.sgx dl,.sgx dd,.sgx pre,.sgx fieldset,.sgx ol { margin:0; }
    .sgx h3 { font-size:clamp(1.15rem,2vw,1.55rem); line-height:1.2; letter-spacing:-.02em; }
    .sgx h4 { font-size:1rem; line-height:1.4; }
    .sgx p,.sgx dd { line-height:1.55; }
    .sgx .sx-sub { color:var(--sx-muted); margin-top:.45rem; font-size:.95rem; }
    .sgx .sx-section { margin-top:1.15rem; }
    .sgx .sx-small,.sgx dt { color:var(--sx-muted); font-size:.82rem; font-weight:500; }
    .sgx .sx-controls { display:flex; flex-wrap:wrap; gap:.4rem; margin:.9rem 0 0; }
    .sgx button,.sgx select { font:inherit; color:var(--sx-ink); }
    .sgx button { cursor:pointer; min-height:42px; background:var(--sx-panel); border:1px solid var(--sx-line); border-radius:7px; padding:.48rem .7rem; font-size:.91rem; text-align:left; line-height:1.3; }
    .sgx button:hover { border-color:var(--sx-muted); }
    .sgx button[aria-pressed="true"] { color:var(--sx-a); background:#152a28; border-color:var(--sx-a); }
    .sgx :is(button,select):focus-visible { outline:3px solid var(--sx-b); outline-offset:3px; }
    .sgx .sx-kv { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,145px),1fr)); gap:.9rem; }
    .sgx .sx-kv dd { margin-top:.18rem; overflow-wrap:anywhere; font-size:.95rem; }
    .sgx .sx-panel { background:var(--sx-panel); border:1px solid var(--sx-line); border-radius:9px; padding:clamp(12px,2.2vw,20px); margin-top:.85rem; }
    .sgx .sx-panel h4 + p,.sgx .sx-panel p + dl,.sgx .sx-panel h4 + dl { margin-top:.6rem; }
    .sgx code,.sgx pre { font:500 .85rem/1.55 ui-monospace,Consolas,monospace; color:var(--sx-a); overflow-wrap:anywhere; }
    .sgx pre { white-space:pre-wrap; }
    .sgx .sx-steps { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); padding:0; list-style:none; gap:.38rem; }
    .sgx .sx-steps li { position:relative; min-width:0; }
    .sgx .sx-steps button { width:100%; height:100%; display:flex; flex-direction:column; align-items:flex-start; gap:.58rem; font-weight:600; }
    .sgx .sx-steps svg { width:24px; height:24px; stroke:currentColor; fill:none; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; }
    .sgx .sx-entities { display:grid; grid-template-columns:1fr auto 1fr auto 1fr; align-items:center; gap:.4rem; }
    .sgx .sx-entities button { width:100%; min-width:0; text-align:center; }
    .sgx .sx-entities button small { display:block; color:var(--sx-muted); margin-top:.25rem; font-size:.8rem; }
    .sgx .sx-wire { width:clamp(8px,2.5vw,32px); border-top:2px solid var(--sx-muted); position:relative; }
    .sgx .sx-wire::before,.sgx .sx-wire::after { content:""; display:block; position:absolute; top:-4px; width:6px; height:6px; border-radius:50%; background:var(--sx-muted); }
    .sgx .sx-wire::after { right:0; }
    .sgx .sx-switch { display:flex; gap:.35rem; flex-wrap:wrap; }
    .sgx .sx-switch button { font-size:.86rem; min-height:38px; }
    .sgx .sx-select { display:block; width:100%; min-width:0; border:1px solid var(--sx-line); border-radius:6px; padding:.55rem 1.8rem .55rem .65rem; color-scheme:dark; background-color:var(--sx-bg); appearance:none; background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' fill='none' stroke='%23a4abba' stroke-width='1.5'%3E%3Cpath d='m3 5 4 4 4-4'/%3E%3C/svg%3E"); background-position:right .55rem center; background-repeat:no-repeat; min-height:42px; }
    .sgx .sx-labeled { display:grid; gap:.35rem; font-size:.93rem; }
    .sgx .sx-pairs { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.55rem; margin:.7rem 0 0; }
    .sgx .sx-pairs fieldset { min-width:0; border:1px solid var(--sx-line); border-radius:8px; padding:.55rem .6rem .7rem; }
    .sgx legend { font-size:.9rem; font-weight:600; padding:0 .28rem; color:var(--sx-b); }
    .sgx .sx-pairs label + label { margin-top:.55rem; }
    .sgx .sx-result { border-left:3px solid var(--sx-a); }
    .sgx .sx-result code { display:block; margin-top:.2rem; }
    .sgx .sx-result[data-tone="review"] { border-left-color:var(--sx-b); }
    .sgx .sx-result[data-tone="review"] code { color:var(--sx-b); }
    .sgx .sx-coverage { font-size:.88rem; color:var(--sx-muted); }
    .sgx .sx-graph { position:relative; height:215px; border:1px solid var(--sx-line); border-radius:9px; background-color:var(--sx-panel); background-image:radial-gradient(#353a44 1px,transparent 1px); background-size:16px 16px; }
    .sgx .sx-graph svg { position:absolute; inset:0; width:100%; height:100%; }
    .sgx .sx-node { position:absolute; transform:translate(-50%,-50%); font:600 .88rem ui-monospace,monospace; min-width:62px; text-align:center; border-radius:22px; }
    .sgx .sx-node[data-query] { border-radius:6px; border-style:dashed; }
    .sgx .sx-time { display:flex; flex-wrap:wrap; gap:.5rem; }
    .sgx .sx-time button { flex:1 1 120px; width:auto; }
    .sgx .sx-time time,.sgx .sx-time small { display:block; }
    .sgx .sx-time small { color:var(--sx-muted); margin-top:.25rem; }
    .sgx .sx-legend { display:flex; flex-wrap:wrap; gap:.3rem 1rem; margin:.45rem 0 .85rem; color:var(--sx-muted); font-size:.83rem; }
    .sgx .sx-legend span::before { content:""; width:1.3rem; display:inline-block; vertical-align:middle; border-top:2px solid var(--sx-a); margin-right:.4rem; }
    .sgx .sx-legend span:last-child::before { border-top:2px dashed var(--sx-b); }
    @container (max-width:590px) {
      .sgx .sx-steps { grid-template-columns:repeat(auto-fit,minmax(95px,1fr)); }
      .sgx .sx-steps button { flex-direction:row; align-items:center; gap:.4rem; }
      .sgx .sx-steps svg { width:18px; flex-shrink:0; }
      .sgx .sx-pairs { grid-template-columns:repeat(auto-fit,minmax(min(100%,168px),1fr)); }
      .sgx .sx-entities { gap:0; grid-template-columns:1fr; justify-items:center; }
      .sgx .sx-entities button { display:flex; justify-content:space-between; align-items:center; }
      .sgx .sx-wire { width:0; height:13px; border-top:0; border-left:2px solid var(--sx-muted); }
      .sgx .sx-wire::after,.sgx .sx-wire::before { display:none; }
    }
  `;

  const headings = {
    flow: ["Ścieżka jednego zgłoszenia", "Wybierz etap i prześledź, jak zmienia się materiał w syntetycznym przykładzie."],
    data: ["Jak udokumentować cel reklamy", "Wybierz obiekt i przełącz się między opisem pól a przykładowym rekordem."],
    matching: ["Symulator decyzji", "Wybierz scenariusz lub zmień ocenę pary. Symulator przelicza decyzję dla fikcyjnego zgłoszenia Q."],
    ui: ["Emisje i czas obserwacji", "Wybierz węzeł lub zdarzenie. Oba widoki pokazują ten sam syntetyczny przypadek."]
  };

  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }

  function button(label, click, className) {
    const node = make("button", className, label);
    node.type = "button";
    node.addEventListener("click", click);
    return node;
  }

  function selectButton(node, active) {
    node.setAttribute("aria-pressed", String(active));
  }

  function pairs(items) {
    const list = make("dl", "sx-kv");
    for (const [label, value] of items) {
      const row = make("div");
      row.append(make("dt", "", label), make("dd", "", value));
      list.append(row);
    }
    return list;
  }

  function livePanel() {
    const pane = make("div", "sx-panel");
    pane.setAttribute("aria-live", "polite");
    pane.setAttribute("aria-atomic", "true");
    return pane;
  }

  const flow = [
    ["Import", "M3 7h6l2 2h10v10H3z M12 3v9m-3-3 3 3 3-3", "Zachowaj tożsamość emisji", "Formularz przyjmuje obraz reklamy i wyciąg z biblioteki. Każdy materiał zachowuje własne pochodzenie.", "Zrzut PNG i wpis biblioteki", "Ad Q · dwa źródła"],
    ["Cechy", "M4 5h16v14H4z M7 14l3-3 3 3 2-2 3 3 M8 8h1", "Odczytaj porównywalne pola", "Z obrazu powstają pHash oraz tekst OCR. Wpis biblioteki dostarcza osobne pole z docelowym adresem.", "Ad Q", "Cechy obrazu, tekstu i celu"],
    ["Dowody", "M8 6H4v12h4 M16 6h4v12h-4 M8 12h8", "Porównaj obie strony", "Podobieństwo obrazu i jego OCR opiera się na tych samych pikselach. Zgodność celu ma osobne źródło po każdej stronie pary.", "Q i emisja referencyjna", "Evidence z polami i źródłami"],
    ["Grupy", "M6 7l12 1-7 10z M6 5v4m10-1h4m-9 8v4", "Sprawdź komplet mocnych par", "Kampania referencyjna obejmuje co najmniej dwie emisje. Przy scalaniu grup każda para między nimi musi mieć ocenę strong.", "Oceny par referencyjnych", "Hipoteza kampanii i profil"],
    ["Decyzja", "M3 12h5l3 5 5-10h5 M4 4h16", "Sprawdź nowe zgłoszenie", "Q jest mocno powiązane z każdą emisją jednej grupy. Przy braku silnego rywala wynik pokazuje tę grupę, pokrycie i źródła.", "Q i zamrożona referencja", "probable_match"]
  ];

  function renderFlow(root) {
    const steps = make("ol", "sx-steps sx-section");
    const detail = livePanel();
    const buttons = [];
    function choose(index) {
      const [, , title, explanation, input, output] = flow[index];
      buttons.forEach((node, i) => selectButton(node, i === index));
      detail.replaceChildren(make("h4", "", title), make("p", "", explanation), pairs([["Wejście", input], ["Wyjście", output]]));
    }
    flow.forEach(([name, icon], index) => {
      const item = make("li");
      const node = button("", () => choose(index));
      node.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="' + icon + '"/></svg>';
      node.append(make("span", "", name));
      item.append(node);
      steps.append(item);
      buttons.push(node);
    });
    root.append(steps, detail);
    choose(0);
  }

  const entities = [
    {type:"Ad", name:"Emisja", detail:"Jeden rekord opisuje jedną emisję ze stabilnym ID. Cel z niezależnego eksportu ma identyfikowalne pochodzenie.", fields:[["Klucz","ad_id"],["Źródło zewnętrzne","source.provider i source.ad_ref"]], record:{ad_id:"emit-7",source:{kind:"synthetic",provider:"demo",ad_ref:"wpis-7",collected_at:"2026-03-02T08:00:00Z"},landing_url:"https://sklep.example/rabat",url_origin:"eksport-7"}},
    {type:"AdPageLink", name:"Relacja", detail:"Dowód wskazuje konkretne pole oryginalnego wpisu i jego wartość. Ta relacja dopuszcza ślady strony do porównania emisji.", fields:[["Końce relacji","ad_id i capture_id"],["Dowód i czas","source_ref, origin_id i observed_at"]], record:{ad_id:"emit-7",capture_id:"str-4",origin_id:"eksport-7",observed_at:"2026-03-02T08:01:00Z",source_ref:{file:"sources/export.jsonl",record_id:"wpis-7",field:"destination",value:"https://sklep.example/rabat"}}},
    {type:"PageCapture", name:"Pobranie", detail:"Jeden zapis dokumentuje konkretne pobranie. Może samodzielnie uczestniczyć w porównywaniu stron, także gdy nie znamy źródłowej reklamy.", fields:[["Klucz","capture_id"],["Pomiar","document, html i dostępne pola HAR"]], record:{capture_id:"str-4",document:{url_without_query:"https://sklep.example/rabat"},har:{document_started_at:"2026-03-02T08:01:00Z",document_status:200},html:{title:"Rabat próbny"}}}
  ];

  function renderData(root) {
    const graph = make("div", "sx-entities sx-section");
    const modes = make("div","sx-switch sx-section");
    const pane = livePanel();
    let selected = 1;
    let example = false;
    const nodes = entities.map((entity, index) => {
      if (index) {
        const wire = make("span", "sx-wire");
        wire.setAttribute("aria-hidden","true");
        graph.append(wire);
      }
      const node = button(entity.type, () => { selected = index; update(); });
      node.append(make("small", "", entity.name));
      graph.append(node);
      return node;
    });
    const description = button("Typ i pola", () => { example = false; update(); });
    const sample = button("Przykład JSON", () => { example = true; update(); });
    modes.append(description, sample);
    function update() {
      nodes.forEach((node, i) => selectButton(node, i === selected));
      selectButton(description, !example);
      selectButton(sample, example);
      const entity = entities[selected];
      if (example) {
        pane.replaceChildren(make("pre", "", JSON.stringify(entity.record, null, 2)));
      } else {
        pane.replaceChildren(make("h4", "", entity.type + " · " + entity.name),make("p", "", entity.detail),pairs(entity.fields));
      }
    }
    root.append(graph, modes, pane);
    update();
  }

  const matchCases = {
    known: ["Jedna pełna grupa", ["strong","strong","clear","missing","clear"]],
    rival: ["Silny rywal", ["strong","strong","strong","missing","clear"]],
    both: ["Dwie pełne grupy", ["strong","strong","strong","strong","clear"]],
    partial: ["Częściowy ślad", ["similar","missing","clear","missing","clear"]],
    singleton: ["Mocna pojedyncza emisja", ["strong","strong","clear","missing","strong"]],
    unknown: ["Brak danych dla grupy", ["clear","missing","missing","missing","clear"]],
    novel: ["Wykluczona referencja", ["clear","missing","clear","missing","clear"]],
    empty: ["Pusta referencja", []]
  };
  const pairOptions = [
    ["strong","Mocna zgodność"], ["similar","Podobieństwo"], ["clear","Rozbieżność · pokrycie"], ["missing","Brak pokrycia"]
  ];
  const pairLabels = ["A1","A2","B1","B2","S1"];

  function assess(values) {
    const groups = [values.slice(0,2),values.slice(2,4)];
    const full = groups.filter(group => group.length === 2 && group.every(value => value === "strong"));
    const rival = groups.some(group => group.includes("strong") && !group.every(value => value === "strong"));
    if (full.length > 1 || (full.length === 1 && rival)) return ["review_needed","Rozstrzygnij konkurencję","Mocne dowody prowadzą do więcej niż jednej grupy. Sprawdź osobno źródła obu kandydatur."];
    if (full.length === 1) return ["probable_match","Prawdopodobne przypisanie","Q ma mocne powiązanie z każdym członkiem jednej grupy. Brak silnego rywala w innej grupie. Samotna emisja może nadal być podobna."];
    if (values.some(value => value === "strong" || value === "similar")) return ["review_needed","Sprawdź sugestię","Co najmniej jedna emisja wykazuje podobieństwo, a żadna grupa nie ma kompletu mocnych porównań z Q."];
    if (!values.length || !groups.every(group => group.includes("clear")) || values[4] !== "clear") return ["insufficient_evidence","Brakuje dowodów", values.length ? "Nie można wykluczyć wszystkich grup lub pojedynczej emisji. Rozbieżność przy wystarczającym pokryciu musi wystąpić dla każdej sprawdzanej grupy i każdej pojedynczej emisji." : "Referencja jest pusta. Dodaj materiał referencyjny, aby rozpocząć porównania."];
    return ["no_match","Możliwy nowy wzorzec","W każdej grupie co najmniej jedna para ma zmierzoną rozbieżność z wystarczającym pokryciem. Wykluczono również pojedynczą emisję. Brak sugestii podobieństwa."];
  }

  function labeledSelect(caption, choices) {
    const label = make("label","sx-labeled");
    label.append(make("span","",caption));
    const select = make("select","sx-select");
    for (const [value, text] of choices) {
      const option = make("option","",text);
      option.value = value;
      select.append(option);
    }
    label.append(select);
    return { label, select };
  }

  function renderMatching(root) {
    const scenario = labeledSelect("Scenariusz",Object.entries(matchCases).map(([key,[title]]) => [key,title]));
    scenario.label.classList.add("sx-section");
    const custom = make("option","","Ustawienia własne");
    custom.value = "custom";
    custom.disabled = true;
    scenario.select.append(custom);
    const figures = make("div","sx-pairs");
    const pane = livePanel();
    pane.classList.add("sx-result");
    const controls = [];
    let empty = false;
    ["Kampania A","Kampania B","Pojedyncza emisja"].forEach((name, groupIndex) => {
      const fieldset = make("fieldset");
      fieldset.append(make("legend","",name));
      for (const id of pairLabels.slice(groupIndex * 2, groupIndex * 2 + 2)) {
        const field = labeledSelect("Q i " + id,pairOptions);
        field.select.addEventListener("change", () => {
          scenario.select.value = "custom";
          showDecision();
        });
        controls.push(field.select);
        fieldset.append(field.label);
      }
      figures.append(fieldset);
    });

    function showDecision() {
      const values = empty ? [] : controls.map(field => field.value);
      const [status, title, description] = assess(values);
      pane.dataset.tone = status === "review_needed" || status === "insufficient_evidence" ? "review" : "normal";
      const parts = [make("h4","",title),make("code","",status),make("p","",description)];
      if (values.length) {
        const missingIds = pairLabels.filter((id, i) => values[i] === "missing");
        const missingDetail = missingIds.length ? " Brak pokrycia dla " + missingIds.join(", ") + "." : "";
        parts.push(make("p","sx-coverage","Porównane emisje: " + values.length + "." + missingDetail));
      }
      pane.replaceChildren(...parts);
    }

    function preset(key) {
      const values = matchCases[key][1];
      empty = values.length === 0;
      figures.hidden = empty;
      figures.style.display = empty ? "none" : "";
      controls.forEach((field, index) => {
        field.disabled = empty;
        if (!empty) field.value = values[index];
      });
      scenario.select.value = key;
      showDecision();
    }
    scenario.select.addEventListener("change",() => preset(scenario.select.value));
    root.append(scenario.label,figures,pane);
    preset("known");
  }

  const examples = [
    {id:"L-17",x:25,y:27,kind:"Emisja referencyjna",date:"2026-03-02T09:00:00Z",time:"2 mar · 09:00",event:"Publikacja",source:"Wpis biblioteki L-17",note:"L-17 i L-23 mają specyficzne podobieństwo obrazu i zgodny, niezależnie udokumentowany cel. Dwie emisje tworzą grupę K."},
    {id:"L-23",x:73,y:27,kind:"Emisja referencyjna",date:"2026-03-04T14:30:00Z",time:"4 mar · 14:30",event:"Publikacja",source:"Wpis biblioteki L-23",note:"L-23 ma oddzielne ID emisji. O silnej parze z L-17 decyduje wspólna kreacja oraz niezależny zapis pola docelowego."},
    {id:"Q",x:27,y:77,kind:"Nowe zgłoszenie",date:"2026-03-07T11:10:00Z",time:"7 mar · 11:10",event:"Pozyskanie",source:"Formularz przyjęcia Q",note:"Q przypomina L-17 warstwą obrazu. Cel i data publikacji pozostają nieustalone. Sugestia wymaga przeglądu."}
  ];

  function renderUi(root) {
    const graph = make("div","sx-graph sx-section");
    graph.setAttribute("role","group");
    graph.setAttribute("aria-label","Graf powiązań fikcyjnej kampanii K i zgłoszenia Q");
    graph.innerHTML = '<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><line x1="25" y1="27" x2="73" y2="27" stroke="#69dfc2" stroke-width="3" vector-effect="non-scaling-stroke"/><line x1="27" y1="77" x2="25" y2="27" stroke="#b5a0ff" stroke-width="2" stroke-dasharray="5 4" vector-effect="non-scaling-stroke"/></svg>';
    const legend = make("div","sx-legend");
    legend.append(make("span","","Mocna para w kampanii K"),make("span","","Podobieństwo do przeglądu"));
    const timeHeading = make("h4","","Zdarzenia w UTC");
    const timeline = make("div","sx-time");
    timeline.setAttribute("role","group");
    timeline.setAttribute("aria-label","Wybór zdarzenia na osi czasu");
    const detail = livePanel();
    const nodes = [], events = [];

    function choose(index) {
      const item = examples[index];
      nodes.forEach((node,i) => selectButton(node,index === i));
      events.forEach((node,i) => selectButton(node,index === i));
      detail.replaceChildren(make("h4","",item.id + " · " + item.kind),make("p","",item.note),pairs([["Zdarzenie",item.event + " · " + item.time + " UTC"],["Źródło czasu",item.source]]));
    }

    examples.forEach((item,index) => {
      const node = button(item.id,() => choose(index),"sx-node");
      node.setAttribute("aria-label",item.id + " · " + item.kind);
      node.style.left = item.x + "%";
      node.style.top = item.y + "%";
      if (item.id === "Q") node.dataset.query = "";
      const event = button("",() => choose(index));
      const time = make("time","",item.time);
      time.dateTime = item.date;
      event.append(time,make("small","",item.id + " · " + item.event));
      nodes.push(node);
      events.push(event);
      graph.append(node);
      timeline.append(event);
    });
    root.append(graph,legend,timeHeading,timeline,detail);
    choose(0);
  }

  const renderers = {flow:renderFlow,data:renderData,matching:renderMatching,ui:renderUi};

  window.renderExplorer = function renderExplorer(key, element) {
    if (!Object.hasOwn(renderers,key) || !element) return false;
    if (!document.getElementById("scamgraph-explorer-css")) {
      const style = make("style","",css);
      style.id = "scamgraph-explorer-css";
      document.head.append(style);
    }
    const root = make("section","sgx");
    const [title, subtitle] = headings[key];
    root.setAttribute("aria-label",title);
    root.append(make("h3","",title),make("p","sx-sub",subtitle));
    renderers[key](root);
    element.replaceChildren(root);
    return true;
  };
})();
