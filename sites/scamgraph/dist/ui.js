import { getCase } from "./cases.js";

const caseButtons = [...document.querySelectorAll("[data-case]")];
const pairSelect = document.getElementById("pair");
const canvas = document.getElementById("graph");
let current = getCase("match");

function addText(parent, tag, value, className) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value;
  parent.append(element);
  return element;
}

function showEvidence() {
  const pair = current.pairs.find((item) => item.target === pairSelect.value);
  const rows = document.getElementById("rows");
  rows.replaceChildren();
  for (const row of pair.rows) {
    const section = document.createElement("section");
    section.className = "ev-row";
    addText(section, "h4", row.label, "ev-title");
    const values = document.createElement("div");
    values.className = "ev-values";
    for (const [id, value] of [
      ["SG-031", row.left],
      [pair.target, row.right],
    ]) {
      const field = document.createElement("div");
      addText(field, "span", id);
      addText(field, "code", value);
      values.append(field);
    }
    section.append(values);
    addText(section, "p", row.detail);
    rows.append(section);
  }
}

// The field lines surround the reference ads and distinguish the incoming query.
function drawGraph() {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.clientWidth,
    h = canvas.clientHeight;
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(w * pixelRatio);
  canvas.height = Math.round(h * pixelRatio);
  ctx.scale(pixelRatio, pixelRatio);
  const points = [
    [0.23 * w, 0.31 * h],
    [0.36 * w, 0.75 * h],
    [0.61 * w, 0.43 * h],
  ];
  const grid = 22;
  ctx.fillStyle = "#577361";
  for (let x = 10; x < w; x += grid) {
    for (let y = 8; y < h; y += grid) ctx.fillRect(x, y, 1, 1);
  }
  ctx.save();
  ctx.translate(0.3 * w, 0.53 * h);
  ctx.rotate(-0.42);
  // Nested outlines let the reference cluster remain visible without an edge.
  for (let ring = 0; ring < 15; ring++) {
    ctx.beginPath();
    for (let i = 0; i <= 135; i++) {
      const angle = (i / 135) * Math.PI * 2;
      const modulation =
        1 +
        0.13 * Math.cos(3 * angle + 0.28) +
        0.055 * Math.sin(5 * angle + ring * 0.065);
      const x = Math.cos(angle) * (w * 0.135 + ring * 5.2) * modulation;
      const y = Math.sin(angle) * (h * 0.27 + ring * 4.4) * modulation;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    if (ring === 0) {
      ctx.fillStyle = "rgba(110,156,98,.1)";
      ctx.fill();
    }
    ctx.strokeStyle = "rgba(150,189,146," + (0.32 - ring * 0.016) + ")";
    ctx.lineWidth = 0.8;
    ctx.stroke();
  }
  ctx.restore();
  function link(a, b, tier) {
    if (tier === "none") return;
    ctx.beginPath();
    ctx.moveTo(...a);
    ctx.lineTo(...b);
    ctx.setLineDash(tier === "strong" ? [] : [5, 5]);
    ctx.strokeStyle = tier === "strong" ? "#c6e97d" : "#d2dfd4";
    ctx.lineWidth = tier === "strong" ? 2.1 : 1.6;
    ctx.stroke();
    ctx.setLineDash([]);
  }
  function circle(x, y, r, color, fill) {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    if (fill) {
      ctx.fillStyle = color;
      ctx.fill();
    } else {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }
  link(points[0], points[1], "strong");
  current.pairs.forEach((pair, i) => link(points[2], points[i], pair.tier));
  points.forEach(([x, y], i) => {
    if (i === 2) {
      for (const [r, c] of [
        [40, "#48634b"],
        [32, "#526f51"],
        [23, "#779156"],
      ])
        circle(x, y, r, c, false);
      circle(x, y, 15, "#263f2c", true);
      circle(x, y, 15, "#d3ed95", false);
      circle(x, y, 8, "#ccec82", true);
    } else {
      circle(x, y, 12, "#253f30", true);
      circle(x, y, 12, "#8dab83", false);
      circle(x, y, 5.5, "#d9efb2", true);
    }
  });
}

function selectCase(key, announce) {
  current = getCase(key);
  for (const button of caseButtons)
    button.setAttribute("aria-pressed", String(button.dataset.case === key));
  document.getElementById("verdict-title").textContent = current.title;
  document.getElementById("verdict-code").textContent = current.status;
  document.getElementById("verdict-summary").textContent = current.summary;
  canvas.parentElement.setAttribute(
    "aria-label",
    "Grupa SG-014 i SG-022 oraz nowa reklama SG-031. " + current.summary,
  );
  showEvidence();
  document.getElementById("case-body").hidden = false;
  drawGraph();
  if (announce)
    document.getElementById("live").textContent =
      current.title + ". " + current.summary;
}

for (const button of caseButtons)
  button.addEventListener("click", () => selectCase(button.dataset.case, true));
pairSelect.addEventListener("change", showEvidence);
selectCase("match", false);
new ResizeObserver(drawGraph).observe(canvas.parentElement);
