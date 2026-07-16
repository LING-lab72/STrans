export const CAPTCHA_RETRY_DELAYS_MS = Object.freeze([1000, 2000, 4000]);

export const initialAuthForm = () => ({ username: "admin", password: "", captcha_code: "" });

const defaultWait = (delay) => new Promise((resolve) => window.setTimeout(resolve, delay));

export async function fetchCaptchaWithRetry(fetchCaptcha, options = {}) {
  const delays = options.delays || CAPTCHA_RETRY_DELAYS_MS;
  const wait = options.wait || defaultWait;
  let lastError;

  for (let attempt = 0; attempt <= delays.length; attempt += 1) {
    try {
      return await fetchCaptcha();
    } catch (error) {
      lastError = error;
      if (attempt === delays.length) break;
      await wait(delays[attempt]);
    }
  }

  throw lastError;
}
