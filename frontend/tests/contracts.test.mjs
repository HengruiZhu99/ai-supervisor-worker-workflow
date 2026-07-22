import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const sourceRoot = new URL("../src/", import.meta.url);
const source = (
  await Promise.all(
    (await readdir(sourceRoot))
      .filter((name) => /\.tsx?$/.test(name))
      .map((name) => readFile(new URL(name, sourceRoot), "utf8")),
  )
).join("\n");
const built = await readFile(
  new URL("../../src/aiflow/api/static/app.js", import.meta.url),
  "utf8",
);

test("frontend exposes the progressive Solo-first contract", () => {
  for (const marker of [
    "Solo TDD",
    "Autonomous Program",
    "Export handoff",
    "EventSource",
  ]) {
    assert.match(source, new RegExp(marker));
  }
  assert.doesNotMatch(source, /dangerouslySetInnerHTML|\beval\s*\(/);
});

test("built runtime is bundled and Node-free", () => {
  assert.ok(built.length > 1_000);
  assert.doesNotMatch(built, /from\s+["']react["']/);
  assert.match(built, /EventSource/);
});
