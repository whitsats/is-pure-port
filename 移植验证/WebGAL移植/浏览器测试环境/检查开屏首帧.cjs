/**
 * 检查开屏首屏：空缓存打开根路径时，落地页 / 语言选择 / 未套模板样式的标题菜单
 * 是否在片头之前露出来，以及片头何时开始播放。
 *
 * 用法：node 检查开屏首帧.cjs [URL]
 */
const { chromium } = require('playwright');

const URL = process.argv[2] || 'http://127.0.0.1:4195/';

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio'],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 720 },
      ignoreHTTPSErrors: true,
    });
    const page = await context.newPage();
    await page.addInitScript(() => {
      window.__bootTimeline = [];
      const started = performance.now();
      const tick = () => {
        const landing = document.querySelector('.html-body__title-enter');
        const lang = document.querySelector('[class*=langWrapper]');
        const btn = [...document.querySelectorAll('.App div')].find(
          (d) => d.textContent === '开始游戏开始游戏开始游戏',
        );
        const list = btn ? btn.parentElement : null;
        const main = list ? list.parentElement : null;
        const video = document.querySelector('video');
        const overlay = document.querySelector('[class*=openingLoop_main]');
        window.__bootTimeline.push({
          t: Math.round(performance.now() - started),
          landing: landing ? getComputedStyle(landing).display !== 'none' : false,
          lang: !!lang,
          title: btn ? btn.offsetParent !== null : false,
          styled: list ? getComputedStyle(list).paddingLeft === '150px' : null,
          titleBg: main ? (main.style.backgroundImage || '').includes('title_op') : false,
          video: !!video,
          videoT: video ? Number(video.currentTime.toFixed(2)) : null,
          overlay: !!overlay,
          blocked: !!document.querySelector('[class*=openingLoop_blocked]'),
          // 标题菜单是否真的露在玩家眼前（被片头层或黑场盖住就不算）
          exposed: !!btn && btn.offsetParent !== null && !overlay && !video,
        });
        if (performance.now() - started < 9000) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    await page.goto(URL, { waitUntil: 'load', timeout: 60000 });
    await page.waitForTimeout(7500);
    const timeline = await page.evaluate(() => window.__bootTimeline || []);
    await context.close();

    // 只保留状态变化的采样点
    const keys = ['landing', 'lang', 'title', 'styled', 'titleBg', 'video', 'overlay', 'blocked', 'exposed'];
    const compressed = [];
    let last = '';
    for (const item of timeline) {
      const sig = keys.map((k) => String(item[k])).join('|');
      if (sig !== last) {
        compressed.push(item);
        last = sig;
      }
    }
    console.log('URL:', URL);
    for (const item of compressed.slice(0, 40)) {
      console.log(
        `t=${String(item.t).padStart(4)}ms landing=${item.landing ? 1 : 0} lang=${item.lang ? 1 : 0} ` +
          `title=${item.title ? 1 : 0} styled=${item.styled} titleBg=${item.titleBg ? 1 : 0} ` +
          `video=${item.video ? 1 : 0} t=${item.videoT} overlay=${item.overlay ? 1 : 0} ` +
          `blocked=${item.blocked ? 1 : 0} exposedTitle=${item.exposed ? 1 : 0}`,
      );
    }
    const videoSample = [...timeline].reverse().find((s) => s.video);
    console.log('末尾片头:', videoSample ? `video=${videoSample.video} t=${videoSample.videoT}` : '无');
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
