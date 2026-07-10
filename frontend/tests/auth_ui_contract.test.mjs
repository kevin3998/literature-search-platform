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

test("account settings uses real current user and exposes api tokens", async () => {
  const source = await readFile(new URL("../src/components/SettingsModal.jsx", import.meta.url), "utf8");

  assert.doesNotMatch(source, /ACCOUNT_PLACEHOLDER/);
  assert.match(source, /currentUser/);
  assert.match(source, /apiTokens|API token|API Token|API Token/);
  assert.match(source, /changePassword|修改密码/);
});

test("admin users modal contains filters and complete explicit actions", async () => {
  const source = await readFile(new URL("../src/components/AdminUsersModal.jsx", import.meta.url), "utf8");

  assert.match(source, /adminUsers/);
  assert.match(source, /includeSystem|显示系统身份/);
  assert.match(source, /query|搜索/);
  assert.match(source, /account_type|accountType|账号类型/);
  assert.match(source, /role/);
  assert.match(source, /status/);
  assert.match(source, /editDisplayName|编辑显示名/);
  assert.match(source, /resetPassword|重置密码/);
  assert.match(source, /revokeSessions|撤销会话/);
  assert.match(source, /revokeApiTokens|撤销 API/);
  assert.match(source, /window\.confirm/);
  assert.match(source, /disabled|禁用/);
  assert.doesNotMatch(source, /<select className="form-input h-8 py-1"/);
});
