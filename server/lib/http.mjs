// 通用 HTTP 小工具 + 设备鉴权。
import { createHash, timingSafeEqual, randomBytes, randomUUID } from "node:crypto";
import { store } from "./store.mjs";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

export function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

export function fail(message, status = 400) {
  return json({ ok: false, error: message }, status);
}

export function hashSecret(secret) {
  return createHash("sha256").update(String(secret)).digest("hex");
}

export function newSecret() {
  return randomBytes(32).toString("base64url");
}

export function newId() {
  return randomUUID();
}

function safeEqual(a, b) {
  const left = Buffer.from(String(a));
  const right = Buffer.from(String(b));
  if (left.length !== right.length) return false;
  return timingSafeEqual(left, right);
}

export function bearer(req) {
  const raw = req.headers.get("authorization") || "";
  return raw.startsWith("Bearer ") ? raw.slice(7).trim() : "";
}

/**
 * 校验 X-Device-Id / Authorization: Bearer <secret>。
 * 返回 { id, dev } 或 null。
 */
export async function authenticate(req) {
  const id = (req.headers.get("x-device-id") || "").trim();
  const secret = bearer(req);
  if (!id || !secret) return null;
  const s = await store();
  const dev = await s.get(`dev/${id}`, { type: "json" });
  if (!dev || !dev.secretHash) return null;
  if (!safeEqual(hashSecret(secret), dev.secretHash)) return null;
  return { id, dev };
}

export async function readJson(req) {
  try {
    const text = await req.text();
    if (!text) return {};
    const data = JSON.parse(text);
    return data && typeof data === "object" ? data : {};
  } catch {
    return null;
  }
}

/**
 * 取一台电脑的绑定信息；不存在时返回 null。
 */
export async function pcMeta(pcId) {
  const s = await store();
  const meta = await s.get(`pc/${pcId}/meta`, { type: "json" });
  if (!meta) return null;
  if (!Array.isArray(meta.phones)) meta.phones = [];
  return meta;
}

export function findPhone(meta, phoneId) {
  return meta && meta.phones.find((p) => p.phoneId === phoneId);
}

export function publicPhone(entry) {
  return {
    phoneId: entry.phoneId,
    name: entry.name || "",
    confirm: !!entry.confirm,
    addedAt: entry.addedAt || 0,
  };
}
