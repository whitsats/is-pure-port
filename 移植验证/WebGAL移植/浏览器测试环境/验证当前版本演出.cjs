const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const {enterDiscTitle, discButton: button} = require('./进入打盘版标题.cjs');

const hdStage = process.argv.includes('--hd-stage');
const origin = `http://127.0.0.1:${hdStage ? 4204 : 4203}/`;

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio']});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 720}});
    const errors = [];
    const loaded = new Set();
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      if (response.ok()) loaded.add(new URL(response.url()).pathname);
    });
    await page.goto(origin, {waitUntil: 'domcontentloaded'});
    const opening = page.locator('video[src*="MV_OP01_phone60.mp4"]');
    await opening.waitFor({state: 'visible', timeout: 20000});
    await page.waitForFunction(() => {
      const video = document.querySelector('video[src*="MV_OP01_phone60.mp4"]');
      return video?.currentTime > 0;
    });
    const metadata = await opening.evaluate(video => ({width: video.videoWidth, height: video.videoHeight,
                                                        duration: video.duration}));
    assert.equal(metadata.width, 2400);
    assert.equal(metadata.height, 1080);
    assert(metadata.duration > 95 && metadata.duration < 96);
    await checkVideoViewport(page, opening);
    assert.equal(await button(page, 'PRESS THE SCREEN TO START').isVisible(), false);
    for (let click = 0; click < 3 && await opening.isVisible(); click++) {
      await opening.click();
      await page.waitForTimeout(250);
    }
    await opening.waitFor({state: 'hidden'});
    await button(page, '鉴赏模式').click();
    const thumbnail = page.locator('[style*="thumb/EV_0088"]').first();
    await thumbnail.waitFor({state: 'visible'});
    await thumbnail.click();
    const overlay = page.locator('[class*="_showFullContainer_"]');
    const full = overlay.locator('[style*="/EV_0088.png"]').first();
    await full.waitFor({state: 'visible'});
    const size = await full.evaluate(async element => {
      const url = element.style.backgroundImage.match(/url\(["']?([^"')]+)["']?\)/)[1];
      const response = await fetch(url);
      const bitmap = await createImageBitmap(await response.blob());
      const dimensions = [bitmap.width, bitmap.height];
      bitmap.close();
      return dimensions;
    });
    assert.deepEqual(size, [2560, 1792]);
    if (hdStage) {
      await overlay.evaluate(element => element.click());
      await page.locator('[class*="_extra_top_icon_"]').click();
      await button(page, '开始游戏').click();
      await page.waitForFunction(async () => {
        const urls = performance.getEntriesByType('resource').map(entry => entry.name);
        const url = urls.find(name => name.includes('/stage/stageStateManager.ts'));
        if (!url) return false;
        const {stageStateManager} = await import(url);
        return stageStateManager.getCalculationStageState().bgName?.includes('disc-hd/EV_0000.png');
      });
      await checkCgBackdrop(page);
      await checkDialogueFrame(page);
      for (const file of ['background/disc-hd/EV_0000.png', 'figure/disc-hd/CHR_0518.png',
                          'background/disc-hd/BG_0218.png']) {
        for (let click = 0; click < 70; click++) {
          if (loaded.has(`/game/${file}`)) break;
          await page.mouse.click(640, 110);
          await page.waitForTimeout(140);
        }
        assert(loaded.has(`/game/${file}`), `浏览器未加载剧情素材 ${file}`);
      }
      await checkWideBackground(page);
      const saved = await readSlot(page, true);
      assert.equal(saved.key, 'ISPv74DiscHD01');
      await enterDiscTitle(page, origin);
      await button(page, '继续游戏').click();
      await button(page, '开始游戏').waitFor({state: 'hidden', timeout: 5000});
      assert.deepEqual(await readSlot(page, false), saved);
      console.log('PASS 高清版独立存档，快存后刷新继续并恢复场景和句子位置');
    }
    assert.deepEqual(errors, []);
    console.log(`PASS ${origin} 片头 ${metadata.width}×${metadata.height}，鉴赏 ${size.join('×')}${hdStage ? '，剧情加载高清背景、CG 和立绘' : ''}`);
    if (hdStage) {
      await testPortraitCg(browser);
      await testEnding(browser);
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

async function checkCgBackdrop(page, filename = 'EV_0000.png') {
  await page.setViewportSize({width: 2400, height: 1080});
  for (let click = 0; click < 20; click++) {
    if (!(await page.locator('#introContainer > div').isVisible())) break;
    await page.mouse.click(1200, 110);
    await page.waitForTimeout(120);
  }
  await page.waitForFunction(async name => {
    const url = performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes('/Core/WebGAL.ts'));
    if (!url) return false;
    const {WebGAL} = await import(url);
    const stage = WebGAL.gameplay.pixiStage;
    const bg = stage?.getStageObjByKey('bg-main');
    const image = bg?.pixiContainer?.children[0];
    return bg?.sourceUrl.endsWith(`/${name}`)
      && image?.scale.x === image?.scale.y && Math.abs(image?.height - stage.stageHeight) < 1
      && image.width < stage.stageWidth
      && getComputedStyle(document.querySelector('.App')).backgroundColor === 'rgba(0, 0, 0, 0)';
  }, filename);
  await page.evaluate(async name => {
    const backdrop = new Image();
    backdrop.src = `./game/background/disc-hd/${name}`;
    await backdrop.decode();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, filename);
  const samples = await countLitPixels(page, [
    {xs: [0.12, 0.14, 0.16], ys: [0.25, 0.4, 0.6]},
    {xs: [0.84, 0.86, 0.88], ys: [0.25, 0.4, 0.6]},
  ]);
  assert(samples.every(count => count >= 6), `CG 内侧留边仍为黑色 ${samples}`);
  await page.setViewportSize({width: 1280, height: 720});
  console.log(`PASS ${filename} 保留完整构图，画布内原黑条透出同一层背景`);
}

async function testPortraitCg(browser) {
  const page = await browser.newPage({viewport: {width: 1280, height: 720}});
  try {
    await page.route('**/game/scene/start.txt', route => route.fulfill({
      contentType: 'text/plain',
      body: 'changeBg:disc-hd/EV_0070.png -duration=0 -next;\n竖幅 CG 定点验证。;\n',
    }));
    await enterDiscTitle(page, origin);
    await button(page, '开始游戏').click();
    await checkCgBackdrop(page, 'EV_0070.png');
  } finally {
    await page.close();
  }
}

async function checkWideBackground(page) {
  const atParkDialogue = () => page.evaluate(async () => {
    const url = performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes('/stage/stageStateManager.ts'));
    if (!url) return false;
    const {stageStateManager} = await import(url);
    return stageStateManager.getCalculationStageState().showText?.includes('嘴上说着不情愿');
  });
  for (let click = 0; click < 120 && !(await atParkDialogue()); click++) {
    await page.mouse.click(640, 110);
    await page.waitForTimeout(120);
  }
  assert(await atParkDialogue(), '未到达截图中的公园对白');
  await page.waitForFunction(async () => {
    const url = performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes('/Core/WebGAL.ts'));
    if (!url) return false;
    const {WebGAL} = await import(url);
    const stage = WebGAL.gameplay.pixiStage;
    const bg = stage?.getStageObjByKey('bg-main');
    const image = bg?.pixiContainer?.children[0];
    return bg?.sourceUrl.endsWith('/BG_0218.png') && bg.pixiContainer.children.length === 1
      && image?.texture.height === 1124
      && Math.abs(image.height - stage.stageHeight) < 1
      && image.width > stage.stageWidth
      && image.scale.x === image.scale.y;
  }, undefined, {timeout: 6000});
  await page.waitForTimeout(250);
  const visibleEdgePixels = await countLitPixels(page, [
    {xs: [0.015, 0.055, 0.13], ys: [0.02, 0.07]},
    {xs: [0.87, 0.945, 0.985], ys: [0.02, 0.07]},
    {xs: [0.015, 0.055, 0.13], ys: [0.92, 0.97]},
    {xs: [0.87, 0.945, 0.985], ys: [0.92, 0.97]},
  ]);
  assert(visibleEdgePixels.every(count => count >= 3), `公园背景未铺到上下边缘 ${visibleEdgePixels}`);
  console.log('PASS 公园背景等比铺满舞台，浏览器截图上下边缘可见');
}

async function checkDialogueFrame(page) {
  const layout = async () => page.evaluate(async () => {
    const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes(suffix));
    const {WebGAL} = await import(live('/Core/WebGAL.ts'));
    const panel = document.getElementById('textBoxMain');
    if (!panel) return null;
    const frame = panel.previousElementSibling;
    const avatar = panel.querySelector('#miniAvatar img');
    const text = panel.lastElementChild.getBoundingClientRect();
    const box = frame.getBoundingClientRect();
    const game = document.querySelector('#root').getBoundingClientRect();
    const style = getComputedStyle(frame);
    return {
      image: style.backgroundImage, mask: style.maskImage,
      inset: box.left - game.left, endInset: game.right - box.right,
      textGap: avatar ? text.left - avatar.getBoundingClientRect().right : null,
      portraitUrl: avatar?.getAttribute('src'),
      portraitLoaded: avatar?.complete && avatar.naturalWidth > 0,
      duplicate: !!WebGAL.gameplay.pixiStage?.getStageObjByKey('ps2Layer4'),
    };
  });
  const initial = await layout();
  assert(initial?.image.includes('ETC_021_p8.png') && initial.image.includes('ETC_021_p9.png'));
  assert.equal(initial.mask, 'none');
  assert(initial.inset > 100 && initial.endInset > 100);

  let portrait;
  for (let click = 0; click < 25; click++) {
    portrait = await layout();
    if (portrait?.portraitUrl?.endsWith('/CHR_0518.png')) break;
    await page.mouse.click(640, 110);
    await page.waitForTimeout(130);
  }
  await page.locator('#miniAvatar img[src$="/CHR_0518.png"]').evaluate(image => image.decode());
  portrait = await layout();
  assert(portrait.image.includes('ETC_021_p12.png') && portrait.image.includes('ETC_021_p13.png'));
  assert.equal(portrait.mask, 'none');
  assert(portrait.portraitLoaded && !portrait.duplicate);
  assert(portrait.textGap >= 25 && portrait.textGap <= 70, `头像到正文间距 ${portrait.textGap}px`);
  if (process.env.WEBGAL_DIALOGUE_SCREENSHOT) {
    await page.waitForTimeout(800);
    await page.screenshot({path: process.env.WEBGAL_DIALOGUE_SCREENSHOT});
  }
  console.log(`PASS 原作普通框及带头像框，文字与头像间距 ${portrait.textGap.toFixed(0)}px，画布侧边无遮罩`);
}

async function countLitPixels(page, areas) {
  const image = (await page.screenshot()).toString('base64');
  return page.evaluate(async ({png, areas}) => {
    const bitmap = await createImageBitmap(await (await fetch(`data:image/png;base64,${png}`)).blob());
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(bitmap, 0, 0);
    bitmap.close();
    return areas.map(({xs, ys}) => xs.flatMap(x => ys.map(y => {
      const [r, g, b] = ctx.getImageData(Math.round(canvas.width * x), Math.round(canvas.height * y), 1, 1).data;
      return Math.max(r, g, b) > 35;
    })).filter(Boolean).length);
  }, {png: image, areas});
}

function readSlot(page, save) {
  return page.evaluate(async store => {
    const urls = performance.getEntriesByType('resource').map(entry => entry.name);
    const live = path => import(urls.find(name => name.includes(path)));
    const [{WebGAL}, {fastSaveGame, hasFastSaveRecord}] = await Promise.all(
      ['/Core/WebGAL.ts', '/storage/fastSaveLoad.ts'].map(live));
    if (store) await fastSaveGame();
    if (!await hasFastSaveRecord()) throw new Error('快存记录不存在');
    return {key: WebGAL.gameKey, scene: WebGAL.sceneManager.sceneData.currentScene.sceneName,
            sentence: WebGAL.sceneManager.sceneData.currentSentenceId};
  }, save);
}

async function checkVideoViewport(page, video) {
  const viewports = [
    {width: 2400, height: 1080, fit: 'contain'},
    {width: 2340, height: 1080, fit: 'cover'},
    {width: 2520, height: 1080, fit: 'contain'},
    {width: 1280, height: 720, fit: 'cover'},
  ];
  const player = await video.elementHandle();
  for (const {width, height, fit} of viewports) {
    await page.setViewportSize({width, height});
    await page.waitForFunction(({player, width, height, fit}) => {
      const box = player.getBoundingClientRect();
      const corners = [[2, 2], [width - 2, height - 2]];
      return Math.abs(box.x) < 1 && Math.abs(box.y) < 1
        && Math.abs(box.width - width) < 1 && Math.abs(box.height - height) < 1
        && getComputedStyle(player).objectFit === fit
        && corners.every(([x, y]) => document.elementFromPoint(x, y) === player);
    }, {player, width, height, fit}, {timeout: 4000});
  }
  assert(await player.evaluate(video => video.isConnected));
}

async function testEnding(browser) {
  const sceneFile = path.join(__dirname, '../新游戏打盘高清版/public/game/scene/mac_055_0x00000c.txt');
  const scene = fs.readFileSync(sceneFile, 'utf8');
  const videoLine = scene.match(/^playVideo:MV_END01_phone60\.mp4;\r?$/m)?.[0].trim();
  assert(videoLine, 'MAC_055 的编译产物缺少片尾指令');
  assert.match(scene, /playVideo:MV_END01_phone60\.mp4;\s*setVar:mac_6000=0 -next;\s*changeScene:mac_056_/);
  const page = await browser.newPage({viewport: {width: 1280, height: 720}});
  try {
    await page.route('**/game/scene/start.txt', route => route.fulfill({
      contentType: 'text/plain',
      body: `${videoLine}\n片尾后推进，定点验证。;\nend;\n`,
    }));
    await enterDiscTitle(page, origin);
    await button(page, '开始游戏').click();
    const movie = page.locator('#playVideoElement');
    await movie.waitFor({state: 'visible'});
    await page.waitForFunction(() => document.querySelector('#playVideoElement')?.currentTime > 0);
    await checkVideoViewport(page, movie);
    const movieSize = await movie.evaluate(video => {
      video.currentTime = video.duration - 0.5;
      return {w: video.videoWidth, h: video.videoHeight, seconds: video.duration,
              fit: getComputedStyle(video).objectFit};
    });
    assert.equal(movieSize.w, 2400);
    assert.equal(movieSize.h, 1080);
    assert.equal(movieSize.fit, 'cover');
    assert(movieSize.seconds > 95 && movieSize.seconds < 96);
    await movie.waitFor({state: 'hidden'});
    await page.waitForFunction(async () => {
      const url = performance.getEntriesByType('resource').map(entry => entry.name)
        .find(name => name.includes('/stage/stageStateManager.ts'));
      if (!url) return false;
      const {stageStateManager} = await import(url);
      return stageStateManager.getCalculationStageState().showText === '片尾后推进，定点验证。';
    });
    const start = button(page, '开始游戏');
    for (let click = 0; click < 20 && !(await start.isVisible()); click++) {
      await page.mouse.click(640, 110);
      await page.waitForTimeout(100);
    }
    assert(await start.isVisible(), '测试剧情未在 end 指令后回到标题');
    console.log(`PASS 片尾 ${movieSize.w}×${movieSize.h} / ${Math.round(movieSize.seconds)} 秒，播放结束后恢复剧情并回标题`);
  } finally {
    await page.close();
  }
}
