// Cloudflare Pages Function：Bug 反馈 API
// 存储：Workers KV，绑定名 BUGS；管理密钥：环境变量 BUG_ADMIN_TOKEN。
// 该路由优先于 functions/api/[[path]].js 的 Netlify 反代，因此不再依赖 Netlify。
//
// POST   /api/bugs                 提交（公开）
// GET    /api/bugs                 读取待处理全部（管理）；?all=1 含历史
// GET    /api/bugs/history         公开历史，含状态，隐去联系方式
// POST   /api/bugs/:id/resolve     汇报修复/计划/不予修复，转入历史（管理）
// DELETE /api/bugs/:id             物理删除，记录不存在时 deleted:false（管理）

const DESC_MIN = 5;
const DESC_MAX = 2000;
const SIDES = ["电脑端", "网页版", "手机端"];
const STATUSES = ["fixed", "planned", "wontfix"];

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function requireAdmin(request, env) {
  if (!env.BUG_ADMIN_TOKEN) {
    return { error: json({ ok: false, error: "未配置 BUG_ADMIN_TOKEN" }, 503) };
  }
  const header = request.headers.get("x-admin-token") || "";
  const bearer = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (header !== env.BUG_ADMIN_TOKEN && bearer !== env.BUG_ADMIN_TOKEN) {
    return { error: json({ ok: false, error: "未授权" }, 401) };
  }
  return {};
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

function stringList(value, max) {
  const arr = Array.isArray(value) ? value : value ? [value] : [];
  return [...new Set(arr.map((v) => String(v).trim().slice(0, 40)).filter(Boolean))].slice(0, max);
}

async function listKeys(kv) {
  const keys = [];
  let cursor;
  do {
    const page = await kv.list({ prefix: "bug:", cursor });
    keys.push(...page.keys.map((k) => k.name));
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);
  return keys;
}

async function create(request, env) {
  const body = await readJson(request);
  if (!body) return json({ ok: false, error: "请求体不是合法 JSON" });

  const description = String(body.description || "").trim();
  if (description.length < DESC_MIN) return json({ ok: false, error: `问题描述至少 ${DESC_MIN} 个字` });
  if (description.length > DESC_MAX) return json({ ok: false, error: `问题描述最多 ${DESC_MAX} 字` });

  const side = stringList(body.side, 3);
  if (!side.length) return json({ ok: false, error: "请选择软件端" });
  if (side.some((s) => !SIDES.includes(s))) return json({ ok: false, error: "软件端取值不合法" });

  const versions = stringList(body.versions, 30);
  if (!versions.length) return json({ ok: false, error: "请选择至少一个出现过的版本" });

  const id = crypto.randomUUID();
  const bug = {
    id,
    title: String(body.title || "").trim().slice(0, 80) || description.slice(0, 40),
    description,
    contact: String(body.contact || "").trim().slice(0, 100),
    page: String(body.page || "").trim().slice(0, 200),
    side,
    versions,
    status: "open",
    ua: String(request.headers.get("user-agent") || "").slice(0, 300),
    createdAt: Date.now(),
  };
  await env.BUGS.put(`bug:${id}`, JSON.stringify(bug));
  return json({ ok: true, id });
}

async function allBugs(env) {
  const keys = await listKeys(env.BUGS);
  return (await Promise.all(keys.map((key) => env.BUGS.get(key, { type: "json" }))))
    .filter(Boolean)
    .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
}

async function list(request, env) {
  const guard = requireAdmin(request, env);
  if (guard.error) return guard.error;

  const all = new URL(request.url).searchParams.get("all") === "1";
  const bugs = (await allBugs(env)).filter((b) => all || !b.status || b.status === "open");
  return json({ ok: true, count: bugs.length, bugs });
}

async function history(env) {
  const bugs = (await allBugs(env))
    .filter((b) => b.status && b.status !== "open")
    .sort((a, b) => (b.resolvedAt || b.createdAt || 0) - (a.resolvedAt || a.createdAt || 0))
    .map((b) => ({
      id: b.id,
      title: b.title,
      description: b.description,
      side: b.side || [],
      versions: b.versions || (b.version ? [b.version] : []),
      status: b.status,
      createdAt: b.createdAt,
      resolvedAt: b.resolvedAt || null,
    }));
  return json({ ok: true, count: bugs.length, bugs });
}

async function resolve(request, env, id) {
  const guard = requireAdmin(request, env);
  if (guard.error) return guard.error;

  const body = (await readJson(request)) || {};
  const status = STATUSES.includes(body.status) ? body.status : "fixed";
  const key = `bug:${id}`;
  const bug = await env.BUGS.get(key, { type: "json" });
  if (!bug) return json({ ok: true, id, notFound: true, status: null });

  const updated = {
    ...bug,
    status,
    note: String(body.note || "").trim().slice(0, 300),
    resolvedAt: Date.now(),
  };
  await env.BUGS.put(key, JSON.stringify(updated));
  return json({ ok: true, id, notFound: false, status });
}

async function remove(request, env, id) {
  const guard = requireAdmin(request, env);
  if (guard.error) return guard.error;

  const key = `bug:${id}`;
  const existing = await env.BUGS.get(key);
  await env.BUGS.delete(key);
  return json({ ok: true, id, deleted: !!existing, notFound: !existing });
}

export async function onRequest(context) {
  const { request, env, params } = context;
  if (!env.BUGS) return json({ ok: false, error: "Bug 存储未配置（缺少 BUGS 绑定）" }, 503);

  const seg = Array.isArray(params.path) ? params.path : params.path ? [params.path] : [];
  const method = request.method.toUpperCase();

  if (seg.length === 0 && method === "POST") return create(request, env);
  if (seg.length === 0 && method === "GET") return list(request, env);
  if (seg.length === 1 && seg[0] === "history" && method === "GET") return history(env);
  if (seg.length === 1 && method === "DELETE") return remove(request, env, seg[0]);
  if (seg.length === 2 && seg[1] === "resolve" && method === "POST") return resolve(request, env, seg[0]);

  return json({ ok: false, error: "接口不存在" }, 404);
}
