// 存储层：线上用 Netlify Blobs，本地开发用文件目录（STORE_DIR）。
// 接口刻意保持最小：get / setJSON / delete / listAll。
import { promises as fs } from "node:fs";
import path from "node:path";

let instance = null;

class FileStore {
  constructor(dir) {
    this.dir = path.resolve(dir);
  }

  _file(key) {
    // key 里可能有 "/"，按目录层级落盘
    return path.join(this.dir, key.replace(/[^a-zA-Z0-9._/-]/g, "_"));
  }

  async get(key, options = {}) {
    try {
      const text = await fs.readFile(this._file(key), "utf-8");
      if (options.type === "json") return JSON.parse(text);
      return text;
    } catch (err) {
      if (err.code === "ENOENT") return null;
      throw err;
    }
  }

  async setJSON(key, value) {
    const file = this._file(key);
    await fs.mkdir(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    await fs.writeFile(tmp, JSON.stringify(value), "utf-8");
    await fs.rename(tmp, file);
  }

  async delete(key) {
    try {
      await fs.unlink(this._file(key));
    } catch (err) {
      if (err.code !== "ENOENT") throw err;
    }
  }

  async listAll(prefix = "") {
    const out = [];
    const walk = async (dir, rel) => {
      let entries;
      try {
        entries = await fs.readdir(dir, { withFileTypes: true });
      } catch (err) {
        if (err.code === "ENOENT") return;
        throw err;
      }
      for (const entry of entries) {
        const key = rel ? `${rel}/${entry.name}` : entry.name;
        if (entry.isDirectory()) {
          await walk(path.join(dir, entry.name), key);
        } else if (!entry.name.endsWith(".tmp") && key.startsWith(prefix)) {
          out.push(key);
        }
      }
    };
    await walk(this.dir, "");
    return out.sort();
  }
}

class BlobsStore {
  constructor(store) {
    this.store = store;
  }

  async get(key, options = {}) {
    if (options.type === "json") return (await this.store.get(key, { type: "json" })) ?? null;
    return (await this.store.get(key)) ?? null;
  }

  async setJSON(key, value) {
    await this.store.setJSON(key, value);
  }

  async delete(key) {
    await this.store.delete(key);
  }

  async listAll(prefix = "") {
    const keys = [];
    const { blobs } = await this.store.list({ prefix });
    for (const blob of blobs) keys.push(blob.key);
    return keys.sort();
  }
}

export async function store() {
  if (instance) return instance;
  if (process.env.STORE_DIR) {
    instance = new FileStore(process.env.STORE_DIR);
  } else {
    const { getStore } = await import("@netlify/blobs");
    instance = new BlobsStore(getStore({ name: "relay", consistency: "strong" }));
  }
  return instance;
}
