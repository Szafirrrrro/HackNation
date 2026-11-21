import { getCase } from "./cases.js";
import "./mapa.js";

const caseButtons = [...document.querySelectorAll("[data-case]")];
const pairSelect = document.getElementById("pair");
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
    addText(section, "h4", row.label);
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

function selectCase(key, announce) {
  current = getCase(key);
  for (const button of caseButtons)
    button.setAttribute("aria-pressed", String(button.dataset.case === key));
  document.getElementById("verdict-title").textContent = current.title;
  document.getElementById("verdict-code").textContent = current.status;
  document.getElementById("verdict-summary").textContent = current.summary;
  showEvidence();
  document.getElementById("case-body").hidden = false;
  if (announce)
    document.getElementById("live").textContent =
      current.title + ". " + current.summary;
}
for (const button of caseButtons)
  button.addEventListener("click", () => selectCase(button.dataset.case, true));
pairSelect.addEventListener("change", showEvidence);
selectCase("match", false);

const nav = [...document.querySelectorAll('aside nav a[href^="#"]')];
const chapters = nav.map((link) => document.getElementById(link.hash.slice(1)));
function highlightSection() {
  let active = chapters[0];
  for (const chapter of chapters) {
    if (chapter.getBoundingClientRect().top <= window.innerHeight * 0.34)
      active = chapter;
  }
  if (
    window.scrollY + window.innerHeight >=
    document.documentElement.scrollHeight - 2
  )
    active = chapters.at(-1);
  for (const link of nav) {
    if (link.hash === "#" + active.id)
      link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}
document.addEventListener("scroll", highlightSection, { passive: true });
window.addEventListener("resize", highlightSection);
highlightSection();
