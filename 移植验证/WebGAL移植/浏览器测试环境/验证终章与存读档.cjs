// Verify late-game storage and the active build's seven terminal scene entries.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const {enterDiscTitle, discButton: button} = require('./进入打盘版标题.cjs');

const directory = path.resolve(__dirname, '../数据');
const read = name => JSON.parse(fs.readFileSync(path.join(directory, name), 'utf8'));
const checkpoint = read('分支检查点.json').checkpoints.at(-1);
const sourceReport = read('全盘剧情_对白补齐与结束核验.json');
const endings = sourceReport.chapters.flatMap(chapter => Object.values(chapter.scenes))
  .filter(info => info.stop?.name === 'end').map(info => info.scene);
assert.equal(endings.length, 7);
const origin = 'http://127.0.0.1:4203/';

async function title(page) {
  await enterDiscTitle(page, origin);
}

async function installProbe(page) {
  await page.evaluate(async () => {
    const urls = performance.getEntriesByType('resource').map(entry => entry.name);
    const live = async suffix => {
      const url = urls.find(name => name.includes(suffix));
      if (!url) throw new Error(`Runtime module not loaded: ${suffix}`);
      return import(url);
    };
    const [{WebGAL}, {stageStateManager}, {loadGameFromStageData}, {fastSaveGame, hasFastSaveRecord}] =
      await Promise.all(['/Core/WebGAL.ts', '/stage/stageStateManager.ts', '/storage/loadGame.ts',
                         '/storage/fastSaveLoad.ts'].map(live));
    window.__ending = {loadGameFromStageData, fastSaveGame, hasFastSaveRecord, snapshot: () => ({
      scene: WebGAL.sceneManager.sceneData.currentScene.sceneName,
      sentence: WebGAL.sceneManager.sceneData.currentSentenceId,
      vars: stageStateManager.getCalculationStageState().GameVar,
    })};
  });
}

async function reachTitle(page) {
  const start = button(page, '开始游戏');
  const scenes = new Set();
  for (let count = 0; count < 6500; count++) {
    const current = await page.evaluate(() => window.__ending.snapshot().scene);
    if (current) scenes.add(current);
    if (await start.isVisible()) return [...scenes];
    const available = page.locator('#chooseContainer div').filter({hasText: /\S/});
    const options = await available.evaluateAll(nodes => nodes
      .filter(node => node.childElementCount === 0 && node.getBoundingClientRect().height > 0)
      .map(node => node.textContent.trim()));
    if (options.length) await button(page, options[0]).click({timeout: 3000});
    else await page.mouse.click(640, 80);
    await page.waitForTimeout(8);
  }
  assert.fail('剧情未回到标题');
}

async function withPage(browser, action) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  try {
    const page = await context.newPage();
    const errors = [];
    const failedRequests = new Set();
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      if (response.status() >= 400) failedRequests.add(`${response.status()} ${response.url()}`);
    });
    const result = await action(page);
    assert.deepEqual(errors, []);
    return {...result, failedRequests: [...failedRequests]};
  } finally {
    await context.close();
  }
}

async function testCheckpoint(browser) {
  return withPage(browser, async page => {
    await title(page);
    await button(page, '开始游戏').click();
    await page.waitForTimeout(2000);
    await installProbe(page);
    await page.evaluate(save => window.__ending.loadGameFromStageData({...save, backlog: [], previewImage: ''}),
                        checkpoint.checkpoint);
    await button(page, checkpoint.choices[0]).waitFor({state: 'visible'});
    const before = await page.evaluate(() => window.__ending.snapshot());
    assert.equal(before.scene, checkpoint.scene);
    assert.deepEqual(before.vars, checkpoint.GameVar);
    await page.evaluate(() => window.__ending.fastSaveGame());
    assert(await page.evaluate(() => window.__ending.hasFastSaveRecord()));
    await title(page);
    await button(page, '继续游戏').click();
    await button(page, checkpoint.choices[0]).waitFor({state: 'visible'});
    await installProbe(page);
    const restored = await page.evaluate(() => window.__ending.snapshot());
    assert.deepEqual(restored, before);
    await button(page, checkpoint.choices[1]).click();
    console.log('PASS MAC_048 晚期快存，刷新继续，变量和句子位置一致');
    const visited = await reachTitle(page);
    await page.waitForFunction(() => window.__ending.hasFastSaveRecord().then(value => !value));
    const terminal = visited.find(scene => endings.includes(scene)) ?? null;
    console.log(`PASS 后期读档分支回到标题并清理快存，终章采样 ${terminal ?? visited.slice(-4).join(', ')}`);
    return {checkpoint: checkpoint.scene, choice: checkpoint.choices[1], restored: true,
            returnedToTitle: true, terminal, visited};
  });
}

async function testEndScene(browser, scene) {
  return withPage(browser, async page => {
    await page.route('**/game/scene/start.txt', route => route.fulfill({
      contentType: 'text/plain', body: `changeScene:${scene};`,
    }));
    await title(page);
    await installProbe(page);
    await button(page, '开始游戏').click();
    await page.waitForFunction(name => window.__ending.snapshot().scene === name, scene);
    const visited = await reachTitle(page);
    assert(visited.includes(scene));
    console.log(`PASS 终章定点 ${scene} → 标题`);
    return {scene, returnedToTitle: true};
  });
}

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--mute-audio'],
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  try {
    const late = testCheckpoint(browser).then(value => ({value}), error => ({error}));
    const terminalEntries = [];
    // Limit concurrent audio-decoding contexts while the checkpoint route runs.
    for (const scene of endings) terminalEntries.push(await testEndScene(browser, scene));
    const {value: result, error} = await late;
    if (error) throw error;
    fs.writeFileSync(path.join(directory, '终章与晚期存读档浏览器核验.json'),
                     `${JSON.stringify({origin, lateCheckpoint: result, terminalEntries}, null, 2)}\n`, {flag: 'wx'});
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
