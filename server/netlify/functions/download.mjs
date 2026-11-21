// Windows 安装包下载入口：优先 Gitee Release（国内更快），其次 GitHub Release。
// 安装包不放进静态站点仓库（42MB，Cloudflare Pages 单文件上限装不下），
// 浏览器端探测会被 Gitee 的 CORS 拦掉，所以把“哪边能下”的判断放在服务端。
const VERSION = "2.2.4";
const SETUP = `ClassSchedule_Setup_${VERSION}.exe`;
const GITEE = `https://gitee.com/lu-yuhan20140623/710/releases/download/v${VERSION}/${SETUP}`;
const GITHUB = `https://github.com/lu-yuhan20140623/710-class-management/releases/download/v${VERSION}/${SETUP}`;
const FALLBACK_PAGE = "https://github.com/lu-yuhan20140623/710-class-management/releases";

export const config = { path: "/download/win" };

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
};
