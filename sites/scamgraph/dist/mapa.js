import { flows, modules } from "./mapa-systemu.js";
import { layerRoutes } from "./mapa-trasy.js";

const board = document.getElementById("map-board");
const lines = document.getElementById("map-lines");
const rows = document.getElementById("map-rows");
const tabs = document.getElementById("flow-tabs");
const params = new URLSearchParams(window.location.search);
let flowKey = "korpus";
let nodeKey = "";
const buttons = new Map();

function element(tag, content, className) {
  const item = document.createElement(tag);
  item.textContent = content;
  if (className) item.className = className;
  return item;
}

function draw() {
  const bounds = board.getBoundingClientRect();
  const boxes = new Map();
  for (const [id, button] of buttons) {
    const rect = button.getBoundingClientRect();
    boxes.set(id, { x: rect.left + rect.width / 2 - bounds.left, width: rect.width,
      top: rect.top - bounds.top, bottom: rect.bottom - bounds.top });
  }
  const flow = flows[flowKey];
  const routes = flow.rows.flatMap(row => layerRoutes(flow.edges.filter(([source]) => row.includes(source)), boxes));
  const paths = routes.map(({ source, target, path: geometry }) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", geometry);
    const isSelected = source === nodeKey || target === nodeKey;
    path.setAttribute("class", isSelected ? "connected" : "edge");
    path.setAttribute("marker-end", isSelected ? "url(#arrow-on)" : "url(#arrow-base)");
    return path;
  });
  // Draw the selected route last so it stays visible at crossings.
  lines.replaceChildren(...paths.filter(p => p.matches(".edge")), ...paths.filter(p => p.matches(".connected")));
}

function selectNode(key, announce) {
  nodeKey = key;
  const node = modules[key];
  const flow = flows[flowKey];
  for (const [id, button] of buttons) button.setAttribute("aria-pressed", String(id === key));
  document.getElementById("node-meta").textContent = "Zespół " + node.owner + "  /  " + node.type;
  document.getElementById("node-title").textContent = node.title;
  document.getElementById("node-shortcut").textContent = "Opis węzła „" + node.title + "”";
  document.getElementById("node-action").textContent = node.action;
  const fields = document.getElementById("node-fields");
  fields.replaceChildren();
  for (const [title, value] of [
    ["Wejście", node.input], ["Wynik", node.output],
    ["Przypadek brzegowy", node.failure], ["Jak odebrać pracę", node.check],
  ]) {
    fields.append(element("dt", title), element("dd", value));
  }
  for (const [title, neighbors] of [
    ["Odbiera z", flow.edges.filter(([, to]) => to === key).map(([from]) => from)],
    ["Przekazuje do", flow.edges.filter(([from]) => from === key).map(([, to]) => to)],
  ]) {
    if (!neighbors.length) continue;
    const links = element("dd", "", "related-nodes");
    for (const id of neighbors) {
      const button = element("button", modules[id].title);
      button.type = "button";
      button.addEventListener("click", () => {
        selectNode(id, true);
        document.getElementById("node-title").focus({ preventScroll: true });
      });
      links.append(button);
    }
    fields.append(element("dt", title), links);
  }
  document.getElementById("node-chapter").href = "./architektura.html#" + node.chapter;
  const permalink = new URL(window.location.href);
  permalink.searchParams.set("graf", flowKey);
  permalink.searchParams.set("modul", key);
  permalink.hash = "architektura";
  document.getElementById("node-link").href = permalink.href;
  if (announce) document.getElementById("map-status").textContent = flow.title + ". " + node.title + ". " + node.action;
  draw();
}

function selectFlow(key, requested, announce) {
  flowKey = key;
  const flow = flows[key];
  for (const button of tabs.children) button.setAttribute("aria-pressed", String(button.dataset.flow === key));
  document.getElementById("flow-summary").textContent = flow.summary;
  buttons.clear();
  rows.replaceChildren();
  for (const ids of flow.rows) {
    const row = element("div", "", "map-row");
    for (const id of ids) {
      const node = modules[id];
      const button = element("button", "", "map-node");
      button.type = "button";
      button.dataset.owner = node.owner[0];
      button.setAttribute("aria-controls", "map-detail");
      button.append(element("small", node.owner), element("strong", node.title));
      button.addEventListener("click", () => selectNode(id, true));
      buttons.set(id, button);
      row.append(button);
    }
    rows.append(row);
  }
  selectNode(buttons.has(requested) ? requested : flow.initial, announce);
}

for (const [key, flow] of Object.entries(flows)) {
  const button = element("button", flow.title);
  button.type = "button";
  button.dataset.flow = key;
  button.addEventListener("click", () => selectFlow(key, flow.initial, true));
  tabs.append(button);
}
document.getElementById("node-title").tabIndex = -1;
document.getElementById("back-to-node").addEventListener("click", () => buttons.get(nodeKey).focus());
selectFlow(Object.hasOwn(flows, params.get("graf")) ? params.get("graf") : flowKey, params.get("modul"), false);
new ResizeObserver(draw).observe(board);
document.fonts.ready.then(draw);
