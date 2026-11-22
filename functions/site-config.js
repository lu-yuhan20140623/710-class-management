// Cloudflare Pages Function：/site-config
// 官网与 Bug 反馈页的版本号、文案统一从 Gitee 的 update/latest.json 动态读取，
// 以后改版本号/文案只改那个 JSON，不需要重新部署站点。
// Gitee 不可用时回退到 GitHub 上的同名文件；都失败则返回 502，页面保留静态兜底文案。
const SOURCE = "https://gitee.com/lu-yuhan20140623/710/raw/master/update/latest.json";
const SOURCE_FALLBACK = "https://raw.githubusercontent.com/lu-yuhan20140623/710-class-management/main/update/latest.json";

async function loadJson(url) {
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "classmanagement-site", "Cache-Control": "no-cache" },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function onRequest() {
  let data = await loadJson(SOURCE);
  if (!data || !data.version) data = await loadJson(SOURCE_FALLBACK);
  if (!data || !data.version) {
    return new Response(JSON.stringify({ ok: false }), {
      status: 502,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  }

  const site = data.site || {};
  const payload = {
    ok: true,
    version: data.version,
    published_at: data.published_at || "",
    notes: data.notes || "",
    site: {
      android_version: site.android_version || "",
      apk: site.apk || "",
      setup_size: site.setup_size || "",
      hero_badge: site.hero_badge || "",
      term: site.term || "",
      versions: Array.isArray(site.versions) ? site.versions : [],
    },
  };

  return new Response(JSON.stringify(payload), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=60",
    },
  });
}
