import { getCase } from "./cases.js";

const explorer = document.getElementById("walk-explorer");
const controls = explorer.querySelectorAll("button[data-walk-case]");

function cell(tag, value, scope) {
  const element = document.createElement(tag);
  element.textContent = value;
  if (scope) element.scope = scope;
  return element;
}

function pairTable({ target, tier, rows }) {
  const table = document.createElement("table");
  table.className = "guide-table";
  table.createCaption().textContent = `SG-031 ↔ ${target} · poziom ${tier}`;

  const heading = table.createTHead().insertRow();
  for (const label of [
    "Ślad",
    "Zgłoszenie SG-031",
    `Referencja ${target}`,
    "Interpretacja",
  ]) {
    heading.append(cell("th", label, "col"));
  }

  const body = table.createTBody();
  for (const { label, left, right, detail } of rows) {
    body
      .insertRow()
      .append(
        cell("th", label, "row"),
        cell("td", left),
        cell("td", right),
        cell("td", detail),
      );
  }
  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  wrapper.append(table);
  return wrapper;
}

function showCase(key) {
  const result = getCase(key);
  document.getElementById("walk-title").textContent = result.title;
  document.getElementById("walk-status").textContent = result.status;
  document.getElementById("walk-summary").textContent = result.summary;
  document
    .getElementById("walk-pairs")
    .replaceChildren(...result.pairs.map(pairTable));
  document.getElementById("walk-json").textContent = JSON.stringify(
    result,
    null,
    2,
  );
  for (const button of controls) {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.walkCase === key),
    );
  }
}

showCase("match");
for (const button of controls) {
  button.addEventListener("click", () => showCase(button.dataset.walkCase));
}
explorer.hidden = false;
document.getElementById("walk-loading").hidden = true;
