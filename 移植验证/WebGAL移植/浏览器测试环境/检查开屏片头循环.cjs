/**
 * 开屏片头循环验收：空缓存打开根路径，检查首屏无落地页/语言页/未套样式菜单，
 * 片头整段播完 → 标题停留配置时长 → 片头重播，连续两轮；再看开始游戏打断与 end 返回。
 *
 * 用法：node 检查开屏片头循环.cjs [URL]
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
const FAST = args.includes('--fast');
const URL = args.find((arg) => arg.startsWith('http')) || 'http://127.0.0.1:4195/';
const HOLD_MS = 15000;
const LOOP_DEADLINE_MS = 260000;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function readState(page) {
  return page.evaluate(() => {
    const video = document.querySelector('video');
    const overlay = document.querySelector('[class*=openingLoop_main]');
    const titleMain = [...document.querySelectorAll('.App > div')].find((d) =>
      (d.style.backgroundImage || '').includes('title_op'),
    );
    const startButton = [...document.querySelectorAll('.App div')].find(
      (d) => d.textContent === '开始游戏开始游戏开始游戏',
    );
    return {
      video: !!video,
      currentTime: video ? Number(video.currentTime.toFixed(2)) : null,
      duration: video && Number.isFinite(video.duration) ? Number(video.duration.toFixed(2)) : null,
      muted: video ? video.muted : null,
      overlay: !!overlay,
      blocked: !!document.querySelector('[class*=openingLoop_blocked]'),
      mutedHint: !!document.querySelector('[class*=openingLoop_mutedHint]'),
      titleBg: !!titleMain,
      titleExposed: !!startButton && startButton.offsetParent !== null && !overlay && !video,
      languageSelect: !!document.querySelector('[class*=langWrapper]'),
      landingVisible: (() => {
        const landing = document.querySelector('.html-body__title-enter');
        return landing ? getComputedStyle(landing).display !== 'none' : false;
      })(),
      textBox: (document.querySelector('#textBoxMain')?.innerText || '').replace(/(.)\1+/gu, '$1').slice(0, 80),
    };
  });
}

async function clickByText(page, text) {
  return page.evaluate((label) => {
    const nodes = [...document.querySelectorAll('.App div')];
    const node = nodes.find((d) => d.textContent === label.repeat(3)) || nodes.find((d) => d.textContent === label);
    if (!node) return false;
    node.click();
    return true;
  }, text);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio'],
  });
  const log = [];
  const say = (line) => {
    console.log(line);
    log.push(line);
  };

  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() => {
      window.__paintMarks = [];
      const mark = () => {
        const landing = document.querySelector('.html-body__title-enter');
        const video = document.querySelector('video');
        const overlay = document.querySelector('[class*=openingLoop_main]');
        const startButton = [...document.querySelectorAll('.App div')].find(
          (d) => d.textContent === '开始游戏开始游戏开始游戏',
        );
        window.__paintMarks.push({
          t: Math.round(performance.now()),
          landing: landing ? getComputedStyle(landing).display !== 'none' : false,
          video: !!video,
          overlay: !!overlay,
          titleExposed: !!startButton && startButton.offsetParent !== null && !overlay,
        });
        if (performance.now() < 8000) requestAnimationFrame(mark);
      };
      requestAnimationFrame(mark);
    });

    await page.goto(URL, { waitUntil: 'load', timeout: 60000 });
    await sleep(2500);

    const firstPaint = await page.evaluate(() => {
      const fcp = performance.getEntriesByType('paint').find((e) => e.name === 'first-contentful-paint');
      const marks = window.__paintMarks || [];
      return {
        fcp: fcp ? Math.round(fcp.startTime) : null,
        landingFrames: marks.filter((m) => m.landing).length,
        firstVideoMs: marks.find((m) => m.video)?.t ?? null,
        firstOverlayMs: marks.find((m) => m.overlay)?.t ?? null,
        exposedTitleFrames: marks.filter((m) => m.titleExposed).length,
      };
    });
    say(`首屏: FCP=${firstPaint.fcp}ms 落地页可见帧=${firstPaint.landingFrames} ` +
      `首个片头层=${firstPaint.firstOverlayMs}ms 首个 video=${firstPaint.firstVideoMs}ms ` +
      `未被遮挡帧=${firstPaint.exposedTitleFrames}`);

    const boot = await readState(page);
    say(`开屏状态: ${JSON.stringify(boot)}`);
    if (boot.landingVisible) throw new Error('WebGAL 落地页仍可见');
    if (boot.languageSelect) throw new Error('语言选择层仍可见');
    if (boot.blocked) throw new Error('出现了阻断式“点击开始”遮罩');
    if (!boot.video) throw new Error('片头 video 未出现');
    if (boot.duration !== null && Math.abs(boot.duration - 95.44) > 0.5) {
      throw new Error(`片头时长不是手机版整段：${boot.duration}`);
    }
    if (firstPaint.exposedTitleFrames > 2) {
      throw new Error(`标题菜单在片头前露出 ${firstPaint.exposedTitleFrames} 帧`);
    }

    const audio = await page.evaluate(async () => {
      const v = document.querySelector('video');
      if (!v) return null;
      const bytes = v.webkitAudioDecodedByteCount ?? null;
      return { bytes, muted: v.muted, duration: v.duration };
    });
    say(`音轨解码字节=${audio?.bytes} 静音=${audio?.muted}`);

    // 静音起播时，第一次点击只恢复声音，不跳过片头
    if (audio && audio.muted) {
      const before = await readState(page);
      await page.mouse.click(640, 360);
      await sleep(600);
      const after = await readState(page);
      say(`点击恢复声音: muted ${before.muted} -> ${after.muted}，静音提示=${after.mutedHint}，片头仍在=${after.video}`);
      if (!after.video) throw new Error('点击恢复声音时把片头跳过了');
      if (after.mutedHint) throw new Error('恢复声音后静音提示没有消失');
      if (after.currentTime !== null && before.currentTime !== null && after.currentTime < before.currentTime) {
        throw new Error('点击恢复声音后片头重头播放');
      }
    }

    // 连续两轮：片头播完 → 标题停留 → 片头重播（--fast 只验证交互部分）
    const startedAt = Date.now();
    let last = await readState(page);
    let restarts = 0;
    let endAt = null;
    let firstPlayStart = Date.now();
    let stallSince = null;
    let blackSince = null;
    const cycles = [];
    while (!FAST && Date.now() - startedAt < LOOP_DEADLINE_MS && restarts < 2) {
      await sleep(500);
      const state = await readState(page);
      const now = Date.now();
      if (state.video && !last.video) {
        restarts += 1;
        const holdMs = endAt ? now - endAt : null;
        cycles.push({
          loop: restarts,
          playedMs: firstPlayStart ? (endAt ?? now) - firstPlayStart : null,
          holdMs,
        });
        say(`第 ${restarts} 次重播：上一轮播完→重播间隔=${holdMs}ms，片头时长=${state.duration}s`);
        if (holdMs !== null && Math.abs(holdMs - HOLD_MS) > 2000) {
          throw new Error(`标题停留时长 ${holdMs}ms 与配置 ${HOLD_MS}ms 不符`);
        }
        firstPlayStart = now;
        endAt = null;
      }
      if (!state.video && last.video) {
        endAt = now;
        const played = firstPlayStart ? now - firstPlayStart : null;
        say(`片头播放结束：本轮播放 ${Math.round((played || 0) / 1000)}s，标题背景=${state.titleBg}`);
        if (played !== null && played < 90000) throw new Error(`片头只播了 ${played}ms，不是整段`);
        if (!state.titleBg) throw new Error('标题界面背景不是 title_op');
      }
      if (state.video) {
        if (last.video && state.currentTime !== null && last.currentTime !== null && state.currentTime <= last.currentTime) {
          stallSince = stallSince ?? now;
          if (now - stallSince > 3000) throw new Error('片头画面卡住（currentTime 不再前进）');
        } else {
          stallSince = null;
        }
      }
      if (!state.video && !state.titleBg && !state.overlay) {
        blackSince = blackSince ?? now;
        if (now - blackSince > 1000) throw new Error('片头与标题之间出现黑屏');
      } else {
        blackSince = null;
      }
      last = state;
    }
    if (FAST) {
      say('--fast：跳过两轮循环');
    } else {
      if (restarts < 2) throw new Error(`没有走完两轮循环，只重播了 ${restarts} 次`);
      say(`循环两轮完成，用时 ${Math.round((Date.now() - startedAt) / 1000)}s：${JSON.stringify(cycles)}`);
    }

    // 开始游戏打断循环
    await page.mouse.click(640, 360); // 跳过片头
    await sleep(800);
    let state = await readState(page);
    if (state.video) throw new Error('点击未能跳过片头');
    if (!state.titleExposed) throw new Error('跳过片头后没有回到标题');
    const clickedStart = await clickByText(page, '开始游戏');
    if (!clickedStart) throw new Error('找不到开始游戏按钮');
    await sleep(1500);
    state = await readState(page);
    say(`开始游戏后: video=${state.video} 标题露在眼前=${state.titleExposed} 文本=${JSON.stringify(state.textBox)}`);
    if (state.video) throw new Error('开始游戏后片头仍在播放');
    if (state.titleExposed) throw new Error('开始游戏后标题仍在');
    if (!state.textBox) throw new Error('开始游戏后没有出现剧情文本');

    // 推进到选项并选择“回到标题”
    for (let i = 0; i < 6; i++) {
      const hasChoice = await page.evaluate(() =>
        [...document.querySelectorAll('.App div')].some((d) => d.textContent === '回到标题看片头循环'),
      );
      if (hasChoice) break;
      await page.mouse.click(640, 360);
      await sleep(500);
    }
    const chose = await page.evaluate(() => {
      const node = [...document.querySelectorAll('.App div')].find((d) => d.textContent === '回到标题看片头循环');
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });
    if (!chose) throw new Error('没有出现 WebGAL 选项');
    await page.mouse.click(chose.x, chose.y);
    for (let i = 0; i < 10; i++) {
      await sleep(400);
      state = await readState(page);
      if (state.titleBg) break;
    }
    state = await readState(page);
    say(`end 回标题: 标题背景=${state.titleBg} 片头=${state.video}`);
    if (!state.titleBg) throw new Error('end 后没有回到标题界面');
    if (state.video) throw new Error('end 后片头立即重播，没有先停标题');

    // 鉴赏入口（游廊）
    if (!(await clickByText(page, '鉴赏模式'))) throw new Error('标题没有鉴赏模式入口');
    await sleep(900);
    if (!(await page.evaluate(() => !!document.querySelector('[class*="_extra_top_"]')))) {
      throw new Error('鉴赏面板没有打开');
    }

    // 逐页扫完整个 CG 鉴赏：收集每一页实际渲染的条目
    const pages = await page.evaluate(() => document.querySelectorAll('[class*="_cgNav_"]').length);
    const rendered = [];
    for (let i = 0; i < pages; i++) {
      // 直接点 DOM：导航是带过渡的窄条，坐标点击会在激活项变粗眯时偏移
      const clickedPage = await page.evaluate((index) => {
        const nav = document.querySelectorAll('[class*="_cgNav_"]')[index];
        if (!nav) return false;
        nav.click();
        return true;
      }, i);
      if (!clickedPage) throw new Error(`鉴赏第 ${i + 1} 页导航不存在`);
      await sleep(700);
      const activePage = await page.evaluate(() =>
        [...document.querySelectorAll('[class*="_cgNav_"]')].findIndex((nav) => nav.className.includes('cgNav_active')),
      );
      if (activePage !== i) throw new Error(`鉴赏第 ${i + 1} 页没有切过去（当前第 ${activePage + 1} 页）`);
      const pageItems = await page.evaluate(() => {
        const container = document.querySelector('[class*="_cgContainer_"]');
        if (!container) return [];
        return [...container.querySelectorAll('div')]
          .filter((d) => (d.style.backgroundImage || '').includes('url('))
          .map((d) => {
            const match = /url\("?'?([^"')]+)"?'?\)/.exec(d.style.backgroundImage);
            const rect = d.getBoundingClientRect();
            return { url: match ? match[1] : '', w: Math.round(rect.width), h: Math.round(rect.height) };
          });
      });
      rendered.push(...pageItems);
    }

    const urls = [...new Set(rendered.map((item) => item.url))];
    const invisible = rendered.filter((item) => item.w < 20 || item.h < 20);
    const backgroundDir = path.resolve('../历史样片/开屏片头样片/public/game/background');
    const evFiles = fs.readdirSync(backgroundDir).filter((name) => /^EV_\d+\.png$/.test(name));
    const originalBytes = evFiles.reduce((sum, name) => sum + fs.statSync(path.join(backgroundDir, name)).size, 0);
    say(
      `鉴赏: 页数=${pages} 条目=${rendered.length} 唯一图片=${urls.length} ` +
        `工程内 EV 文件=${evFiles.length} 尺寸异常=${invisible.length}`,
    );
    if (pages < 2) throw new Error(`鉴赏只有 ${pages} 页，条目没有铺开（可能是系列分组或数据缺失）`);
    if (rendered.length !== evFiles.length) {
      throw new Error(`鉴赏条目 ${rendered.length} 与工程内 EV 文件 ${evFiles.length} 不一致`);
    }
    if (urls.length !== rendered.length) throw new Error('鉴赏里有重复条目');
    if (invisible.length > 0) throw new Error(`有 ${invisible.length} 个鉴赏条目尺寸为 0（空白）`);
    if (!urls.every((url) => url.includes('/game/background/thumb/EV_') && url.endsWith('.webp'))) {
      throw new Error('鉴赏列表用的不是缩略图: ' + JSON.stringify(urls.slice(0, 3)));
    }

    // 逐张加载 + 解码，确认没有 404 / 空白；同时统计缩略图总体积
    const imageCheck = await page.evaluate(async (list) => {
      const failed = [];
      let bytes = 0;
      for (const url of list) {
        try {
          const response = await fetch(url, { cache: 'force-cache' });
          if (!response.ok) {
            failed.push({ url, status: response.status });
            continue;
          }
          const blob = await response.blob();
          bytes += blob.size;
          const bitmap = await createImageBitmap(blob);
          if (bitmap.width < 2 || bitmap.height < 2) failed.push({ url, status: 'empty', w: bitmap.width });
          bitmap.close();
        } catch (error) {
          failed.push({ url, status: String(error) });
        }
      }
      return { total: list.length, failed, bytes };
    }, urls);
    say(
      `鉴赏缩略图加载: ${imageCheck.total} 张，失败 ${imageCheck.failed.length}，` +
        `合计 ${(imageCheck.bytes / 1048576).toFixed(2)}MB（原图 ${(originalBytes / 1048576).toFixed(1)}MB）`,
    );
    if (imageCheck.failed.length > 0) {
      throw new Error('鉴赏缩略图加载失败: ' + JSON.stringify(imageCheck.failed.slice(0, 5)));
    }
    if (imageCheck.bytes > originalBytes * 0.25) {
      throw new Error(`缩略图总体积 ${imageCheck.bytes} 未明显小于原图 ${originalBytes}`);
    }

    // 点开第一个条目：全屏预览必须回退到原图（不是缩略图）
    await page.evaluate(() => document.querySelector('[class*="_cgContainer_"] [class*="_cgElement_"]')?.click());
    await page.waitForFunction(() => !!document.querySelector('[class*="_showFullContainer_"]'), { timeout: 10000 });
    const fullPreview = await page.evaluate(async () => {
      const inner = document.querySelector('[class*="_showFullCgMain_"] div');
      const background = inner ? inner.style.backgroundImage : '';
      const url = /url\("?'?([^"')]+)"?'?\)/.exec(background)?.[1] ?? '';
      const response = await fetch(url);
      const bitmap = await createImageBitmap(await response.blob());
      const size = { w: bitmap.width, h: bitmap.height };
      bitmap.close();
      return { url, status: response.status, size };
    });
    say(`鉴赏大图预览: ${JSON.stringify(fullPreview)}`);
    if (!fullPreview.url.includes('/game/background/EV_') || fullPreview.url.includes('/thumb/')) {
      throw new Error('全屏预览没有使用原图: ' + fullPreview.url);
    }
    if (fullPreview.status !== 200 || fullPreview.size.w < 640) {
      throw new Error('全屏预览原图加载异常: ' + JSON.stringify(fullPreview));
    }
    await page.evaluate(() => document.querySelector('[class*="_showFullContainer_"]')?.click());
    await sleep(400);
    const previewClosed = await page.evaluate(() => !document.querySelector('[class*="_showFullContainer_"]'));
    if (!previewClosed) throw new Error('鉴赏大图预览关不掉');

    // 展开原生 BGM 列表，逐首校验音频元数据，再实测播放/暂停/下一首
    const toggled = await page.evaluate(() => {
      const lists = document.querySelectorAll('[class*="_bgmPlayerMain_"] [class*="_bgmControlButton_"]');
      if (lists.length < 5) return false;
      lists[4].click();
      return true;
    });
    if (!toggled) throw new Error('BGM 播放器控制区不存在');
    await sleep(400);
    const bgmItems = await page.evaluate(() =>
      [...document.querySelectorAll('[class*="_bgmListContainer_"] [class*="_bgmElement_"]')].map((node) => ({
        name: node.textContent.trim(),
        className: node.className,
      })),
    );
    const expectedBgmFiles = fs
      .readdirSync(path.resolve('../历史样片/开屏片头样片/public/game/bgm'))
      .filter((name) => /^IS_Pure_BGM_SE_\d+\.mp3$/.test(name));
    say(`BGM 列表: UI 条目=${bgmItems.length} 工程 MP3=${expectedBgmFiles.length}`);
    if (bgmItems.length !== expectedBgmFiles.length || bgmItems.length === 0) {
      throw new Error(`BGM 鉴赏条目 ${bgmItems.length} 与工程 MP3 ${expectedBgmFiles.length} 不符`);
    }
    // 逐首选中：AudioContainer 换成该文件并解出元数据（404 会体现在 audio.error 上）
    const audioMetadata = [];
    for (let i = 0; i < bgmItems.length; i++) {
      await page.evaluate((index) => {
        document.querySelectorAll('[class*="_bgmListContainer_"] [class*="_bgmElement_"]')[index]?.click();
      }, i);
      const loaded = await page.waitForFunction(
        () => {
          const audio = document.querySelector('#currentBgm');
          return audio && audio.currentSrc.includes('IS_Pure_BGM_SE_') && audio.readyState >= 1 && Number.isFinite(audio.duration);
        },
        { timeout: 15000 },
      ).then(async () => page.evaluate(() => {
        const audio = document.querySelector('#currentBgm');
        return {
          src: decodeURI(audio.currentSrc).split('/').pop(),
          duration: Number(audio.duration.toFixed(2)),
          readyState: audio.readyState,
          error: audio.error ? audio.error.code : null,
        };
      }));
      if (!loaded.src || loaded.duration < 60 || loaded.error !== null) {
        throw new Error(`BGM 元数据异常: ${JSON.stringify(loaded)}`);
      }
      audioMetadata.push(loaded);
    }
    say(`BGM 元数据: ${audioMetadata.length} 首全部就绪；时长=${audioMetadata.map((x) => x.duration).join(',')}s`);

    // 通过 WebGAL 播放器按钮实际播放首曲，确认时间前进，再点停止
    await page.evaluate(() => document.querySelector('[class*="_bgmListContainer_"] [class*="_bgmElement_"]')?.click());
    await page.waitForFunction(() => {
      const audio = document.querySelector('#currentBgm');
      return audio && audio.currentSrc.includes('IS_Pure_BGM_SE_00136') && audio.readyState >= 1;
    }, { timeout: 15000 });
    await page.evaluate(() => document.querySelectorAll('[class*="_bgmPlayerMain_"] [class*="_bgmControlButton_"]')[1]?.click());
    await sleep(900);
    const playing = await page.evaluate(() => {
      const audio = document.querySelector('#currentBgm');
      return { paused: audio.paused, currentTime: audio.currentTime, src: decodeURI(audio.currentSrc).split('/').pop() };
    });
    if (playing.paused || playing.currentTime <= 0.3) throw new Error(`BGM 播放按钮未实际播放: ${JSON.stringify(playing)}`);
    await page.evaluate(() => document.querySelectorAll('[class*="_bgmPlayerMain_"] [class*="_bgmControlButton_"]')[3]?.click());
    await sleep(300);
    const stopped = await page.evaluate(() => ({ paused: document.querySelector('#currentBgm').paused }));
    if (!stopped.paused) throw new Error('BGM 停止按钮没有暂停音乐');
    await page.evaluate(() => document.querySelectorAll('[class*="_bgmPlayerMain_"] [class*="_bgmControlButton_"]')[2]?.click());
    await page.waitForFunction(() => {
      const audio = document.querySelector('#currentBgm');
      return audio && audio.currentSrc.includes('IS_Pure_BGM_SE_00143') && audio.readyState >= 1;
    }, { timeout: 15000 });
    const nextTrack = await page.evaluate(() => ({
      src: decodeURI(document.querySelector('#currentBgm').currentSrc).split('/').pop(),
      duration: Number(document.querySelector('#currentBgm').duration.toFixed(2)),
    }));
    say(`BGM 实播: 播放=${JSON.stringify(playing)} 停止=${stopped.paused} 下一首=${JSON.stringify(nextTrack)}`);
    if (!nextTrack.src.includes('00143') || nextTrack.duration < 60) throw new Error('BGM 下一首切换不正确');

    // 关闭鉴赏，回到标题，并确认片头循环没有被破坏
    const closeClicked = await page.evaluate(() => {
      const icon = document.querySelector('[class*="_extra_top_icon_"]');
      if (!icon) return false;
      icon.click();
      return true;
    });
    if (!closeClicked) throw new Error('鉴赏面板没有关闭按钮');
    await sleep(600);
    const closed = await page.evaluate(() => !document.querySelector('[class*="_extra_top_"]'));
    if (!closed) throw new Error('鉴赏面板关不掉');
    state = await readState(page);
    say(`关闭鉴赏: 面板已关=${closed} 标题=${state.titleExposed} 片头=${state.video}`);
    if (!state.titleExposed) throw new Error('关闭鉴赏后没有回到标题');

    let resumed = null;
    for (let i = 0; i < 40; i++) {
      await sleep(500);
      state = await readState(page);
      if (state.video) {
        resumed = { ms: (i + 1) * 500, currentTime: state.currentTime };
        break;
      }
    }
    if (!resumed) throw new Error('关闭鉴赏后片头没有恢复循环');
    await sleep(1200);
    const resumedPlaying = await readState(page);
    say(`关闭鉴赏后循环恢复: ${JSON.stringify(resumed)} 1.2s 后 currentTime=${resumedPlaying.currentTime}`);
    if (resumedPlaying.currentTime === null || resumedPlaying.currentTime <= resumed.currentTime) {
      throw new Error('关闭鉴赏后片头恢复但没有前进');
    }

    // 标题“片头回放”：点击后立即重放同一条片头（不复制文件）
    await page.mouse.click(640, 360); // 跳过片头回到标题
    await sleep(900);
    if (!(await clickByText(page, '片头回放'))) throw new Error('标题没有片头回放入口');
    await sleep(1200);
    const replay = await readState(page);
    say(`片头回放: video=${replay.video} duration=${replay.duration} currentTime=${replay.currentTime} muted=${replay.muted}`);
    if (!replay.video) throw new Error('点片头回放没有播放片头');
    if (replay.duration === null || Math.abs(replay.duration - 95.44) > 0.5) {
      throw new Error(`片头回放用的不是整段手机版片头（duration=${replay.duration}）`);
    }
    if (replay.currentTime !== null && replay.currentTime < 0.3) throw new Error('片头回放没有真正开始播放');
    await page.mouse.click(640, 360); // 结束回放，回到标题停留
    await sleep(700);
    state = await readState(page);
    say(`回放结束: 标题=${state.titleExposed} 片头=${state.video}`);
    if (!state.titleExposed) throw new Error('片头回放结束后没有回到标题');

    if (errors.length) throw new Error('pageerror: ' + JSON.stringify(errors));
    say('结论: PASS');
  } finally {
    const logPath = path.resolve('../验证/开屏片头_浏览器测试.log');
    fs.writeFileSync(logPath, [new Date().toISOString(), ...log, ''].join('\n'), 'utf8');
    console.log('日志:', logPath);
    await browser.close();
  }
})().catch((e) => {
  console.error('FAIL:', e.message);
  process.exitCode = 1;
});
