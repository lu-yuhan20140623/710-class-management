// 本地接口回归：注册 → 配对 → 快照 → 指令 → 换绑/失效。
// 用法：node test-api.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import net from "node:net";

const here = fileURLToPath(new URL(".", import.meta.url));

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitReady(base) {
  for (let i = 0; i < 60; i += 1) {
    try {
      const res = await fetch(`${base}/health`);
      if (res.ok) return;
    } catch {
      /* 还没起来 */
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("dev server 启动超时");
}

async function main() {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}/api`;
  const child = spawn(process.execPath, ["dev-server.mjs"], {
    cwd: here,
    env: { ...process.env, PORT: String(port), STORE_DIR: `${here}.data-test` },
    stdio: ["ignore", "inherit", "inherit"],
  });

  try {
    await waitReady(base);

    const call = async (method, path, { token, body } = {}) => {
      const headers = { "content-type": "application/json" };
      if (token) {
        headers.authorization = `Bearer ${token.secret}`;
        headers["x-device-id"] = token.deviceId;
      }
      const res = await fetch(`${base}${path}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
      });
      return { status: res.status, data: await res.json() };
    };

    const register = async (kind, name) => {
      const res = await call("POST", "/register", { body: { kind, name } });
      assert.equal(res.status, 200);
      assert.ok(res.data.deviceId && res.data.secret);
      return { deviceId: res.data.deviceId, secret: res.data.secret };
    };

    const pc = await register("pc", "教师办公室");
    const phone1 = await register("phone", "老师手机");
    const phone2 = await register("phone", "备用手机");

    // 1. 手机发起绑定，电脑拉取申请
    let res = await call("POST", "/pair/request", {
      token: phone1,
      body: { pcId: pc.deviceId, pub: "PHONE1_PUB" },
    });
    assert.equal(res.status, 200);
    const req1 = res.data.requestId;

    res = await call("GET", "/pair/requests", { token: pc });
    assert.equal(res.status, 200);
    assert.equal(res.data.requests.length, 1);
    assert.equal(res.data.requests[0].phoneId, phone1.deviceId);

    // 2. 电脑同意（第一台自动成为确认设备）
    res = await call("POST", `/pair/requests/${req1}/decide`, {
      token: pc,
      body: { approve: true, pub: "PC_PUB" },
    });
    assert.equal(res.status, 200);

    res = await call("GET", `/pair/requests/${req1}?pcId=${pc.deviceId}`, { token: phone1 });
    assert.equal(res.data.status, "approved");
    assert.equal(res.data.pcPub, "PC_PUB");

    res = await call("GET", `/pc/${pc.deviceId}/phones`, { token: pc });
    assert.equal(res.data.phones.length, 1);
    assert.equal(res.data.phones[0].confirm, true);

    // 3. 第二台手机：只能只读加入，不能顶替确认设备
    res = await call("POST", "/pair/request", {
      token: phone2,
      body: { pcId: pc.deviceId, pub: "PHONE2_PUB" },
    });
    const req2 = res.data.requestId;
    res = await call("POST", `/pair/requests/${req2}/decide`, {
      token: pc,
      body: { approve: true, pub: "PC_PUB2" },
    });
    assert.equal(res.status, 200);
    res = await call("GET", `/pc/${pc.deviceId}/phones`, { token: pc });
    const confirmCount = res.data.phones.filter((p) => p.confirm).length;
    assert.equal(confirmCount, 1);
    assert.equal(res.data.phones.length, 2);

    // 4. 快照：各手机各一份密文
    res = await call("PUT", `/pc/${pc.deviceId}/snapshot/${phone1.deviceId}`, {
      token: pc,
      body: { cipher: "CIPHER1", version: "2.2.1" },
    });
    assert.equal(res.status, 200);
    res = await call("GET", `/pc/${pc.deviceId}/snapshot`, { token: phone1 });
    assert.equal(res.data.cipher, "CIPHER1");
    res = await call("GET", `/pc/${pc.deviceId}/snapshot`, { token: phone2 });
    assert.equal(res.status, 200);
    assert.equal(res.data.exists, false);

    // 未绑定手机读不到
    res = await call("GET", `/pc/${pc.deviceId}/snapshot`, { token: await register("phone", "路人") });
    assert.equal(res.status, 403);

    // 5. 手机 -> 电脑指令
    res = await call("POST", `/pc/${pc.deviceId}/actions`, {
      token: phone1,
      body: { cipher: "ACTION1" },
    });
    assert.equal(res.status, 200);
    const actionId = res.data.id;
    res = await call("GET", `/pc/${pc.deviceId}/actions`, { token: pc });
    assert.equal(res.data.actions.length, 1);
    assert.equal(res.data.actions[0].cipher, "ACTION1");
    res = await call("DELETE", `/pc/${pc.deviceId}/actions/${actionId}`, { token: pc });
    assert.equal(res.status, 200);
    res = await call("GET", `/pc/${pc.deviceId}/actions`, { token: pc });
    assert.equal(res.data.actions.length, 0);

    // 6. 换绑：不带 replace 时拒绝，带 replace 时旧确认设备立即失效
    const phone3 = await register("phone", "新手机");
    res = await call("POST", "/pair/request", {
      token: phone3,
      body: { pcId: pc.deviceId, pub: "PHONE3_PUB" },
    });
    const req3 = res.data.requestId;
    res = await call("POST", `/pair/requests/${req3}/decide`, {
      token: pc,
      body: { approve: true, pub: "PC_PUB3", replace: true },
    });
    assert.equal(res.status, 200);
    res = await call("GET", `/pc/${pc.deviceId}/phones`, { token: pc });
    const phones = res.data.phones;
    assert.equal(phones.filter((p) => p.confirm).length, 1);
    assert.equal(phones.find((p) => p.confirm).phoneId, phone3.deviceId);
    assert.equal(phones.some((p) => p.phoneId === phone1.deviceId), false);

    res = await call("GET", `/pc/${pc.deviceId}/snapshot`, { token: phone1 });
    assert.equal(res.status, 403);

    // 7. 鉴权：错误密钥被拒
    res = await call("GET", `/pc/${pc.deviceId}/phones`, {
      token: { deviceId: pc.deviceId, secret: "wrong" },
    });
    assert.equal(res.status, 401);

    console.log("全部接口用例通过");
  } finally {
    child.kill();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
