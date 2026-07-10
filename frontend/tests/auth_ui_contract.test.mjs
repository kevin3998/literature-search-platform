import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("auth screen contains login and registration forms", async () => {
  const source = await readFile(new URL("../src/components/AuthScreen.jsx", import.meta.url), "utf8");

  assert.match(source, /authLogin/);
  assert.match(source, /authSignup/);
  assert.match(source, /email/);
  assert.match(source, /password/);
  assert.match(source, /display_name|displayName/);
});
