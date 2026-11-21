// 课程表云同步后端：设备注册、手机↔电脑配对、加密快照与指令中转。
//
// 设计要点：
//  - 服务端只存“密文 + 公钥”，快照与指令的明文永远不离开两端（沿用两端现有的
//    DH + AES-256-GCM 方案）。
//  - 绑定由电脑端发起：电脑输入手机设备 ID，手机端弹窗同意后才生效。
//  - 一台电脑只保留一台手机（confirm 设备）；换绑需电脑端先验证教师密钥，
//    再带 replace=true 调用。
//  - 手机可绑定多台电脑，但同一时刻只订阅其中一台。
import {
  authenticate, fail, findPhone, hashSecret, json, newId, newSecret,
  pcMeta, publicPhone, readJson,
} from "../../lib/http.mjs";
import { store } from "../../lib/store.mjs";

export const config = { path: "/api/*" };

const PAIR_TTL_MS = 10 * 60 * 1000;
const MAX_ACTIONS = 20;

function pathOf(req) {
  let path = new URL(req.url).pathname;
  for (const prefix of ["/.netlify/functions/api", "/api"]) {
    if (path === prefix) return "/";
    if (path.startsWith(prefix + "/")) {
      path = path.slice(prefix.length);
      break;
    }
  }
  return path;
}

async function requirePc(req, pcId) {
  const auth = await authenticate(req);
  if (!auth) return { error: fail("设备未授权", 401) };
  if (auth.dev.kind !== "pc") return { error: fail("仅电脑端可调用", 403) };
  if (auth.id !== pcId) return { error: fail("设备 ID 不匹配", 403) };
  return { auth };
}

async function requirePhone(req) {
  const auth = await authenticate(req);
  if (!auth) return { error: fail("设备未授权", 401) };
  if (auth.dev.kind !== "phone") return { error: fail("仅手机端可调用", 403) };
  return { auth };
}

async function listJson(prefix) {
  const s = await store();
  const keys = await s.listAll(prefix);
  const items = [];
  for (const key of keys) {
    const data = await s.get(key, { type: "json" });
    if (data) items.push({ key, data });
  }
  return items;
}

// ---------------- 设备 ----------------
async function register(req) {
  const body = await readJson(req);
  if (!body) return fail("请求体不是合法 JSON");
  const kind = body.kind === "pc" ? "pc" : body.kind === "phone" ? "phone" : "";
  if (!kind) return fail("kind 必须是 pc 或 phone");

  const id = newId();
  const secret = newSecret();
  const dev = {
    id,
    kind,
    name: String(body.name || "").slice(0, 32),
    secretHash: hashSecret(secret),
    createdAt: Date.now(),
  };
  const s = await store();
  await s.setJSON(`dev/${id}`, dev);
  return json({ ok: true, deviceId: id, secret, kind });
}

// ---------------- 绑定（电脑输入手机 ID → 手机确认） ----------------
async function createBind(req) {
  const auth = await authenticate(req);
  if (!auth) return fail("设备未授权", 401);
  if (auth.dev.kind !== "pc") return fail("仅电脑端可发起绑定", 403);

  const body = await readJson(req);
  if (!body) return fail("请求体不是合法 JSON");
  const phoneId = String(body.phoneId || "").trim();
  const pub = String(body.pub || "").trim();
  if (!phoneId || !pub) return fail("缺少 phoneId 或 pub");

  const s = await store();
  const phoneDev = await s.get(`dev/${phoneId}`, { type: "json" });
  if (!phoneDev || phoneDev.kind !== "phone") return fail("手机端未注册", 404);

  const meta = (await pcMeta(auth.id)) || {
    name: auth.dev.name || "",
    createdAt: Date.now(),
    phones: [],
  };
  const bound = findPhone(meta, phoneId);
  if (bound) {
    // 这台手机之前就绑定过：直接更新公钥，不用再确认
    bound.pub = pub;
    bound.confirm = true;
    await s.setJSON(`pc/${auth.id}/meta`, meta);
    return json({
      ok: true, requestId: "", status: "approved",
      phoneName: bound.name || "", pcName: meta.name || "",
    });
  }

  const confirmPhone = meta.phones.find((p) => p.confirm);
  if (confirmPhone && confirmPhone.phoneId !== phoneId && body.replace !== true) {
    return fail("已有确认设备，换绑需先在电脑端验证教师密钥", 409);
  }

  const requestId = newId();
  await s.setJSON(`req/${phoneId}/${requestId}`, {
    requestId,
    pcId: auth.id,
    pcName: meta.name || "",
    phoneId,
    phoneName: phoneDev.name || "",
    pcPub: pub,
    replace: body.replace === true,
    status: "pending",
    createdAt: Date.now(),
  });
  return json({ ok: true, requestId, status: "pending" });
}

async function bindStatus(req, phoneId, requestId) {
  const auth = await authenticate(req);
  if (!auth || auth.dev.kind !== "pc") return fail("设备未授权", 401);

  const s = await store();
  const request = await s.get(`req/${phoneId}/${requestId}`, { type: "json" });
  if (!request || request.pcId !== auth.id) return fail("绑定申请不存在", 404);
  if (request.status === "pending" && Date.now() - (request.createdAt || 0) > PAIR_TTL_MS) {
    request.status = "expired";
    await s.setJSON(`req/${phoneId}/${requestId}`, request);
  }
  return json({
    ok: true,
    status: request.status,
    phoneName: request.phoneName || "",
    pcName: request.pcName || "",
  });
}

async function phoneInbox(req) {
  const guard = await requirePhone(req);
  if (guard.error) return guard.error;

  const now = Date.now();
  const s = await store();
  const requests = [];
  for (const { key, data } of await listJson(`req/${guard.auth.id}/`)) {
    if (data.status !== "pending") continue;
    if (now - (data.createdAt || 0) > PAIR_TTL_MS) {
      data.status = "expired";
      await s.setJSON(key, data);
      continue;
    }
    requests.push({
      requestId: data.requestId,
      pcId: data.pcId,
      pcName: data.pcName || "",
      pcPub: data.pcPub || "",
      createdAt: data.createdAt,
    });
  }
  requests.sort((a, b) => b.createdAt - a.createdAt);
  return json({ ok: true, requests });
}

async function decideBind(req, requestId) {
  const auth = await authenticate(req);
  if (!auth) return fail("设备未授权", 401);
  if (auth.dev.kind !== "phone") return fail("仅手机端可确认绑定", 403);

  const body = await readJson(req);
  if (!body) return fail("请求体不是合法 JSON");
  const approve = body.approve === true;
  const pub = String(body.pub || "").trim();
  if (approve && !pub) return fail("同意绑定时必须带上手机公钥");

  const s = await store();
  const key = `req/${auth.id}/${requestId}`;
  const request = await s.get(key, { type: "json" });
  if (!request) return fail("绑定申请不存在", 404);
  if (request.status !== "pending") return fail("该申请已处理", 409);

  if (!approve) {
    request.status = "denied";
    request.decidedAt = Date.now();
    await s.setJSON(key, request);
    return json({ ok: true, status: "denied" });
  }

  const pcId = request.pcId;
  const meta = (await pcMeta(pcId)) || {
    name: request.pcName || "",
    createdAt: Date.now(),
    phones: [],
  };
  // 一台电脑只保留一台手机：其余设备连同快照、指令一起清掉
  for (const p of meta.phones) {
    if (p.phoneId === auth.id) continue;
    await s.delete(`snap/${pcId}/${p.phoneId}`);
    for (const item of await listJson(`act/${pcId}/`)) {
      if (item.data.phoneId === p.phoneId) await s.delete(item.key);
    }
  }
  meta.phones = [{
    phoneId: auth.id,
    name: auth.dev.name || request.phoneName || "",
    pub,
    confirm: true,
    addedAt: Date.now(),
  }];
  await s.setJSON(`pc/${pcId}/meta`, meta);

  request.status = "approved";
  request.decidedAt = Date.now();
  await s.setJSON(key, request);
  return json({
    ok: true, status: "approved",
    pcId, pcName: meta.name || "", pcPub: request.pcPub,
  });
}

// ---------------- 已绑定手机管理 ----------------
async function listPhones(req, pcId) {
  const guard = await requirePc(req, pcId);
  if (guard.error) return guard.error;
  const meta = await pcMeta(pcId);
  // pub 是手机端的 DH 公钥，电脑要靠它派生各自的会话密钥
  const phones = meta
    ? meta.phones.map((p) => ({ ...publicPhone(p), pub: p.pub || "" }))
    : [];
  return json({ ok: true, phones });
}

async function revokePhone(req, pcId, phoneId) {
  const guard = await requirePc(req, pcId);
  if (guard.error) return guard.error;

  const meta = await pcMeta(pcId);
  if (!meta) return fail("电脑端未初始化", 404);
  meta.phones = meta.phones.filter((p) => p.phoneId !== phoneId);
  const s = await store();
  await s.setJSON(`pc/${pcId}/meta`, meta);
  await s.delete(`snap/${pcId}/${phoneId}`);
  for (const item of await listJson(`act/${pcId}/`)) {
    if (item.data.phoneId === phoneId) await s.delete(item.key);
  }
  return json({ ok: true });
}

// ---------------- 快照 ----------------
async function putSnapshot(req, pcId, phoneId) {
  const guard = await requirePc(req, pcId);
  if (guard.error) return guard.error;

  const meta = await pcMeta(pcId);
  if (!meta || !findPhone(meta, phoneId)) return fail("该手机未绑定", 403);

  const body = await readJson(req);
  if (!body) return fail("请求体不是合法 JSON");
  const cipher = String(body.cipher || "");
  if (!cipher) return fail("缺少 cipher");

  const s = await store();
  await s.setJSON(`snap/${pcId}/${phoneId}`, {
    cipher,
    version: String(body.version || ""),
    updatedAt: Date.now(),
  });
  return json({ ok: true });
}

async function getSnapshot(req, pcId) {
  const guard = await requirePhone(req);
  if (guard.error) return guard.error;

  const meta = await pcMeta(pcId);
  if (!meta || !findPhone(meta, guard.auth.id)) return fail("未绑定该电脑", 403);

  const s = await store();
  const snap = await s.get(`snap/${pcId}/${guard.auth.id}`, { type: "json" });
  if (!snap) return json({ ok: true, exists: false });
  return json({ ok: true, exists: true, cipher: snap.cipher, version: snap.version, updatedAt: snap.updatedAt });
}

// ---------------- 手机 -> 电脑 指令 ----------------
async function postAction(req, pcId) {
  const guard = await requirePhone(req);
  if (guard.error) return guard.error;

  const meta = await pcMeta(pcId);
  if (!meta || !findPhone(meta, guard.auth.id)) return fail("未绑定该电脑", 403);

  const body = await readJson(req);
  if (!body) return fail("请求体不是合法 JSON");
  const cipher = String(body.cipher || "");
  if (!cipher) return fail("缺少 cipher");

  const s = await store();
  const id = newId();
  await s.setJSON(`act/${pcId}/${id}`, {
    id,
    phoneId: guard.auth.id,
    cipher,
    createdAt: Date.now(),
  });
  return json({ ok: true, id });
}

async function listActions(req, pcId) {
  const guard = await requirePc(req, pcId);
  if (guard.error) return guard.error;

  const items = await listJson(`act/${pcId}/`);
  const actions = items
    .map(({ data }) => data)
    .sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0))
    .slice(0, MAX_ACTIONS)
    .map((a) => ({ id: a.id, phoneId: a.phoneId, cipher: a.cipher, createdAt: a.createdAt }));
  return json({ ok: true, actions });
}

async function deleteAction(req, pcId, actionId) {
  const guard = await requirePc(req, pcId);
  if (guard.error) return guard.error;
  await (await store()).delete(`act/${pcId}/${actionId}`);
  return json({ ok: true });
}

// ---------------- 路由 ----------------
export default async function handler(req) {
  try {
    const seg = pathOf(req).split("/").filter(Boolean);
    const method = req.method.toUpperCase();

    if (seg.length === 1 && seg[0] === "health") {
      return json({ ok: true, service: "class-schedule-relay", time: Date.now() });
    }
    if (seg.length === 1 && seg[0] === "register" && method === "POST") {
      return await register(req);
    }
    if (seg[0] === "bind" && seg.length === 1 && method === "POST") {
      return await createBind(req);
    }
    if (seg[0] === "bind" && seg.length === 3 && method === "GET") {
      return await bindStatus(req, seg[1], seg[2]);
    }
    if (seg[0] === "pair" && seg[1] === "inbox") {
      if (seg.length === 2 && method === "GET") {
        return await phoneInbox(req);
      }
      if (seg.length === 4 && seg[3] === "decide" && method === "POST") {
        return await decideBind(req, seg[2]);
      }
    }
    if (seg[0] === "pc" && seg.length >= 3) {
      const pcId = seg[1];
      if (seg[2] === "phones" && seg.length === 3 && method === "GET") {
        return await listPhones(req, pcId);
      }
      if (seg[2] === "phones" && seg.length === 4 && method === "DELETE") {
        return await revokePhone(req, pcId, seg[3]);
      }
      if (seg[2] === "snapshot" && seg.length === 4 && method === "PUT") {
        return await putSnapshot(req, pcId, seg[3]);
      }
      if (seg[2] === "snapshot" && seg.length === 3 && method === "GET") {
        return await getSnapshot(req, pcId);
      }
      if (seg[2] === "actions" && seg.length === 3) {
        if (method === "POST") return await postAction(req, pcId);
        if (method === "GET") return await listActions(req, pcId);
      }
      if (seg[2] === "actions" && seg.length === 4 && method === "DELETE") {
        return await deleteAction(req, pcId, seg[3]);
      }
    }
    return fail("接口不存在", 404);
  } catch (err) {
    console.error("[api]", err);
    return fail("服务器内部错误", 500);
  }
}
