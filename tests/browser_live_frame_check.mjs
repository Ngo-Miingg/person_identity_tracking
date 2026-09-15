import crypto from "node:crypto";

const target = await fetch("http://127.0.0.1:9224/json/new?http%3A%2F%2F127.0.0.1%3A5173%2F%23view%3Dlive%26job%3D340c64a74470", { method: "PUT" }).then((r) => r.json());
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let id = 0;
const pending = new Map();
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const operation = pending.get(message.id);
    pending.delete(message.id);
    message.error ? operation.reject(new Error(JSON.stringify(message.error))) : operation.resolve(message.result);
  }
};
const call = (method, params = {}) => new Promise((resolve, reject) => {
  const requestId = ++id;
  pending.set(requestId, { resolve, reject });
  ws.send(JSON.stringify({ id: requestId, method, params }));
});
const evaluate = async (expression) => (await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
await call("Page.enable");
await call("Runtime.enable");
await call("Page.navigate", { url: "http://127.0.0.1:5173/#view=live&job=340c64a74470" });
await new Promise((resolve) => setTimeout(resolve, 6000));
const samples = [];
for (let i = 0; i < 4; i += 1) {
  const screenshot = await call("Page.captureScreenshot", { format: "png" });
  samples.push({
    screenshot: crypto.createHash("md5").update(Buffer.from(screenshot.data, "base64")).digest("hex"),
    dom: await evaluate("(() => { const image = document.querySelector('.live-viewport img'); return { src: image?.src, complete: image?.complete, width: image?.naturalWidth, height: image?.naturalHeight, text: document.body.innerText.includes('No media available for this job') }; })()"),
  });
  await new Promise((resolve) => setTimeout(resolve, 2000));
}
console.log(JSON.stringify(samples, null, 2));
await call("Page.close").catch(() => undefined);
ws.close();
