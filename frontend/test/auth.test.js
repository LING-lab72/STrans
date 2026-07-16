import assert from "node:assert/strict";
import test from "node:test";

import { CAPTCHA_RETRY_DELAYS_MS, fetchCaptchaWithRetry, initialAuthForm } from "../src/auth.js";

test("login form never embeds a default password", () => {
  assert.deepEqual(initialAuthForm(), { username: "admin", password: "", captcha_code: "" });
});

test("captcha retry uses the declared 1s, 2s and 4s backoff schedule", async () => {
  const waits = [];
  let attempts = 0;

  const result = await fetchCaptchaWithRetry(
    async () => {
      attempts += 1;
      if (attempts < 4) throw new Error(`temporary-${attempts}`);
      return { captcha_id: "captcha-1", image: "data:image/svg+xml;base64,test" };
    },
    { wait: async (delay) => waits.push(delay) },
  );

  assert.deepEqual(CAPTCHA_RETRY_DELAYS_MS, [1000, 2000, 4000]);
  assert.equal(attempts, 4);
  assert.deepEqual(waits, [1000, 2000, 4000]);
  assert.equal(result.captcha_id, "captcha-1");
});

test("captcha retry stops immediately after a successful request", async () => {
  const waits = [];

  const result = await fetchCaptchaWithRetry(
    async () => ({ captcha_id: "captcha-ready", image: "ready" }),
    { wait: async (delay) => waits.push(delay) },
  );

  assert.equal(result.captcha_id, "captcha-ready");
  assert.deepEqual(waits, []);
});

test("captcha retry surfaces the last failure after all attempts", async () => {
  const waits = [];
  let attempts = 0;

  await assert.rejects(
    fetchCaptchaWithRetry(
      async () => {
        attempts += 1;
        throw new Error(`captcha-unavailable-${attempts}`);
      },
      { wait: async (delay) => waits.push(delay) },
    ),
    /captcha-unavailable-4/,
  );

  assert.equal(attempts, 4);
  assert.deepEqual(waits, [1000, 2000, 4000]);
});
