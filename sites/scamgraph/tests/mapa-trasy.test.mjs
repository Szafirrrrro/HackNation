import assert from "node:assert/strict";
import test from "node:test";
import { layerRoutes } from "../dist/mapa-trasy.js";

const node = (x, top, width = 160) => ({ x, top, bottom: top + 70, width });

test("aligned nodes are joined by one vertical segment", () => {
  const boxes = new Map([["source", node(100, 0)], ["target", node(100, 130)]]);
  const [route] = layerRoutes([["source", "target"]], boxes);
  assert.equal(route.path, "M 100 71 V 128");
});

test("branches on the same side use distinct ports and lanes, in spatial order", () => {
  for (const direction of [-1, 1]) {
    const boxes = new Map([
      ["root", node(400, 0)], ["aligned", node(400, 130)],
      ["near", node(400 + direction * 160, 130)],
      ["far", node(400 + direction * 320, 130)],
    ]);
    const edges = ["near", "aligned", "far"].map(target => ["root", target]);
    const routes = layerRoutes(edges, boxes);
    const path = id => routes.find(route => route.target === id).path;
    const turn = id => {
      const commands = path(id).split(" ");
      assert.deepEqual(commands.filter(token => /^[A-Za-z]$/.test(token)), ["M", "V", "a", "H", "a", "V"]);
      assert.equal(Number(commands[6]), 8);
      return { port: Number(commands[1]), startOfBend: Number(commands[4]) };
    };
    const near = turn("near");
    const far = turn("far");
    assert.ok(direction * (near.port - 400) > 0);
    assert.ok(direction * (far.port - near.port) > 0);
    assert.ok(near.startOfBend > far.startOfBend);
    assert.equal(path("aligned"), "M 400 71 V 128");
    assert.deepEqual(layerRoutes(edges.toReversed(), boxes).reverse(), routes);
  }
});
