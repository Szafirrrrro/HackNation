import test from "node:test";
import assert from "node:assert/strict";
import { getCase } from "../dist/cases.js";

const scenarios = [
  ["match", "probable_match", "strong", [2, 4]],
  ["review", "review_needed", "similar", [2, 4]],
  ["missing", "insufficient_evidence", "none", [62, 60]],
  ["none", "no_match", "none", [62, 60]],
];

function distance(left, right) {
  const bits = hash => BigInt("0x" + hash).toString(2).padStart(64, "0");
  const rightBits = bits(right);
  return [...bits(left)].filter((value, index) => value !== rightBits[index]).length;
}

for (const [key, status, tier, expectedDistances] of scenarios) {
  test(`${key} compares the query with both reference records`, () => {
    const result = getCase(key);
    assert.equal(result.status, status);
    assert.ok(result.title.length);
    assert.match(result.summary, /SG-031/);
    assert.deepEqual(result.pairs.map(pair => pair.target), ["SG-014", "SG-022"]);
    for (const [index, pair] of result.pairs.entries()) {
      assert.equal(pair.tier, tier);
      assert.equal(pair.rows.length, 3);
      for (const row of pair.rows) {
        for (const field of ["label", "left", "right", "detail"]) {
          assert.ok(row[field].length, field);
        }
      }
      const image = pair.rows.find(row => row.label.includes("pHash"));
      const measured = distance(image.left, image.right);
      assert.equal(measured, expectedDistances[index]);
      assert.ok(image.detail.includes(measured + "/64"));
    }
  });
}

test("the two reference ads can form a group under the same image threshold and URL rule", () => {
  const [first, second] = getCase("match").pairs;
  assert.equal(distance(first.rows[0].right, second.rows[0].right), 6);
  assert.equal(first.rows[2].right, second.rows[2].right);
  assert.equal(first.rows[2].left, first.rows[2].right);
});

test("OCR repeats the image observation and cannot make the review case strong", () => {
  for (const pair of getCase("review").pairs) {
    const [, ocr, url] = pair.rows;
    assert.equal(ocr.left, ocr.right);
    assert.match(ocr.detail, /wspólne źródło/);
    assert.notEqual(url.left, url.right);
    assert.equal(pair.tier, "similar");
  }
});

test("missing coverage and compared, different independent fields produce different outcomes", () => {
  const missing = getCase("missing").pairs[0].rows;
  const different = getCase("none").pairs[0].rows;
  assert.equal(missing[0].left, different[0].left);
  assert.equal(missing[2].left, "Brak pola");
  assert.match(different[2].left, /^https:\/\/[^/]+\.example\//);
  assert.notEqual(different[2].left, different[2].right);
});
