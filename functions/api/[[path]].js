// Cloudflare Pages Function：云同步中继 API（D1 存储）
// 路径与参数与旧 Netlify 后端完全一致，电脑端 / 手机端无需改动。
//
// 存储：D1 绑定 RELAY_DB，单表 kv(k, v)，v 为 JSON 文本；键名沿用
//   dev/<id>、pc/<id>/meta、req/<phoneId>/<requestId>、snap/<pcId>/<phoneId>、act/<pcId>/<actionId>
// 服务端只存“密文 + 公钥”，快照与指令的明文不离开两端。
const PAIR_TTL_MS = 10 * 60 * 1000;
const MAX_ACTIONS = 20;

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function fail(message, status = 400) {
  return json({ ok: false, error: message }, status);
}

// ---------------- 存储（D1） ----------------
let schemaReady = null;

function ready(env) {
  if (!env.RELAY_DB) throw new Error("未配置 RELAY_DB 绑定");
  if (!schemaReady) {
    schemaReady = env.RELAY_DB
      .prepare("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
      .run()
      .catch((err) => {
        schemaReady = null;
        throw err;
      });
  }
  return schemaReady.then(() => env.RELAY_DB);
}

async function dbGet(env, key) {
  const db = await ready(env);
  const row = await db.prepare("SELECT v FROM kv WHERE k = ?").bind(key).first();
  if (!row || typeof row.v !== "string") return null;
  try {
    return JSON.parse(row.v);
  } catch {
    return null;
  }
}

async function dbSet(env, key, value) {
  const db = await ready(env);
  await db
    .prepare("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v")
    .bind(key, JSON.stringify(value))
    .run();
}

async function dbDelete(env, key) {
  const db = await ready(env);
  await db.prepare("DELETE FROM kv WHERE k = ?").bind(key).run();
}

async function dbList(env, prefix) {
  const db = await ready(env);
  const res = await db
    .prepare("SELECT k FROM kv WHERE k LIKE ? ORDER BY k")
    .bind(prefix + "%")
    .all();
  return (res.results || []).map((row) => row.k);
}

// ---------------- 鉴权 ----------------
function bearer(request) {
  const raw = request.headers.get("authorization") || "";
  return raw.toLowerCase().startsWith("bearer ") ? raw.slice(7).trim() : "";
}

async function hashSecret(secret) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(secret)));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function newSecret() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function safeEqual(a, b) {
  const left = String(a);
  const right = String(b);
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let i = 0; i < left.length; i += 1) {
    diff |= left.charCodeAt(i) ^ right.charCodeAt(i);
  }
  return diff === 0;
}

async function authenticate(request, env) {
  const id = (request.headers.get("x-device-id") || "").trim();
  const secret = bearer(request);
  if (!id || !secret) return null;
  const dev = await dbGet(env, `dev/${id}`);
  if (!dev || !dev.secretHash) return null;
  if (!safeEqual(await hashSecret(secret), dev.secretHash)) return null;
  return { id, dev };
}

async function requirePc(request, env, pcId) {
  const auth = await authenticate(request, env);
  if (!auth) return { error: fail("设备未授权", 401) };
  if (auth.dev.kind !== "pc") return { error: fail("仅电脑端可调用", 403) };
  if (auth.id !== pcId) return { error: fail("设备 ID 不匹配", 403) };
  return { auth };
}

async function requirePhone(request, env) {
  const auth = await authenticate(request, env);
  if (!auth) return { error: fail("设备未授权", 401) };
  if (auth.dev.kind !== "phone") return { error: fail("仅手机端可调用", 403) };
  return { auth };
}

async function readJson(request) {
  try {
    const text = await request.text();
    if (!text) return {};
    const data = JSON.parse(text);
    return data && typeof data === "object" ? data : {};
  } catch {
    return null;
  }
}

// ---------------- 绑定信息 ----------------
async function pcMeta(env, pcId) {
  const meta = await dbGet(env, `pc/${pcId}/meta`);
  if (!meta || typeof meta !== "object") return null;
  if (!Array.isArray(meta.phones)) meta.phones = [];
  return meta;
}

function findPhone(meta, phoneId) {
  const list = meta && Array.isArray(meta.phones) ? meta.phones : [];
  return list.find((p) => p && p.phoneId === phoneId);
}

function publicPhone(entry) {
  const e = entry || {};
  return {
    phoneId: e.phoneId,
    name: e.name || "",
    confirm: !!e.confirm,
    addedAt: e.addedAt || 0,
  };
}

async function listJson(env, prefix) {
  const items = [];
  for (const key of await dbList(env, prefix)) {
    const data = await dbGet(env, key);
    if (data) items.push({ key, data });
  }
  return items;
}

// ---------------- 设备 ----------------
async function register(request, env) {
  const body = await readJson(request);
  if (!body) return fail("请求体不是合法 JSON");
  const kind = body.kind === "pc" ? "pc" : body.kind === "phone" ? "phone" : "";
  if (!kind) return fail("kind 必须是 pc 或 phone");

  const id = crypto.randomUUID();
  const secret = newSecret();
  const dev = {
    id,
    kind,
    name: String(body.name || "").slice(0, 32),
    secretHash: await hashSecret(secret),
    createdAt: Date.now(),
  };
  await dbSet(env, `dev/${id}`, dev);
  return json({ ok: true, deviceId: id, secret, kind });
}

// ---------------- 绑定（电脑输入手机 ID → 手机确认） ----------------
async function createBind(request, env) {
  const auth = await authenticate(request, env);
  if (!auth) return fail("设备未授权", 401);
  if (auth.dev.kind !== "pc") return fail("仅电脑端可发起绑定", 403);

  const body = await readJson(request);
  if (!body) return fail("请求体不是合法 JSON");
  const phoneId = String(body.phoneId || "").trim();
  const pub = String(body.pub || "").trim();
  if (!phoneId || !pub) return fail("缺少 phoneId 或 pub");

  const phoneDev = await dbGet(env, `dev/${phoneId}`);
  if (!phoneDev || phoneDev.kind !== "phone") return fail("手机端未注册", 404);

  const meta = (await pcMeta(env, auth.id)) || {
    name: auth.dev.name || "",
    createdAt: Date.now(),
    phones: [],
  };
  const bound = findPhone(meta, phoneId);
  if (bound) {
    // 这台手机之前就绑定过：直接更新公钥，不用再确认
    bound.pub = pub;
    bound.confirm = true;
    await dbSet(env, `pc/${auth.id}/meta`, meta);
    return json({
      ok: true, requestId: "", status: "approved",
      phoneName: bound.name || "", pcName: meta.name || "",
    });
  }

  const confirmPhone = meta.phones.find((p) => p && p.confirm);
  if (confirmPhone && confirmPhone.phoneId !== phoneId && body.replace !== true) {
    return fail("已有确认设备，换绑需先在电脑端验证教师密钥", 409);
  }

  const requestId = crypto.randomUUID();
  await dbSet(env, `req/${phoneId}/${requestId}`, {
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

async function bindStatus(request, env, phoneId, requestId) {
  const auth = await authenticate(request, env);
  if (!auth || auth.dev.kind !== "pc") return fail("设备未授权", 401);

  const key = `req/${phoneId}/${requestId}`;
  const requestInfo = await dbGet(env, key);
  if (!requestInfo || requestInfo.pcId !== auth.id) return fail("绑定申请不存在", 404);
  if (requestInfo.status === "pending" && Date.now() - (requestInfo.createdAt || 0) > PAIR_TTL_MS) {
    requestInfo.status = "expired";
    await dbSet(env, key, requestInfo);
  }
  return json({
    ok: true,
    status: requestInfo.status,
    phoneName: requestInfo.phoneName || "",
    pcName: requestInfo.pcName || "",
  });
}

async function phoneInbox(request, env) {
  const guard = await requirePhone(request, env);
  if (guard.error) return guard.error;

  const now = Date.now();
  const requests = [];
  for (const { key, data } of await listJson(env, `req/${guard.auth.id}/`)) {
    if (data.status !== "pending") continue;
    if (now - (data.createdAt || 0) > PAIR_TTL_MS) {
      data.status = "expired";
      await dbSet(env, key, data);
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

async function decideBind(request, env, requestId) {
  const auth = await authenticate(request, env);
  if (!auth) return fail("设备未授权", 401);
  if (auth.dev.kind !== "phone") return fail("仅手机端可确认绑定", 403);

  const body = await readJson(request);
  if (!body) return fail("请求体不是合法 JSON");
  const approve = body.approve === true;
  const pub = String(body.pub || "").trim();
  if (approve && !pub) return fail("同意绑定时必须带上手机公钥");

  const key = `req/${auth.id}/${requestId}`;
  const requestInfo = await dbGet(env, key);
  if (!requestInfo) return fail("绑定申请不存在", 404);
  if (requestInfo.status !== "pending") return fail("该申请已处理", 409);

  if (!approve) {
    requestInfo.status = "denied";
    requestInfo.decidedAt = Date.now();
    await dbSet(env, key, requestInfo);
    return json({ ok: true, status: "denied" });
  }

  const pcId = requestInfo.pcId;
  const meta = (await pcMeta(env, pcId)) || {
    name: requestInfo.pcName || "",
    createdAt: Date.now(),
    phones: [],
  };
  // 一台电脑只保留一台手机：其余设备连同快照、指令一起清掉
  for (const p of meta.phones) {
    if (p.phoneId === auth.id) continue;
    await dbDelete(env, `snap/${pcId}/${p.phoneId}`);
    for (const item of await listJson(env, `act/${pcId}/`)) {
      if (item.data.phoneId === p.phoneId) await dbDelete(env, item.key);
    }
  }
  meta.phones = [{
    phoneId: auth.id,
    name: auth.dev.name || requestInfo.phoneName || "",
    pub,
    confirm: true,
    addedAt: Date.now(),
  }];
  await dbSet(env, `pc/${pcId}/meta`, meta);

  requestInfo.status = "approved";
  requestInfo.decidedAt = Date.now();
  await dbSet(env, key, requestInfo);
  return json({
    ok: true, status: "approved",
    pcId, pcName: meta.name || "", pcPub: requestInfo.pcPub,
  });
}

// ---------------- 已绑定手机管理 ----------------
async function listPhones(request, env, pcId) {
  const guard = await requirePc(request, env, pcId);
  if (guard.error) return guard.error;
  const meta = await pcMeta(env, pcId);
  const list = meta && Array.isArray(meta.phones) ? meta.phones : [];
  // pub 是手机端的 DH 公钥，电脑要靠它派生各自的会话密钥
  const phones = list.map((p) => ({ ...publicPhone(p), pub: (p && p.pub) || "" }));
  return json({ ok: true, phones });
}

async function revokePhone(request, env, pcId, phoneId) {
  const guard = await requirePc(request, env, pcId);
  if (guard.error) return guard.error;

  const meta = await pcMeta(env, pcId);
  if (!meta) return fail("电脑端未初始化", 404);
  meta.phones = meta.phones.filter((p) => p.phoneId !== phoneId);
  await dbSet(env, `pc/${pcId}/meta`, meta);
  await dbDelete(env, `snap/${pcId}/${phoneId}`);
  for (const item of await listJson(env, `act/${pcId}/`)) {
    if (item.data.phoneId === phoneId) await dbDelete(env, item.key);
  }
  return json({ ok: true });
}

// ---------------- 快照 ----------------
async function putSnapshot(request, env, pcId, phoneId) {
  const guard = await requirePc(request, env, pcId);
  if (guard.error) return guard.error;

  const meta = await pcMeta(env, pcId);
  if (!meta || !findPhone(meta, phoneId)) return fail("该手机未绑定", 403);

  const body = await readJson(request);
  if (!body) return fail("请求体不是合法 JSON");
  const cipher = String(body.cipher || "");
  if (!cipher) return fail("缺少 cipher");

  await dbSet(env, `snap/${pcId}/${phoneId}`, {
    cipher,
    version: String(body.version || ""),
    updatedAt: Date.now(),
  });
  return json({ ok: true });
}

async function getSnapshot(request, env, pcId) {
  const guard = await requirePhone(request, env);
  if (guard.error) return guard.error;

  const meta = await pcMeta(env, pcId);
  if (!meta || !findPhone(meta, guard.auth.id)) return fail("未绑定该电脑", 403);

  const snap = await dbGet(env, `snap/${pcId}/${guard.auth.id}`);
  if (!snap) return json({ ok: true, exists: false });
  return json({
    ok: true, exists: true,
    cipher: snap.cipher, version: snap.version, updatedAt: snap.updatedAt,
  });
}

// ---------------- 手机 -> 电脑 指令 ----------------
async function postAction(request, env, pcId) {
  const guard = await requirePhone(request, env);
  if (guard.error) return guard.error;

  const meta = await pcMeta(env, pcId);
  if (!meta || !findPhone(meta, guard.auth.id)) return fail("未绑定该电脑", 403);

  const body = await readJson(request);
  if (!body) return fail("请求体不是合法 JSON");
  const cipher = String(body.cipher || "");
  if (!cipher) return fail("缺少 cipher");

  const id = crypto.randomUUID();
  await dbSet(env, `act/${pcId}/${id}`, {
    id,
    phoneId: guard.auth.id,
    cipher,
    createdAt: Date.now(),
  });
  return json({ ok: true, id });
}

async function listActions(request, env, pcId) {
  const guard = await requirePc(request, env, pcId);
  if (guard.error) return guard.error;

  const actions = (await listJson(env, `act/${pcId}/`))
    .map(({ data }) => data)
    .sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0))
    .slice(0, MAX_ACTIONS)
    .map((a) => ({ id: a.id, phoneId: a.phoneId, cipher: a.cipher, createdAt: a.createdAt }));
  return json({ ok: true, actions });
}

async function deleteAction(request, env, pcId, actionId) {
  const guard = await requirePc(request, env, pcId);
  if (guard.error) return guard.error;
  await dbDelete(env, `act/${pcId}/${actionId}`);
  return json({ ok: true });
}

// ---------------- 路由 ----------------
export async function onRequest(context) {
  const { request, env, params } = context;
  try {
    const seg = Array.isArray(params.path) ? params.path : params.path ? [params.path] : [];
    const method = request.method.toUpperCase();

    if (seg.length === 1 && seg[0] === "health") {
      // ?store=1 用于排查存储：写一条探针再读回
      if (new URL(request.url).searchParams.get("store") === "1") {
        try {
          await dbSet(env, "probe/health", { t: Date.now() });
          const back = await dbGet(env, "probe/health");
          return json({ ok: !!back, store: "d1" });
        } catch (err) {
          return json({ ok: false, store: "error", error: String((err && err.message) || err).slice(0, 200) });
        }
      }
      return json({ ok: true, service: "class-schedule-relay", storage: "d1", time: Date.now() });
    }

    if (seg.length === 1 && seg[0] === "register" && method === "POST") {
      return await register(request, env);
    }
    if (seg[0] === "bind" && seg.length === 1 && method === "POST") {
      return await createBind(request, env);
    }
    if (seg[0] === "bind" && seg.length === 3 && method === "GET") {
      return await bindStatus(request, env, seg[1], seg[2]);
    }
    if (seg[0] === "pair" && seg[1] === "inbox") {
      if (seg.length === 2 && method === "GET") return await phoneInbox(request, env);
      if (seg.length === 4 && seg[3] === "decide" && method === "POST") {
        return await decideBind(request, env, seg[2]);
      }
    }
    if (seg[0] === "pc" && seg.length >= 3) {
      const pcId = seg[1];
      if (seg[2] === "phones" && seg.length === 3 && method === "GET") {
        return await listPhones(request, env, pcId);
      }
      if (seg[2] === "phones" && seg.length === 4 && method === "DELETE") {
        return await revokePhone(request, env, pcId, seg[3]);
      }
      if (seg[2] === "snapshot" && seg.length === 4 && method === "PUT") {
        return await putSnapshot(request, env, pcId, seg[3]);
      }
      if (seg[2] === "snapshot" && seg.length === 3 && method === "GET") {
        return await getSnapshot(request, env, pcId);
      }
      if (seg[2] === "actions" && seg.length === 3) {
        if (method === "POST") return await postAction(request, env, pcId);
        if (method === "GET") return await listActions(request, env, pcId);
      }
      if (seg[2] === "actions" && seg.length === 4 && method === "DELETE") {
        return await deleteAction(request, env, pcId, seg[3]);
      }
    }
    return fail("接口不存在", 404);
  } catch (err) {
    console.error("[api]", err);
    return fail("服务器内部错误", 500);
  }
}
