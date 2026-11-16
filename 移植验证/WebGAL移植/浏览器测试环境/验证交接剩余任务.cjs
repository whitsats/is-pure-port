// 交接剩余任务的无头验收：EV 转场立绘、数值/存读档、鉴赏解锁、流程图。
// 只读引擎运行状态，不手写剧情变量；唯一的人为跳转是最后的鉴赏 BGM 定点触发。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const {enterDiscTitle, discButton: button} = require('./进入打盘版标题.cjs');

const origin = 'http://127.0.0.1:4204/';
const SCENE = 'mac_000_0x00000c.txt';
const executablePath = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

async function live(page, pathFragment) {
  return page.evaluate(async fragment => {
    const url = performance.getEntriesByType('resource').map(e => e.name)
      .find(name => name.includes(fragment));
    if (!url) throw new Error(`未找到模块 ${fragment}`);
    return url;
  }, pathFragment);
}

async function dialogue(page) {
  return page.evaluate(() => [...document.querySelectorAll('#textBoxMain span[id]')].map(element => {
    const text = element.textContent || '';
    const length = text.length / 3;
    const first = text.slice(0, length);
    return length > 0 && Number.isInteger(length) && first.repeat(3) === text ? first : text;
  }).join('').replace(/\s+/gu, ''));
}

async function advanceTo(page, needle, max = 320) {
  const wanted = needle.replace(/\s+/gu, '');
  for (let step = 0; step < max; step++) {
    if ((await dialogue(page)).includes(wanted)) return;
    await page.waitForTimeout(120);
    if ((await dialogue(page)).includes(wanted)) return;
    await page.mouse.click(640, 600);
    await page.waitForTimeout(120);
  }
  throw new Error(`未到达对白「${needle}」，当前「${await dialogue(page)}」`);
}

function sceneLine(scene, needle) {
  const lines = fs.readFileSync(path.join(__dirname, '../新游戏打盘高清版/public/game/scene', scene), 'utf8')
    .split(/\r?\n/);
  const index = lines.findIndex(line => line.includes(needle));
  if (index < 0) throw new Error(`场景 ${scene} 没有「${needle}」`);
  return index + 1;
}

async function advanceToLine(page, scene, needle, max = 400) {
  const target = sceneLine(scene, needle);
  for (let step = 0; step < max; step++) {
    const current = await page.evaluate(async () => {
      const url = performance.getEntriesByType('resource').map(e => e.name)
        .find(name => name.includes('/Core/WebGAL.ts'));
      const {WebGAL} = await import(url);
      return {scene: WebGAL.sceneManager.sceneData.currentScene.sceneName,
              sentence: WebGAL.sceneManager.sceneData.currentSentenceId};
    });
    if (current.scene !== scene) throw new Error(`场景已离开 ${scene}: ${current.scene}`);
    if (current.sentence >= target) return;
    await page.mouse.click(640, 600);
    await page.waitForTimeout(90);
  }
  throw new Error(`未到达 ${scene}:${target}「${needle}」`);
}

async function advanceToSceneLine(page, scene, needle, max = 800) {
  const target = sceneLine(scene, needle);
  for (let step = 0; step < max; step++) {
    const current = await page.evaluate(async () => {
      const url = performance.getEntriesByType('resource').map(e => e.name)
        .find(name => name.includes('/Core/WebGAL.ts'));
      const {WebGAL} = await import(url);
      return {scene: WebGAL.sceneManager.sceneData.currentScene.sceneName,
              sentence: WebGAL.sceneManager.sceneData.currentSentenceId};
    });
    if (current.scene === scene && current.sentence >= target) return;
    if (current.scene > scene && current.scene !== scene) {
      throw new Error(`已越过目标场景 ${scene}: ${current.scene}`);
    }
    await page.mouse.click(640, 600);
    await page.waitForTimeout(70);
  }
  throw new Error(`未到达 ${scene}:${target}「${needle}」`);
}

async function advanceToScene(page, scene, max = 1200) {
  for (let step = 0; step < max; step++) {
    const current = await page.evaluate(async () => {
      const url = performance.getEntriesByType('resource').map(e => e.name)
        .find(name => name.includes('/Core/WebGAL.ts'));
      const {WebGAL} = await import(url);
      return {scene: WebGAL.sceneManager.sceneData.currentScene.sceneName,
              sentence: WebGAL.sceneManager.sceneData.currentSentenceId};
    });
    if (current.scene === scene && current.sentence >= 2) return;
    await page.mouse.click(640, 600);
    await page.waitForTimeout(70);
  }
  throw new Error(`未进入场景 ${scene}`);
}

async function stage(page) {
  const url = await live(page, '/Core/Modules/stage/stageStateManager.ts');
  return page.evaluate(async moduleUrl => {
    const {stageStateManager} = await import(moduleUrl);
    const {WebGAL} = await import(performance.getEntriesByType('resource').map(e => e.name)
      .find(name => name.includes('/Core/WebGAL.ts')));
    const pixi = WebGAL.gameplay.pixiStage;
    const visible = key => !!pixi?.getStageObjByKey(key);
    return {
      scene: WebGAL.sceneManager.sceneData.currentScene.sceneName,
      sentence: WebGAL.sceneManager.sceneData.currentSentenceId,
      bg: pixi?.getStageObjByKey('bg-main')?.sourceUrl || '',
      layer1: visible('ps2Layer1'), layer2: visible('ps2Layer2'),
      layer3: visible('ps2Layer3'), layer4: visible('ps2Layer4'),
      bgm: stageStateManager.getCalculationStageState().bgm?.src || '',
      vars: Object.fromEntries(Object.entries(stageStateManager.getCalculationStageState().GameVar)
        .filter(([key]) => /^mac_(6026|602a|602b|602c)$/i.test(key))),
      figures: stageStateManager.getCalculationStageState().freeFigure.map(item => item.key),
    };
  }, url);
}

async function startGame(page) {
  await enterDiscTitle(page, origin);
  await button(page, '开始游戏').click();
  await waitForScene(page, SCENE);
}

async function waitForScene(page, scene) {
  for (let attempt = 0; attempt < 80; attempt++) {
    if ((await stage(page)).scene === scene) return;
    await page.waitForTimeout(250);
  }
  throw new Error(`场景未加载 ${scene}`);
}

async function quickSave(page) {
  const url = await live(page, '/storage/fastSaveLoad.ts');
  await page.evaluate(async moduleUrl => {
    const {fastSaveGame} = await import(moduleUrl);
    await fastSaveGame();
  }, url);
}

async function reloadAndContinue(page) {
  const saved = await page.evaluate(async () => {
    const url = performance.getEntriesByType('resource').map(e => e.name)
      .find(name => name.includes('/Core/WebGAL.ts'));
    const {WebGAL} = await import(url);
    return {scene: WebGAL.sceneManager.sceneData.currentScene.sceneName,
            sentence: WebGAL.sceneManager.sceneData.currentSentenceId};
  });
  await page.reload({waitUntil: 'domcontentloaded'});
  await enterDiscTitle(page, origin);
  await button(page, '继续游戏').click();
  await page.waitForFunction(async wanted => {
    const url = performance.getEntriesByType('resource').map(e => e.name)
      .find(name => name.includes('/Core/WebGAL.ts'));
    if (!url) return false;
    const {WebGAL} = await import(url);
    return WebGAL.sceneManager.sceneData.currentScene.sceneName === wanted.scene
      && WebGAL.sceneManager.sceneData.currentSentenceId === wanted.sentence;
  }, saved, {timeout: 20000});
  return saved;
}

async function appreciation(page) {
  const url = await live(page, '/store/store.ts');
  return page.evaluate(async moduleUrl => {
    const {webgalStore} = await import(moduleUrl);
    const data = webgalStore.getState().userData.appreciationData;
    return {cg: data.cg.map(item => item.name), bgm: data.bgm.map(item => item.name)};
  }, url);
}

async function testEvAndStats(browser) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  const page = await context.newPage();
  await page.addInitScript(() => {
    const originalPlay = HTMLMediaElement.prototype.play;
    const originalPause = HTMLMediaElement.prototype.pause;
    window.discAmbience = [];
    HTMLMediaElement.prototype.play = function () {
      if (this.src.endsWith('/SE_00139.opus')) {
        window.discAmbience.push({type: 'play', loop: this.loop, volume: this.volume});
        this.addEventListener('playing', () => window.discAmbience.push({type: 'playing'}), {once: true});
      }
      return originalPlay.call(this);
    };
    HTMLMediaElement.prototype.pause = function () {
      if (this.src.endsWith('/SE_00139.opus')) window.discAmbience.push({type: 'pause'});
      return originalPause.call(this);
    };
  });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await startGame(page);
    let state = await stage(page);
    assert.equal(state.scene, 'mac_000_0x00000c.txt');
    assert.equal(state.vars.mac_6026, 20);
    assert.equal(state.vars.mac_602a, 20);
    assert.equal(state.vars.mac_602b, 20);
    assert.equal(state.vars.mac_602c, 20);
    await page.waitForFunction(() => window.discAmbience.some(event => event.type === 'playing'),
      null, {timeout: 5000});
    const ambience = await page.evaluate(() => window.discAmbience.find(event => event.type === 'play'));
    assert(ambience.loop && ambience.volume > 0);

    // 转场前最后一拍：寺谷仍在第 1 层；快存后进入 EV_0002，第 1 层应被收起。
    await advanceToLine(page, SCENE, '一贵「那是……」');
    state = await stage(page);
    assert.equal(state.layer1, true, 'EV_0002 前第 1 层应仍在');
    await quickSave(page);
    await reloadAndContinue(page);
    await page.waitForTimeout(1200);
    await advanceToLine(page, SCENE, '一贵「那是……」');
    state = await stage(page);
    assert.equal(state.layer1, true, '读档后 EV 前第 1 层应恢复');
    await advanceToLine(page, SCENE, '濑户，你过来一下');
    state = await stage(page);
    assert.match(state.bg, /BG_0250\.png$/);
    assert.equal(state.layer1, false, '蓝天回忆第一句就应收起寺谷');
    const webgalUrl = await live(page, '/Core/WebGAL.ts');
    await page.waitForFunction(async url => {
      const {WebGAL} = await import(url);
      return !WebGAL.gameplay.pixiStage.getFigureObjects().some(figure => figure.key.startsWith('ps2Layer1'));
    }, webgalUrl, {timeout: 5000});
    await advanceToLine(page, SCENE, '一贵「什，什么啊？」');
    state = await stage(page);
    assert.equal(state.layer1, false, '读档后进入 EV 仍应清除');

    // 回忆段的第二张 EV 和「哪有他那样说话的呀」不得有残影。
    await advanceToLine(page, SCENE, '哪有他那样说话的呀');
    state = await stage(page);
    assert.equal(state.layer1, false, '回忆段不应有寺谷残影');
    await page.mouse.click(640, 600);
    await advanceToLine(page, SCENE, '回头一看，发现背后站着一个女孩');
    state = await stage(page);
    assert.equal(state.layer1, false, 'EV_0004 后仍不应有残影');

    // 原盘在切回公园后重放寺谷，第二个蓝天转场再清理人物。
    await advanceToLine(page, SCENE, '那之后，你和那人之间怎么样了');
    state = await stage(page);
    assert.equal(state.layer1, true, '寺谷回来时应重新入场');
    assert.match(state.bg, /BG_0218\.png$/);
    await advanceToLine(page, SCENE, 'VOICE_00040.wav');
    state = await stage(page);
    assert.match(state.bg, /BG_0250\.png$/);
    assert.equal(state.layer1, false, '第二次蓝天转场首句应收起寺谷');
    assert(!state.figures.includes('ps2Layer1'), '第二次转场应从剧情状态移除寺谷');
    await page.waitForFunction(async url => {
      const {WebGAL} = await import(url);
      return !WebGAL.gameplay.pixiStage.getFigureObjects().some(figure => figure.key.startsWith('ps2Layer1'));
    }, webgalUrl, {timeout: 5000});
    await advanceToLine(page, SCENE, '……４年前');
    state = await stage(page);
    assert.equal(state.layer1, false, '第二次蓝天转场的后续对白也不应残留寺谷');
    await advanceToLine(page, SCENE, 'wait:2000');
    await page.waitForFunction(() => window.discAmbience.at(-1)?.type === 'pause', null, {timeout: 5000});

    // 数值写入：进入已核实的「道歉」分支场景，读它在原盘 0x3AFC 起的四连写。
    // （选项按钮本身的 65 组实点记录见 数据/分支扫描_含嵌套_全量.json。）
    const sceneUrl = '/src/Core/controller/scene/changeScene.ts';
    await page.evaluate(async moduleUrl => {
      const {changeScene} = await import(moduleUrl);
      await changeScene('./game/scene/mac_001_0x0038c4.txt', 'mac_001_0x0038c4.txt');
    }, sceneUrl);
    await page.waitForTimeout(800);
    const before = (await stage(page)).vars;
    await advanceToLine(page, 'mac_001_0x0038c4.txt', '一贵「站住！」', 120);
    const afterChoice = (await stage(page)).vars;
    assert.notDeepEqual(afterChoice, before, '分支写入后数值应有变化');

    await page.evaluate(async moduleUrl => {
      const {changeScene} = await import(moduleUrl);
      await changeScene('./game/scene/mac_002_0x00000c.txt', 'mac_002_0x00000c.txt');
    }, sceneUrl);
    await page.waitForTimeout(800);
    const chapter2 = await stage(page);
    assert(chapter2.scene.startsWith('mac_002_'), '应进入 MAC_002');
    assert.deepEqual(chapter2.vars, afterChoice, '跨章后数值应保留');
    await quickSave(page);
    await reloadAndContinue(page);
    await page.waitForTimeout(1000);
    const loaded = await stage(page);
    assert.deepEqual(loaded.vars, afterChoice, '读档后数值应恢复');

    // 用真实第 19 章剧本的局部入口，连续验证保留和清除。
    const scene19 = 'mac_019_0x00000c.txt';
    const sourceLine = sceneLine(scene19, '拿起最后一个水桶');
    const [parserUrl, nextUrl] = await Promise.all([
      live(page, '/Core/parser/sceneParser.ts'),
      live(page, '/Core/controller/gamePlay/nextSentence.ts'),
    ]);
    await page.evaluate(async ({webgalUrl, parserUrl, nextUrl, scene19, sourceLine}) => {
      const [{WebGAL}, {sceneParser}, {continueSentence}] = await Promise.all(
        [webgalUrl, parserUrl, nextUrl].map(url => import(url)),
      );
      const url = './game/scene/' + scene19;
      const text = await (await fetch(url)).text();
      WebGAL.sceneManager.sceneData.currentScene = sceneParser(text, scene19, url);
      WebGAL.sceneManager.sceneData.currentSentenceId = sourceLine;
      WebGAL.flowchartManager.cancelPending();
      continueSentence();
    }, {webgalUrl, parserUrl, nextUrl, scene19, sourceLine});
    await advanceToLine(page, scene19, 'VOICE_04058.wav', 20);
    assert.equal((await stage(page)).layer1, true, '伊织应先出场');
    await advanceToLine(page, scene19, 'VOICE_04060.wav', 20);
    state = await stage(page);
    assert.match(state.bg, /BG_0016\.png$/);
    assert.equal(state.layer1, true, '原盘标志为 1 的转场应保留伊织');
    await advanceToLine(page, scene19, 'VOICE_04065.wav', 30);
    state = await stage(page);
    assert.match(state.bg, /BG_0024\.png$/);
    assert.equal(state.layer1, false, '原盘标志为 0 的转场应收起伊织');
    assert(!state.figures.includes('ps2Layer1'));

    assert.deepEqual(errors, []);
    console.log('PASS 两次蓝天转场、EV 转场、人物重新入场、第 19 章保留和清除、转场前快存读档');
    console.log('PASS 数值初值 20、分支加减、跨章与读档保留', before, afterChoice);
  } finally {
    await context.close();
  }
}

function currentScene(state) {
  return state.scene.startsWith('mac_002_');
}

async function testAppreciation(browser) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  const page = await context.newPage();
  await page.addInitScript(() => performance.setResourceTimingBufferSize(5000));
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await enterDiscTitle(page, origin, {waitForOpeningPlayback: true});
    await page.waitForTimeout(1200);
    let gallery = await appreciation(page);
    // 干净档案不预置任何条目；标题片头真正起播后才解锁 EV_OP01。
    assert.equal(gallery.cg.includes('EV_OP01「オープニング」'), true, '片头播放后应解锁 EV_OP01');
    assert.equal(gallery.cg.includes('EV036「泉と神社へ」'), false, '未到第 37 章时 EV036 应锁定');
    assert.equal(gallery.cg.includes('EV_END01「エンディング」'), false, '未看片尾时 EV_END01 应锁定');
    assert.deepEqual(gallery.bgm, [], '干净档案不应预置 BGM');
    assert.equal(gallery.cg.filter(name => name === 'EV_OP01「オープニング」').length, 1, '片头 CG 不应重复');

    await button(page, '开始游戏').click();
    await waitForScene(page, SCENE);
    await advanceToLine(page, SCENE, '伊织是高中话剧团的成员。', 60);
    gallery = await appreciation(page);
    assert.equal(gallery.cg.includes('EV_0000'), true, '显示 EV_0000 后应解锁');
    assert.equal(gallery.cg.filter(name => name === 'EV_0000').length, 1, 'CG 不应重复');

    await advanceToLine(page, SCENE, '一贵「那是……」');
    await page.mouse.click(640, 600);
    await advanceToLine(page, SCENE, '一贵「什，什么啊？」');
    gallery = await appreciation(page);
    assert.equal(gallery.cg.includes('EV_0002'), true, '显示 EV_0002 后应解锁');
    const count = gallery.cg.length;

    await page.reload({waitUntil: 'domcontentloaded'});
    await enterDiscTitle(page, origin);
    gallery = await appreciation(page);
    assert.equal(gallery.cg.includes('EV_0000') && gallery.cg.includes('EV_0002'), true,
      '刷新后解锁应保留');
    assert.equal(gallery.cg.length, count, '刷新不应重复解锁');
    assert.equal(gallery.cg.filter(name => name === 'EV_OP01「オープニング」').length, 1,
      '刷新后片头 CG 不应重复');

    // BGM：直接进入已验证会起播 SE_00146 的分支场景，验证实际播放与解锁。
    await button(page, '开始游戏').click();
    await page.waitForTimeout(2000);
    const sceneUrl = '/src/Core/controller/scene/changeScene.ts';
    await page.evaluate(async moduleUrl => {
      const {changeScene} = await import(moduleUrl);
      await changeScene('./game/scene/mac_001_0x0038c4.txt', 'mac_001_0x0038c4.txt');
    }, sceneUrl);
    await page.waitForTimeout(800);
    for (let step = 0; step < 12; step++) {
      await page.mouse.click(640, 600);
      await page.waitForTimeout(150);
    }
    const audio = await stage(page);
    gallery = await appreciation(page);
    assert.equal(gallery.bgm.includes('曲目04'), true, 'BGM 应解锁并显示简短曲目名称');
    assert.match(audio.bgm, /IS_Pure_BGM_SE_00146\.mp3/, 'BGM 应实际播放');

    // BGM 解锁也要经刷新保留，且不产生重复条目。
    await page.reload({waitUntil: 'domcontentloaded'});
    await enterDiscTitle(page, origin);
    gallery = await appreciation(page);
    assert.equal(gallery.bgm.filter(name => name === '曲目04').length, 1,
      '刷新后 BGM 解锁应保留且不重复');
    await button(page, '开始游戏').click();
    await page.waitForTimeout(2000);

    // EV036：第 37 章入口的原生 unlockCg；正文不显示这张图，只进鉴赏。
    await page.evaluate(async moduleUrl => {
      const {changeScene} = await import(moduleUrl);
      await changeScene('./game/scene/mac_037_0x00000c.txt', 'mac_037_0x00000c.txt');
    }, sceneUrl);
    await page.waitForTimeout(1000);
    gallery = await appreciation(page);
    assert.equal(gallery.cg.includes('EV036「泉と神社へ」'), false, '只进入第 37 章还未到神社时 EV036 应锁定');
    await advanceToLine(page, 'mac_037_0x00000c.txt', '我一个人走进了神社。');
    // 第一次点击只结束该句打字，后再点一次才执行紧跟其后的 unlockCg 行。
    for (let step = 0; step < 8; step++) {
      gallery = await appreciation(page);
      if (gallery.cg.includes('EV036「泉と神社へ」')) break;
      await page.mouse.click(640, 600);
      await page.waitForTimeout(300);
    }
    assert.equal(gallery.cg.includes('EV036「泉と神社へ」'), true, '走进神社事件后 EV036 应解锁');
    assert.equal(gallery.cg.filter(name => name === 'EV036「泉と神社へ」').length, 1, 'EV036 不应重复');
    assert.equal(gallery.cg.includes('EV_END01「エンディング」'), false, '未播放片尾时 EV_END01 仍应锁定');

    // 只鉴赏出现的 CG 也要刷新保留，且仍不重复。
    await page.reload({waitUntil: 'domcontentloaded'});
    await enterDiscTitle(page, origin);
    gallery = await appreciation(page);
    assert.equal(gallery.cg.filter(name => name === 'EV036「泉と神社へ」').length, 1,
      '刷新后 EV036 应保留且不重复');
    assert.equal(gallery.cg.includes('EV_END01「エンディング」'), false,
      '刷新后未触发的 EV_END01 仍应锁定');
    await button(page, '开始游戏').click();
    await page.waitForTimeout(2000);

    // EV_END01：跳到终章片尾指令本身，等视频真正起播后检查原生解锁。
    await page.evaluate(async moduleUrl => {
      const {changeScene} = await import(moduleUrl);
      await changeScene('./game/scene/mac_055_0x00000c.txt', 'mac_055_0x00000c.txt');
    }, sceneUrl);
    await waitForScene(page, 'mac_055_0x00000c.txt');
    await page.evaluate(async () => {
      const resources = performance.getEntriesByType('resource').map(e => e.name);
      const live = suffix => import(resources.find(name => name.includes(suffix)));
      const [{WebGAL}, {stopAllPerform}, {forward, commitForward}] = await Promise.all(
        ['/Core/WebGAL.ts', '/gamePlay/stopAllPerform.ts', '/gamePlay/nextSentence.ts'].map(live),
      );
      const index = WebGAL.sceneManager.sceneData.currentScene.sentenceList.findIndex(item => item.commandRaw === 'playVideo');
      if (index < 0) throw new Error('终章场景应包含 playVideo');
      stopAllPerform();
      WebGAL.sceneManager.sceneData.currentSentenceId = index;
      if (!forward()) throw new Error('片尾指令未能推进');
      commitForward();
    });
    await page.waitForFunction(() => document.getElementById('playVideoElement')?.currentTime > 0,
      null, {timeout: 15000});
    gallery = await appreciation(page);
    assert.equal(gallery.cg.includes('EV_END01「エンディング」'), true, '片尾视频起播后 EV_END01 应解锁');
    assert.equal(gallery.cg.filter(name => name === 'EV_END01「エンディング」').length, 1, 'EV_END01 不应重复');

    assert.deepEqual(errors, []);
    console.log('PASS 鉴赏：干净档案无预置；片头 EV_OP01、正文 EV_0000/EV_0002、正文 BGM SE_00146、走进神社后 EV036 解锁；重复去重、刷新保留、未触发锁定');
  } finally {
    await context.close();
  }
}

async function testFlowchart(browser) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  const page = await context.newPage();
  try {
    await startGame(page);
    await page.waitForTimeout(2500);
    const stateUrl = await live(page, '/Core/Modules/stage/stageStateManager.ts');
    const result = await page.evaluate(async stageUrl => {
      const {WebGAL} = await import(performance.getEntriesByType('resource').map(e => e.name)
        .find(name => name.includes('/Core/WebGAL.ts')));
      const manager = WebGAL.flowchartManager;
      const snapshot = await manager.loadSnapshot('main', 'chapter_000');
      const {stageStateManager} = await import(stageUrl);
      const vars = stageStateManager.getCalculationStageState().GameVar;
      return {
        root: manager.isUnlocked('main', 'chapter_000'),
        first: manager.isUnlocked('main', 'chapter_001'),
        far: manager.isUnlocked('main', 'chapter_010'),
        branchVisible: manager.getVisibleFlowcharts().some(f => f.id === 'mac_001_branch'),
        hasSnapshot: !!snapshot,
        snapshotScene: snapshot?.sceneData?.sceneName,
        snapshotSentence: snapshot?.sceneData?.currentSentenceId,
        snapshotVars: snapshot?.nowStageState?.GameVar?.mac_6026,
        liveVar: vars.mac_6026,
        enabled: manager.enabled,
        flowcharts: manager.getFlowcharts().length,
        lockedSnapshot: await manager.loadSnapshot('main', 'chapter_010'),
      };
    }, stateUrl);
    assert.equal(result.root, true);
    assert.equal(result.first, false);
    assert.equal(result.far, false);
    assert.equal(result.hasSnapshot, true);
    assert.equal(result.snapshotScene, 'mac_000_0x00000c.txt');
    assert.equal(result.snapshotVars, 20);
    assert.equal(result.branchVisible, false, '未走分支前个人线流程图应隐藏');
    assert.equal(result.lockedSnapshot, null, '锁定节点不应有可读取的快照');

    const snapshot = await page.evaluate(async () => {
      const {WebGAL} = await import(performance.getEntriesByType('resource').map(e => e.name)
        .find(name => name.includes('/Core/WebGAL.ts')));
      return WebGAL.flowchartManager.loadSnapshot('main', 'chapter_000');
    });
    for (let step = 0; step < 25; step++) {
      await page.mouse.click(640, 600);
      await page.waitForTimeout(100);
    }
    const loadUrl = await live(page, '/storage/loadGame.ts');
    await page.evaluate(async ([moduleUrl, saved]) => {
      const {loadGameFromStageData} = await import(moduleUrl);
      loadGameFromStageData({...saved, backlog: [], previewImage: ''});
    }, [loadUrl, snapshot]);
    await page.waitForTimeout(1200);
    const restored = await stage(page);
    assert.equal(restored.scene, 'mac_000_0x00000c.txt');
    assert.equal(restored.sentence, result.snapshotSentence, '跳转应恢复原句位置');
    assert.deepEqual(restored.vars, {mac_6026: 20, mac_602a: 20, mac_602b: 20, mac_602c: 20});

    await page.mouse.move(720, 520);
    await button(page, '流程图').click({timeout: 5000});
    await page.waitForTimeout(800);
    const shown = await page.evaluate(() => document.body.innerText);
    assert.match(shown, /第01话/);

    await page.reload({waitUntil: 'domcontentloaded'});
    await enterDiscTitle(page, origin);
    const persisted = await page.evaluate(async () => {
      const {WebGAL} = await import(performance.getEntriesByType('resource').map(e => e.name)
        .find(name => name.includes('/Core/WebGAL.ts')));
      return WebGAL.flowchartManager.isUnlocked('main', 'chapter_000');
    });
    assert.equal(persisted, true, '刷新后流程图进度应保留');
    console.log('PASS 流程图：首章解锁、远章锁定、快照可恢复、刷新保留');
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({headless: true, executablePath, args: ['--mute-audio']});
  try {
    const transitions = process.argv.includes('--transitions');
    const appreciation = process.argv.includes('--appreciation');
    if (transitions || !appreciation) await testEvAndStats(browser);
    if (appreciation || !transitions) await testAppreciation(browser);
    if (!transitions && !appreciation) await testFlowchart(browser);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
