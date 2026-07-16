import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { resolveRoadModelerUrl, roadModelerLinkAttributes } from "../src/roadModeler.js";

test("road modeler integration targets the vendored same-origin page", () => {
  assert.equal(resolveRoadModelerUrl("/"), "/road_logic_modeler/index.html");
  assert.equal(resolveRoadModelerUrl("/strans/"), "/strans/road_logic_modeler/index.html");
});

test("road modeler opens in an isolated browser tab", () => {
  assert.deepEqual(roadModelerLinkAttributes(), {
    href: "/road_logic_modeler/index.html",
    target: "_blank",
    rel: "noopener noreferrer",
  });
});

test("road modeler page and every declared core asset ship with the frontend", async () => {
  const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const publicRoot = resolve(frontendRoot, "public", "road_logic_modeler");
  const index = await readFile(resolve(publicRoot, "index.html"), "utf8");

  assert.match(index, /<title>道路逻辑建模工具<\/title>/);
  for (const asset of ["styles.css", "src/geometry.js", "src/model.js", "src/renderer.js", "src/app.js"]) {
    const content = await readFile(resolve(publicRoot, asset), "utf8");
    assert.ok(content.length > 0, `${asset} should not be empty`);
    assert.match(index, new RegExp(asset.replace(".", "\\.")));
  }
});
