// Cloudflare Pages Function：/download/win
// 与 server/netlify/functions/download.mjs 逻辑一致：
// 依次探测 Gitee Release、GitHub Release，都不可用就跳到发布列表页。
const VERSION = "2.2.3";
const SETUP = `ClassSchedule_Setup_${VERSION}.exe`;
const GITEE = `https://gitee.com/lu-yuhan20140623/710/releases/download/v${VERSION}/${SETUP}`;
const GITHUB = `https://github.com/lu-yuhan20140623/710-class-management/releases/download/v${VERSION}/${SETUP}`;
const FALLBACK_PAGE = "https://github.com/lu-yuhan20140623/710-class-management/releases";

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

export async function onRequest() {
  for (const url of [GITEE, GITHUB]) {
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
}
