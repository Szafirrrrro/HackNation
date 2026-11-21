// Each layer owns the open strip between its nodes and the next row.
// Keep aligned connections vertical and give branches separate attachment points.
function portX(node, neighbor, neighbors) {
  const dx = neighbor.x - node.x;
  if (neighbors.length === 1 || Math.abs(dx) < 1) return node.x;
  const side = neighbors.filter(other => (other.x - node.x) * Math.sign(dx) >= 1);
  side.sort((a, b) => Math.abs(a.x - node.x) - Math.abs(b.x - node.x));
  const fraction = (side.indexOf(neighbor) + 1) / (side.length + 1);
  return node.x + Math.sign(dx) * node.width * 0.45 * fraction;
}

function elbow(x1, y1, x2, y2, laneY) {
  if (Math.abs(x2 - x1) < 1) return `M ${x1} ${y1} V ${y2}`;
  const direction = Math.sign(x2 - x1);
  const radius = Math.min(8, Math.abs(x2 - x1) / 2, laneY - y1, y2 - laneY);
  const step = direction * radius;
  const firstSweep = direction > 0 ? 0 : 1;
  return [
    `M ${x1} ${y1} V ${laneY - radius}`,
    `a ${radius} ${radius} 0 0 ${firstSweep} ${step} ${radius}`,
    `H ${x2 - step}`,
    `a ${radius} ${radius} 0 0 ${1 - firstSweep} ${step} ${radius}`,
    `V ${y2}`,
  ].join(" ");
}

export function layerRoutes(edges, boxes) {
  const routes = edges.map(([source, target]) => {
    const from = boxes.get(source);
    const to = boxes.get(target);
    const targets = edges.filter(([id]) => id === source).map(([, id]) => boxes.get(id));
    const sources = edges.filter(([, id]) => id === target).map(([id]) => boxes.get(id));
    return { source, target, x1: portX(from, to, targets), y1: from.bottom + 1,
      x2: portX(to, from, sources), y2: to.top - 2 };
  });
  for (const direction of [-1, 1]) {
    const lanes = routes.filter(route => (route.x2 - route.x1) * direction >= 1);
    // The outer branch turns first so an inner branch never passes through it.
    lanes.sort((a, b) => direction * (b.x1 - a.x1));
    lanes.forEach((route, index) => { route.lane = (index + 1) / (lanes.length + 1); });
  }
  return routes.map(({ source, target, x1, y1, x2, y2, lane = 0.5 }) => ({
    source, target, path: elbow(x1, y1, x2, y2, y1 + (y2 - y1) * lane),
  }));
}
