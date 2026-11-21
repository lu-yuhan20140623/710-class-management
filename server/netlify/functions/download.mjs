// Windows 安装包下载入口：优先跳 Gitee Release（更快），Gitee 上没有对应版本或不可达时退回本站 downloads/。
//
// 浏览器端的 fetch 探测会被 Gitee 的 CORS 拦掉（不带 Access-Control-Allow-Origin），
// 所以把“探测哪边能下”放到服务端做，页面链接固定指到这里。
const VERSION = "2.2.3";
const SETUP = `ClassSchedule_Setup_${VERSION}.exe`;
const GITEE = `https://gitee.com/lu-yuhan20140623/710/releases/download/v${VERSION}/${SETUP}`;
const LOCAL = `/downloads/${SETUP}`;

export const config = { path: "/download/win" };

export default async () => {
  try {
    const res = await fetch(GITEE, {
      method: "HEAD",
      redirect: "follow",
      headers: { "User-Agent": "classmanagement-download" },
    });
    if (res.ok) {
      return new Response(null, {
        status: 302,
        headers: { Location: GITEE, "Cache-Control": "public, max-age=300" },
      });
    }
  } catch {
    // 忽略：下面退回本站
  }
  return new Response(null, {
    status: 302,
    headers: { Location: LOCAL, "Cache-Control": "no-store" },
  });
};
