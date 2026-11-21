// Cloudflare Pages Function：/api/* 反向代理到 Netlify 后端
// 目的：两端默认使用 pages.dev（访问更快、更稳），数据仍存于 Netlify Blobs，
// 避免迁移存储导致现有绑定失效。Cloudflare 端只做透传，不解析内容。
const ORIGIN = "https://classmanagement.de5.net";

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const target = ORIGIN + url.pathname + url.search;
  const headers = new Headers(context.request.headers);
  headers.delete("host");
  headers.delete("content-length");
  headers.set("X-Forwarded-Host", url.host);

  const init = { method: context.request.method, headers, redirect: "manual" };
  if (!["GET", "HEAD"].includes(context.request.method)) {
    init.body = context.request.body;
  }

  const res = await fetch(target, init);
  const out = new Headers(res.headers);
  out.delete("content-encoding");
  out.delete("content-length");
  out.delete("transfer-encoding");
  return new Response(res.body, { status: res.status, headers: out });
}
