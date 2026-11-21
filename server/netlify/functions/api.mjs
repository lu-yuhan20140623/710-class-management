// 课程表云同步后端：设备注册、手机↔电脑配对、加密快照与指令中转。
//
// 设计要点：
//  - 服务端只存“密文 + 公钥”，快照与指令的明文永远不离开两端（沿用两端现有的
//    DH + AES-256-GCM 方案）。
//  - 一台电脑（PC）只有一个“确认设备”（confirm=true），其余手机只读；
//    换绑必须由电脑端先验证教师密钥，再带 replace=true 调这里。
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

// ---------------- 配对 ----------------
async function createPairRequest(req) {
  const auth = await authenticate(req);
  if (!auth) return fail("设备未授权", 401);
  if (auth.dev.kind !== "phone") return fail("仅手机端可发起绑定", 403);

  const body = await readJson(req);
  if (!body) return fail("请求体不是合法 JSON");
  const pcId = String(body.pcId || "").trim();
  const pub = String(body.pub || "").trim();
  if (!pcId || !pub) return fail("缺少 pcId 或 pub");

  const s = await store();
  const pcDev = await s.get(`dev/${pcId}`, { type: "json" });
  if (!pcDev || pcDev.kind !== "pc") return fail("电脑端未注册", 404);

  const meta = await pcMeta(pcId);
  const bound = meta ? findPhone(meta, auth.id) : null;
  if (bound) {
    // 已绑定过：直接算成功，省得重复弹窗
    return json({ ok: true, requestId: "", status: "approved", pcPub: bound.pub || "" });
  }

  const requestId = newId();
  await s.setJSON(`pair/${pcId}/${requestId}`, {
    requestId,
    pcId,
    pcName: pcDev.name || "",
    phoneId: auth.id,
    phoneName: auth.dev.name || "",
    pub,
    status: "pending",
    pcPub: "",
    createdAt: Date.now(),
  });
  return json({ ok: true, requestId, status: "pending" });
}

async function pendingRequests(req, pcId) {
  const guard = await requirePc(req, pcId);
  if (guard.error) return guard.error;

  const now = Date.now();
  const items = await listJson(`pair/${pcId}/`);
  const s = await store();
  const requests = [];
  for (const { key, data } of items) {
    if (data.status !== "pending") continue;
    if (now - (data.createdAt || 0) > PAIR_TTL_MS) {
      data.status = "expired";
      await s.setJSON(key, data);
      continue;
    }
    requests.push({
      requestId: data.requestId,
      phoneId: data.phoneId,
      phoneName: data.phoneName || "",
      pub: data.pub,
      createdAt: data.createdAt,
    });
  }
  requests.sort((a, b) => b.createdAt - a.createdAt);
  return json({ ok: true, requests });
}

async function decidePair(req, pcId, requestId) {
  const guard = await requirePc(req, pcId);
  if (guard.error) return guard.error;

  const body = await readJson(req);
  if (!body) return fail("请求体不是合法 JSON");
  const approve = body.approve === true;
  const pub = String(body.pub || "").trim();
  const replace = body.replace === true;

  const s = await store();
  const key = `pair/${pcId}/${requestId}`;
  const request = await s.get(key, { type: "json" });
  if (!request) return fail("绑定申请不存在", 404);
  if (request.status !== "pending") return fail("该申请已处理", 409);
  if (approve && !pub) return fail("同意绑定时必须带上电脑端公钥");

  const meta = (await pcMeta(pcId)) || {
    name: request.pcName || "",
    createdAt: Date.now(),
    phones: [],
  };

  if (approve) {
    const confirmPhone = meta.phones.find((p) => p.confirm);
    const isReplacing = !!(confirmPhone && confirmPhone.phoneId !== request.phoneId && replace);
    if (isReplacing) {
      // 换绑：旧确认设备立即失效，连它的快照和指令一起清掉
      meta.phones = meta.phones.filter((p) => p.phoneId !== confirmPhone.phoneId);
      await s.delete(`snap/${pcId}/${confirmPhone.phoneId}`);
      for (const item of await listJson(`act/${pcId}/`)) {
        if (item.data.phoneId === confirmPhone.phoneId) {
          await s.delete(item.key);
        }
      }
    }
    const existing = meta.phones.find((p) => p.phoneId === request.phoneId);
    if (existing) {
      // phones[].pub 必须是手机的公钥，电脑靠它派生会话密钥
      existing.pub = request.pub;
      existing.name = request.phoneName || existing.name || "";
      if (isReplacing) existing.confirm = true;
    } else {
      meta.phones.push({
        phoneId: request.phoneId,
        name: request.phoneName || "",
        pub: request.pub,
        // 已有确认设备时，新加入的手机只能只读
        confirm: isReplacing || !meta.phones.some((p) => p.confirm),
        addedAt: Date.now(),
      });
    }
    await s.setJSON(`pc/${pcId}/meta`, meta);
    request.status = "approved";
    request.pcPub = pub;
  } else {
    request.status = "denied";
  }
  request.decidedAt = Date.now();
  await s.setJSON(key, request);
  return json({ ok: true, status: request.status });
}

async function pairStatus(req, pcId, requestId) {
  const guard = await requirePhone(req);
  if (guard.error) return guard.error;

  const s = await store();
  const request = await s.get(`pair/${pcId}/${requestId}`, { type: "json" });
  if (!request) return fail("绑定申请不存在", 404);
  if (request.phoneId !== guard.auth.id) return fail("无权查看该申请", 403);
  if (request.status === "pending" && Date.now() - (request.createdAt || 0) > PAIR_TTL_MS) {
    request.status = "expired";
    await s.setJSON(`pair/${pcId}/${requestId}`, request);
  }
  return json({
    ok: true,
    status: request.status,
    pcPub: request.pcPub || "",
    pcName: request.pcName || "",
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
    if (seg[0] === "pair") {
      if (seg.length === 2 && seg[1] === "request" && method === "POST") {
        return await createPairRequest(req);
      }
      if (seg.length === 2 && seg[1] === "requests" && method === "GET") {
        const auth = await authenticate(req);
        if (!auth || auth.dev.kind !== "pc") return fail("设备未授权", 401);
        return await pendingRequests(req, auth.id);
      }
      if (seg.length === 3 && seg[1] === "requests" && method === "GET") {
        const pcId = String(new URL(req.url).searchParams.get("pcId") || "").trim();
        if (!pcId) return fail("缺少 pcId");
        return await pairStatus(req, pcId, seg[2]);
      }
      if (seg.length === 4 && seg[1] === "requests" && method === "POST" && seg[3] === "decide") {
        const auth = await authenticate(req);
        if (!auth || auth.dev.kind !== "pc") return fail("设备未授权", 401);
        return await decidePair(req, auth.id, seg[2]);
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
