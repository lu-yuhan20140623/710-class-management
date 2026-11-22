// Windows 安装包下载入口：优先 Gitee Release（国内更快），其次 GitHub Release。
// 安装包不放进静态站点仓库（42MB，Cloudflare Pages 单文件上限装不下），
// 浏览器端探测会被 Gitee 的 CORS 拦掉，所以把“哪边能下”的判断放在服务端。
// 版本号从 Gitee 的 update/latest.json 动态读取，发版不必改代码、不必重新部署。
const FALLBACK_VERSION = "2.2.4";
const CONFIG_URL = "https://gitee.com/lu-yuhan20140623/710/raw/master/update/latest.json";
const CONFIG_URL_FALLBACK = "https://raw.githubusercontent.com/lu-yuhan20140623/710-class-management/main/update/latest.json";
const FALLBACK_PAGE = "https://github.com/lu-yuhan20140623/710-class-management/releases";

export const config = { path: "/download/win" };

async function loadJson(url) {
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "classmanagement-download", "Cache-Control": "no-cache" },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function currentVersion() {
  let data = await loadJson(CONFIG_URL);
  if (!data || !data.version) data = await loadJson(CONFIG_URL_FALLBACK);
  const version = data && data.version ? String(data.version).trim() : "";
  return /^\d+(\.\d+)*$/.test(version) ? version : FALLBACK_VERSION;
}

async function alive(url) {
  try {
    const res = await fetch(url, {
      method: "HEAD",
      redirect: "follow",
      headers: { "User-Agent": "classmanagement-download" },
    });
    return res.ok;
  } catch {
    return false;
  }
}

export default async () => {
  const version = await currentVersion();
  const setup = `ClassSchedule_Setup_${version}.exe`;
  const gitee = `https://gitee.com/lu-yuhan20140623/710/releases/download/v${version}/${setup}`;
  const github = `https://github.com/lu-yuhan20140623/710-class-management/releases/download/v${version}/${setup}`;

  for (const url of [gitee, github]) {
    if (await alive(url)) {
      return new Response(null, {
        status: 302,
        headers: { Location: url, "Cache-Control": "public, max-age=300" },
      });
    }
  }
  return new Response(null, {
    status: 302,
    headers: { Location: FALLBACK_PAGE, "Cache-Control": "no-store" },
  });
};
