import test from "node:test";
import assert from "node:assert/strict";

function installWindowStub() {
  const data = new Map();
  globalThis.window = {
    localStorage: {
      getItem: (key) => data.get(key) ?? null,
      setItem: (key, value) => data.set(key, String(value)),
      removeItem: (key) => data.delete(key),
    },
    prompt: () => null,
    confirm: () => false,
  };
}

test("newSession catches API failures and reports them through appError", async () => {
  installWindowStub();
  globalThis.fetch = async (url, options = {}) => {
    if (url === "/api/sessions" && options.method === "POST") {
      return new Response(JSON.stringify({ detail: "session write failed" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);
  useAppStore.setState({ activeModuleId: "literature_search", appError: null });

  const created = await useAppStore.getState().newSession("literature_search");

  assert.equal(created, null);
  assert.equal(useAppStore.getState().appError.message, "新建会话失败：session write failed");
});
