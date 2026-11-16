// 真实按钮走第 2 话开篇选项 + 第 3 话阈值两侧，不直接写 GameVar。
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { enterDiscTitle, discButton: button } = require('./进入打盘版标题.cjs');

const origin = 'http://127.0.0.1:4204/';
const executablePath = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

async function startGame(page) {
  await enterDiscTitle(page, origin);
  await button(page, '开始游戏').click();
  await page.waitForFunction(async () => {
    const url = performance.getEntriesByType('resource').map(e => e.name)
      .find(name => name.includes('/Core/WebGAL.ts'));
    if (!url) return false;
    const { WebGAL } = await import(url);
    return WebGAL.sceneManager.sceneData.currentScene.sceneName === 'mac_000_0x00000c.txt';
  }, null, { timeout: 20000 });
  await page.evaluate(async () => {
    const find = fragment => performance.getEntriesByType('resource').map(e => e.name)
      .find(name => name.includes(fragment));
    const { nextSentence } = await import(find('/Core/controller/gamePlay/nextSentence.ts'));
    const { WebGAL } = await import(find('/Core/WebGAL.ts'));
    const { stageStateManager } = await import(find('/Core/Modules/stage/stageStateManager.ts'));
    window.__valueProbe = { nextSentence, WebGAL, stageStateManager };
  });
}

async function snapshot(page) {
  return page.evaluate(() => {
    const { WebGAL, stageStateManager } = window.__valueProbe;
    const choose = document.querySelector('#chooseContainer');
    const vars = Object.fromEntries(Object.entries(stageStateManager.getCalculationStageState().GameVar)
      .filter(([key]) => /^mac_60(26|2a|2b|2c)$/i.test(key)));
    return {
      scene: WebGAL.sceneManager.sceneData.currentScene.sceneName,
      sentence: WebGAL.sceneManager.sceneData.currentSentenceId,
      choices: choose && choose.textContent.trim()
        ? [...choose.querySelectorAll('div')].filter(item => !item.querySelector('div'))
            .map(item => item.textContent.trim()).filter(Boolean)
        : [],
      vars,
    };
  });
}

async function step(page) {
  return page.evaluate(() => {
    window.__valueProbe.nextSentence();
    return true;
  });
}

async function runToChoose(page, max = 12000) {
  for (let i = 0; i < max; i++) {
    await step(page);
    const state = await snapshot(page);
    if (state.choices.length) return state;
    if (i % 1000 === 999) console.log(`  ... ${i + 1} 步 ${state.scene}:${state.sentence}`, state.vars);
    await page.waitForTimeout(3);
  }
  throw new Error('未到达下一个选项');
}

async function runUntil(page, predicate, max = 2000) {
  for (let i = 0; i < max; i++) {
    await step(page);
    const state = await snapshot(page);
    if (predicate(state)) return state;
    if (state.choices.length) throw new Error(`意外停在选项 ${state.choices.join(' / ')}`);
    await page.waitForTimeout(3);
  }
  throw new Error('未满足目标状态');
}

async function clickChoice(page, text) {
  const target = page.locator('#chooseContainer').getByText(text, { exact: true }).last();
  await target.waitFor({ state: 'visible', timeout: 10000 });
  await target.click();
  await page.waitForFunction(() => {
    const root = document.querySelector('#chooseContainer');
    return !root || !root.textContent.trim();
  }, null, { timeout: 10000 });
}

async function quickSave(page) {
  const url = await page.evaluate(() => performance.getEntriesByType('resource').map(e => e.name)
    .find(name => name.includes('/storage/fastSaveLoad.ts')));
  await page.evaluate(async moduleUrl => {
    const { fastSaveGame } = await import(moduleUrl);
    await fastSaveGame();
  }, url);
  await page.waitForTimeout(600);
}

async function reloadAndContinue(page) {
  const saved = await snapshot(page);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await enterDiscTitle(page, origin);
  await button(page, '继续游戏').click();
  await page.waitForFunction(async wanted => {
    const url = performance.getEntriesByType('resource').map(e => e.name)
      .find(name => name.includes('/Core/WebGAL.ts'));
    if (!url) return false;
    const { WebGAL } = await import(url);
    return WebGAL.sceneManager.sceneData.currentScene.sceneName === wanted.scene
      && WebGAL.sceneManager.sceneData.currentSentenceId === wanted.sentence;
  }, { scene: saved.scene, sentence: saved.sentence }, { timeout: 20000 });
  await page.evaluate(async () => {
    const find = fragment => performance.getEntriesByType('resource').map(e => e.name)
      .find(name => name.includes(fragment));
    const { nextSentence } = await import(find('/Core/controller/gamePlay/nextSentence.ts'));
    const { WebGAL } = await import(find('/Core/WebGAL.ts'));
    const { stageStateManager } = await import(find('/Core/Modules/stage/stageStateManager.ts'));
    window.__valueProbe = { nextSentence, WebGAL, stageStateManager };
  });
  await page.waitForTimeout(800);
  return saved;
}

async function route(browser, first) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await startGame(page);
    let state = await snapshot(page);
    assert.deepEqual(state.vars, { mac_6026: 20, mac_602a: 20, mac_602b: 20, mac_602c: 20 });

    state = await runToChoose(page, 4000);
    assert.deepEqual(state.choices, ['道歉', '少扯了！', '…………']);
    console.log(`到达第 2 话开篇选项 ${state.choices.join(' / ')}，点击「${first}」`);
    await clickChoice(page, first);

    state = await runUntil(page, s => s.scene.startsWith('mac_001_0x003') && (s.vars.mac_602a !== 20 || s.vars.mac_602b !== 20 || s.vars.mac_602c !== 20), 400);
    const afterFirst = state.vars;
    console.log('第一组选项后', afterFirst, state.scene);
    const expectedFirst = first === '道歉'
      ? { mac_6026: 21, mac_602a: 21, mac_602b: 20, mac_602c: 20 }
      : { mac_6026: 20, mac_602a: 20, mac_602b: 19, mac_602c: 21 };
    assert.deepEqual(afterFirst, expectedFirst, '第一组选项加减应与原盘一致');

    await quickSave(page);
    const saved = await reloadAndContinue(page);
    state = await snapshot(page);
    assert.equal(state.scene, saved.scene);
    assert.deepEqual(state.vars, afterFirst, '读档后数值应恢复');
    console.log('读档后句子和数值保持', state.scene, state.vars);

    state = await runToChoose(page, 5000);
    assert.deepEqual(state.choices, ['２年教室', '走廊', '美術室', '站前商店街']);
    console.log('第 3 话入口选择「２年教室」');
    await clickChoice(page, '２年教室');

    state = await runToChoose(page, 5000);
    console.log('第 3 话阈值点', state.scene, state.sentence, state.vars, state.choices);
    assert.equal(state.scene, 'mac_003_0x00000c.txt');
    assert.equal(state.vars.mac_602c, first === '道歉' ? 20 : 21);
    if (first === '道歉') {
      assert.deepEqual(state.choices, ['青梅竹马而已', '没必要说明', '…………'],
        '602C=20 时阈值成立，应显示三项');
    } else {
      assert.deepEqual(state.choices, ['没必要说明', '…………'],
        '602C=21 时阈值不成立，应隐藏「青梅竹马而已」');
    }
    console.log(`PASS 真实点击「${first}」→ ２年教室 → 602C=${state.vars.mac_602c}，阈值${first === '道歉' ? '成立' : '不成立'}，选项数 ${state.choices.length}`);
    assert.deepEqual(errors, []);
    return { first, afterFirst, threshold: state };
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({ executablePath, headless: true });
  try {
    const a = await route(browser, '少扯了！');
    const b = await route(browser, '道歉');
    console.log('PASS 阈值两侧均已实测：');
    console.log('  少扯了！ / ２年教室 ->', a.threshold.vars, a.threshold.choices);
    console.log('  道歉 / ２年教室 ->', b.threshold.vars, b.threshold.choices);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
