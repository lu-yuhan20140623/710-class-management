// 本地开发服务器：不依赖 Netlify CLI，直接跑 functions/api.mjs。
// 存储落在 server/.data/，接口与线上完全一致。
import http from "node:http";
import { fileURLToPath } from "node:url";
import handler from "./netlify/functions/api.mjs";

const PORT = Number(process.env.PORT || 8787);
process.env.STORE_DIR ||= fileURLToPath(new URL("./.data/", import.meta.url));

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || `127.0.0.1:${PORT}`}`);
  const body = req.method === "GET" || req.method === "HEAD" ? undefined : await readBody(req);
  const headers = new Headers();
  for (const [key, value] of Object.entries(req.headers)) {
    if (typeof value === "string") headers.set(key, value);
  }

  let response;
  try {
    response = await handler(new Request(url, { method: req.method, headers, body }));
  } catch (err) {
    console.error(err);
    res.writeHead(500, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: false, error: "本地服务器异常" }));
    return;
  }

  const text = await response.text();
  res.writeHead(response.status, Object.fromEntries(response.headers));
  res.end(text);
});

server.listen(PORT, () => {
  console.log(`API dev server: http://127.0.0.1:${PORT}/api/health`);
});
