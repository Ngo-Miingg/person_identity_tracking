const debugPort = process.env.PIT_CHROME_DEBUG_PORT || "9223";
const appUrl = process.env.PIT_APP_URL || "http://127.0.0.1:5173/";
const operatorKey = process.env.PIT_API_KEY || "pit-secure-local-operator-key-2026";
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const target = await fetch(
  `http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(appUrl)}`,
  { method: "PUT" },
).then((response) => response.json());
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});

let sequence = 0;
const pending = new Map();
const requests = [];
socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const operation = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) operation.reject(new Error(JSON.stringify(message.error)));
    else operation.resolve(message.result);
  }
  if (message.method === "Network.requestWillBeSent") {
    requests.push(message.params.request.url);
  }
};

function call(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const response = await call("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}

async function waitFor(expression, timeout = 12000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await evaluate(expression)) return;
    await sleep(150);
  }
  throw new Error(`Timed out waiting for: ${expression}`);
}

try {
  await call("Page.enable");
  await call("Runtime.enable");
  await call("Network.enable");
  await call("Page.navigate", { url: appUrl });
  await waitFor("document.readyState === 'complete'");
  await waitFor("!!document.querySelector('#operator-token') || !!document.querySelector('.app-header')");
  if (await evaluate("!!document.querySelector('#operator-token')")) {
    await evaluate(`(() => {
      const input = document.querySelector('#operator-token');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(operatorKey)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('form').requestSubmit();
      return true;
    })()`);
  }
  await waitFor("!!document.querySelector('.app-header')");
  await waitFor("document.querySelectorAll('.session-select option').length >= 3");

  const ids = await evaluate(
    "Array.from(document.querySelectorAll('.session-select option')).map((option) => option.value).filter(Boolean).slice(0, 3)",
  );
  if (ids.length < 3) throw new Error("At least three jobs are required for the switch test");

  await evaluate("location.hash = '#view=identities&job=missing-e2e-job'");
  await waitFor("document.body.innerText.includes('Job not found')");
  await call("Page.reload", { ignoreCache: true });
  await sleep(1000);
  await waitFor("document.readyState === 'complete'");
  await waitFor("document.body.innerText.includes('Job not found')");
  const missing = await evaluate(
    "({ hash: location.hash, showsRequestedId: document.body.innerText.includes('missing-e2e-job') })",
  );

  await evaluate(`location.hash = '#view=identities&job=${ids[0]}'`);
  await sleep(80);
  await evaluate(`location.hash = '#view=pipeline&job=${ids[1]}'`);
  await sleep(80);
  await evaluate(`location.hash = '#view=archive&job=${ids[2]}'`);
  await sleep(80);
  await evaluate(`location.hash = '#view=identities&job=${ids[0]}'`);
  await waitFor(`document.querySelector('.session-select')?.value === '${ids[0]}'`);
  await sleep(1200);
  const switched = await evaluate(
    "({ hash: location.hash, selected: document.querySelector('.session-select')?.value, hasLoadError: document.body.innerText.includes('Failed to Load') })",
  );

  await evaluate("location.hash = '#view=archive&job=0ffadbe2abc3'");
  await waitFor("document.querySelector('.session-select')?.value === '0ffadbe2abc3'");
  await sleep(700);
  const archive = await evaluate(
    "({ hash: location.hash, selected: document.querySelector('.session-select')?.value, hasJob: document.body.innerText.includes('0ffadbe2abc3'), hasLog: document.body.innerText.includes('Console Log:') })",
  );

  requests.length = 0;
  await evaluate("location.hash = '#view=live&job=0ffadbe2abc3'");
  await waitFor("!!document.querySelector('video')");
  await sleep(6000);
  const replay = await evaluate(`(() => {
    const video = document.querySelector('video');
    return {
      hash: location.hash,
      selected: document.querySelector('.session-select')?.value,
      controls: video?.controls,
      rate: video?.playbackRate,
      src: video?.currentSrc || video?.src,
    };
  })()`);
  const apiCounts = {};
  for (const url of requests.filter((value) => value.includes("/api/"))) {
    const path = new URL(url).pathname;
    apiCounts[path] = (apiCounts[path] || 0) + 1;
  }

  console.log(JSON.stringify({ ids, missing, switched, archive, replay, apiCounts }, null, 2));
} finally {
  await call("Page.close").catch(() => undefined);
  socket.close();
}
