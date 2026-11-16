const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const {enterDiscTitle, discButton} = require('./进入打盘版标题.cjs');

const root = path.resolve(__dirname, '..');
const origin = 'http://127.0.0.1:4204/';
const scenes = path.join(root, '新游戏打盘高清版/public/game/scene');
const variables = ['mac_6026', 'mac_602a', 'mac_602b', 'mac_602c'];
const lockedNode = (page, id) => page.locator(`[data-flowchart-node="${id}"]`);

async function prepare(page, entry) {
  await page.addInitScript(() => performance.setResourceTimingBufferSize(3000));
  if (entry) {
    await page.route('**/game/scene/start.txt', route => route.fulfill({
      contentType: 'text/plain',
      body: 'setVar:mac_6026=20 -next;\nsetVar:mac_602c=20 -next;\nchangeScene:' + entry + ';\n',
    }));
  }
  await enterDiscTitle(page, origin);
  await discButton(page, '开始游戏').click();
  await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(entry => entry.name);
    const live = suffix => {
      const url = resources.find(name => name.includes(suffix));
      if (!url) throw new Error(`找不到已加载的引擎模块 ${suffix}`);
      return import(url);
    };
    const [{WebGAL}, {stageStateManager}, {nextSentence, continueSentence}, {webgalStore}] = await Promise.all(
      ['/Core/WebGAL.ts', '/stage/stageStateManager.ts', '/gamePlay/nextSentence.ts', '/store/store.ts'].map(live),
    );
    window.__flow = {WebGAL, stageStateManager, nextSentence, continueSentence, webgalStore, live, timer: null};
  });
}

async function drive(page, reached, arg) {
  await page.evaluate(() => {
    const probe = window.__flow;
    probe.WebGAL.gameplay.isFast = true;
    probe.timer = setInterval(() => {
      if (!document.querySelector('#chooseContainer')?.textContent.trim() &&
          !document.querySelector('#playVideoElement')) probe.nextSentence();
    }, 15);
  });
  try {
    await page.waitForFunction(reached, arg, {timeout: 40000});
  } catch (error) {
    const info = await page.evaluate(() => {
      const {WebGAL, stageStateManager} = window.__flow;
      const current = WebGAL.sceneManager.sceneData;
      return {
        scene: current.currentScene.sceneName, sentence: current.currentSentenceId,
        text: stageStateManager.getCalculationStageState().showText,
        options: document.querySelector('#chooseContainer')?.textContent,
        unlocked: WebGAL.flowchartManager.getFlowcharts()[0]?.nodes
          .filter(node => node.type === 'ending' && WebGAL.flowchartManager.isUnlocked('main', node.id))
          .map(node => node.id),
      };
    });
    throw new Error(`推进超时 ${JSON.stringify(info)}`, {cause: error});
  } finally {
    await page.evaluate(() => {
      clearInterval(window.__flow.timer);
      window.__flow.WebGAL.gameplay.isFast = false;
    });
  }
}

async function chart(page, title) {
  await page.mouse.move(800, 510);
  await page.mouse.move(820, 550);
  await discButton(page, '流程图').click();
  await page.getByRole('button', {name: title, exact: true}).click();
}

async function verifyFlowchart(browser) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  try {
    const page = await context.newPage();
    await prepare(page, 'mac_002_0x00000c.txt');
    const corridor = page.locator('#chooseContainer').getByText('走廊', {exact: true});
    await drive(page, () => document.querySelector('#chooseContainer')?.textContent.includes('走廊'));
    await corridor.waitFor();
    await corridor.click();
    await page.waitForFunction(() => window.__flow.WebGAL.flowchartManager.isUnlocked('mac_002_choice_01', 'option_1'));
    const outcome = await page.evaluate(() => window.__flow.WebGAL.flowchartManager.loadSnapshot('mac_002_choice_01', 'option_1'));
    assert.equal(outcome.nowStageState.GameVar.mac_6007, 1);
    const endChapter = () => window.__flow.WebGAL.flowchartManager.isUnlocked('mac_002_choice_01', 'merge');
    await drive(page, endChapter);

    await chart(page, '第03话 · 选项 1');
    assert.equal(await lockedNode(page, 'option_0').getAttribute('role'), null);
    assert.equal(await lockedNode(page, 'merge').getAttribute('role'), 'button');
    await lockedNode(page, 'option_1').click();
    await page.waitForFunction(({scene, sentence, values}) => {
      const {WebGAL, stageStateManager} = window.__flow;
      const sceneData = WebGAL.sceneManager.sceneData;
      return sceneData.currentScene.sceneName === scene && sceneData.currentSentenceId === sentence
        && Object.entries(values).every(([key, value]) => stageStateManager.getCalculationStageState().GameVar[key] === value);
    }, {scene: outcome.sceneData.sceneName, sentence: outcome.sceneData.currentSentenceId,
      values: {mac_602c: outcome.nowStageState.GameVar.mac_602c, mac_6007: 1}});
    assert.equal(await page.evaluate(() => window.__flow.stageStateManager.getCalculationStageState().showText),
                 outcome.nowStageState.showText);

    await chart(page, '第03话 · 选项 1');
    await lockedNode(page, 'choice').click();
    await corridor.waitFor({state: 'visible'});
    assert.equal(await page.evaluate(() => window.__flow.stageStateManager.getCalculationStageState().GameVar.mac_602c), 20);

    await enterDiscTitle(page, origin);
    await page.waitForFunction(async () => {
      const url = performance.getEntriesByType('resource').map(entry => entry.name)
        .find(name => name.includes('/Core/WebGAL.ts'));
      if (!url) return false;
      const {WebGAL} = await import(url);
      return WebGAL.flowchartManager.isUnlocked('mac_002_choice_01', 'merge');
    });
    console.log('PASS 流程图真实点击恢复分支对白和变量，恢复选择菜单，汇合和锁定状态正确，刷新后保留');
  } finally {
    await context.close();
  }
}

async function verifyRetimedChoice(browser) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  try {
    const page = await context.newPage();
    await prepare(page, 'mac_020_0x00000c.txt');
    await page.waitForFunction(() => {
      const {sceneManager} = window.__flow.WebGAL;
      return !sceneManager.lockSceneWrite && sceneManager.sceneData.currentScene.sceneName === 'mac_020_0x00000c.txt';
    });
    await page.evaluate(async () => {
      const {WebGAL, live, stageStateManager} = window.__flow;
      const [{sceneParser}, {stopAllPerform}, {forward, commitForward}] = await Promise.all([
        '/parser/sceneParser.ts', '/gamePlay/stopAllPerform.ts', '/gamePlay/nextSentence.ts',
      ].map(live));
      const name = 'mac_020_0x00000c.txt';
      const url = './game/scene/' + name;
      const text = await (await fetch(url)).text();
      const voiceLine = text.split(/\r?\n/).findIndex(line => line.includes('VOICE_04163.wav'));
      if (voiceLine < 0) throw new Error('缺少第 21 话对白锚点');
      stopAllPerform();
      stageStateManager.setStage('GameVar', {...stageStateManager.getCalculationStageState().GameVar, mac_a025: 0});
      WebGAL.sceneManager.sceneData.currentScene = sceneParser(text, name, url);
      WebGAL.sceneManager.sceneData.currentSentenceId = voiceLine;
      WebGAL.flowchartManager.cancelPending();
      if (!forward()) throw new Error('第 21 话对白没有推进');
      commitForward();
    });
    const unlocks = () => page.evaluate(() => {
      const flow = window.__flow.WebGAL.flowchartManager;
      return ['choice', 'option_0', 'option_1'].map(node => flow.isUnlocked('mac_020_choice_01', node));
    });
    assert.deepEqual(await unlocks(), [false, false, false], '选项前对白不得提前解锁第 21 话的分支');
    const option = page.locator('#chooseContainer').getByText('说越苗打电话给我的事', {exact: true});
    await drive(page, () => document.querySelector('#chooseContainer')?.textContent.includes('说越苗打电话给我的事'));
    assert.deepEqual(await unlocks(), [true, false, false]);
    await option.click();
    await drive(page, () => window.__flow.WebGAL.flowchartManager.isUnlocked('mac_020_choice_01', 'option_0'));
    assert.deepEqual(await unlocks(), [true, true, false]);
    console.log('PASS 第 21 话动效重建后在真实选项处解锁，只开放实际选择的结果');
  } finally {
    await context.close();
  }
}

function checkpoint(strategy, scene, sourceLine) {
  const cli = ['-B', '验证/模拟数值路线.py', '--strategy', strategy, '--checkpoint', `${scene}:${sourceLine + 1}`];
  return JSON.parse(execFileSync('python', cli, {cwd: root, encoding: 'utf8'}));
}

async function verifyEnding(browser, scenario) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  try {
    const page = await context.newPage();
    const seed = checkpoint(scenario.strategy, scenario.scene, scenario.line);
    await prepare(page, null);
    await page.waitForFunction(() => window.__flow.stageStateManager.getCalculationStageState().showText);
    await page.evaluate(async state => {
      const {WebGAL, stageStateManager, continueSentence, live} = window.__flow;
      const [{sceneParser}, {sceneFetcher}] = await Promise.all(['/parser/sceneParser.ts',
        '/controller/scene/sceneFetcher.ts'].map(live));
      const url = './game/scene/' + state.scene;
      const text = await sceneFetcher(url);
      stageStateManager.setStage('GameVar', {...stageStateManager.getCalculationStageState().GameVar, ...state.GameVar});
      WebGAL.sceneManager.sceneData.currentScene = sceneParser(text, state.scene, url);
      WebGAL.sceneManager.sceneData.currentSentenceId = state.sourceLine;
      WebGAL.flowchartManager.cancelPending();
      WebGAL.flowchartManager.waitForCurrentSceneDialog();
      continueSentence();
    }, seed);
    if (scenario.movie) {
      const movie = page.locator('#playVideoElement[src*="MV_END01_phone60.mp4"]');
      await movie.waitFor();
      await page.waitForFunction(() => document.querySelector('#playVideoElement')?.currentTime > 0);
      assert(await page.evaluate(() => window.__flow.webgalStore.getState().userData.appreciationData.cg
        .some(item => item.name.includes('EV_END01'))));
      await movie.evaluate(video => {video.currentTime = video.duration - 0.4;});
      await movie.waitFor({state: 'hidden'});
    }
    if (scenario.choose) {
      const choice = page.locator('#chooseContainer').getByText(scenario.choose, {exact: true});
      await drive(page, name => document.querySelector('#chooseContainer')?.textContent.includes(name), scenario.choose);
      await choice.click();
    }
    const nodeId = `ending_${scenario.ending.replace(/\.txt$/, '')}`;
    await drive(page, id => window.__flow.WebGAL.flowchartManager.isUnlocked('main', id), nodeId);
    await discButton(page, '开始游戏').waitFor({state: 'visible'});
    const ending = await page.evaluate(id => window.__flow.WebGAL.flowchartManager.loadSnapshot('main', id), nodeId);
    assert.equal(ending.sceneData.sceneName, scenario.ending);
    assert.deepEqual(variables.map(key => ending.nowStageState.GameVar[key]), scenario.values);
    console.log(`PASS ${scenario.strategy} 路线 → ${scenario.ending}，结局数值 ${scenario.values.join('/')}${scenario.movie ? '，片尾及鉴赏解锁' : ''}，返回标题`);
  } finally {
    await context.close();
  }
}

async function verifyStatusAndOptions(browser) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  try {
    const page = await context.newPage();
    await prepare(page, null);
    await page.waitForFunction(() => window.__flow.stageStateManager.getCalculationStageState().showText);
    await page.mouse.move(760, 510);
    await page.mouse.move(780, 565);
    try {
      await page.getByRole('button', {name: '状态', exact: true}).click({timeout: 5000});
    } catch (error) {
      const detail = await page.evaluate(() => {
        const store = window.__flow.webgalStore.getState();
        return {
          enabled: store.userData.globalGameVar.Enable_disc_status,
          title: store.GUI.showTitle, textbox: store.GUI.showTextBox, controls: store.GUI.controlsVisibility,
          top: document.elementFromPoint(780, 565)?.outerHTML.slice(0, 100),
          body: document.body.innerText.slice(0, 180),
        };
      });
      throw new Error(JSON.stringify(detail), {cause: error});
    }
    const panel = page.getByRole('region', {name: '游戏状态'});
    await panel.waitFor();
    const sceneBefore = await page.evaluate(() => window.__flow.WebGAL.sceneManager.sceneData.currentSentenceId);
    assert.equal(await panel.locator('[data-stat]').count(), 7);
    assert.equal(await panel.locator('[data-stat="mac_6026"]').textContent(), '20');
    assert.equal(await panel.locator('meter').count(), 3);
    assert.deepEqual(await panel.locator('meter').evaluateAll(meters => meters.map(meter => [meter.value, meter.max])),
                     [[20, 40], [20, 40], [20, 40]]);
    assert.equal(await panel.locator('dt img').count(), 4);
    await panel.locator('dt img').evaluateAll(portraits => Promise.all(portraits.map(portrait => portrait.decode())));
    for (const viewport of [{width: 2400, height: 1080}, {width: 844, height: 390}]) {
      await page.setViewportSize(viewport);
      await page.waitForFunction(() => {
        const panel = document.querySelector('[aria-label="游戏状态"]');
        if (!panel) return false;
        const box = panel.getBoundingClientRect();
        const numbers = [...panel.querySelectorAll('[data-stat]')].map(node => node.getBoundingClientRect());
        return box.left >= 0 && box.top >= 0 && box.right <= innerWidth && box.bottom <= innerHeight
          && numbers.every(value => value.left > box.left && value.right < box.right && value.bottom < box.bottom);
      });
    }
    await page.setViewportSize({width: 1280, height: 720});
    if (process.env.WEBGAL_STATUS_PREVIEW_DIR) {
      await page.waitForFunction(() => getComputedStyle(document.querySelector('[class*="_Menu_main_"]')).opacity === '1');
      await page.screenshot({path: path.join(process.env.WEBGAL_STATUS_PREVIEW_DIR, 'is-webgal-游戏状态.png')});
    }
    await panel.getByRole('button', {name: '返回剧情'}).click();
    await panel.waitFor({state: 'hidden'});
    assert.equal(await page.evaluate(() => window.__flow.WebGAL.sceneManager.sceneData.currentSentenceId), sceneBefore);
    await page.mouse.move(790, 550);
    await page.mouse.move(820, 560);
    await discButton(page, '选项').click();
    await discButton(page, '显示').click();
    const preview = page.locator('[class*="_discPreview_"]');
    await preview.scrollIntoViewIfNeeded();
    for (const size of ['小', '中', '大']) {
      await page.locator('[class*="_Options_main_content_"] [class*="_NormalButton_"]')
        .filter({hasText: new RegExp(`^${size}$`)}).click({timeout: 5000});
      await page.waitForFunction(() => {
        const container = document.querySelector('[class*="_discPreview_"]');
        const textbox = container?.querySelector('[data-textbox-preview]');
        if (!textbox) return false;
        const box = textbox.getBoundingClientRect();
        const stage = container.getBoundingClientRect();
        const text = textbox.lastElementChild.getBoundingClientRect();
        return box.top >= stage.top && box.bottom <= stage.bottom
          && text.top >= box.top + 10 && text.bottom <= box.bottom;
      }, undefined, {timeout: 4500});
    }
    if (process.env.WEBGAL_STATUS_PREVIEW_DIR) {
      await preview.scrollIntoViewIfNeeded();
      await page.waitForTimeout(800);
      await preview.screenshot({path: path.join(process.env.WEBGAL_STATUS_PREVIEW_DIR, 'is-webgal-设置预览.png')});
    }
    console.log('PASS 状态页显示 4 项好感、3 项性格数值；设置的三档文字尺寸均完整显示');
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--mute-audio'],
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  try {
    const movieScene = 'mac_055_0x00000c.txt';
    const movieLine = fs.readFileSync(path.join(scenes, movieScene), 'utf8').split(/\r?\n/)
      .findIndex(line => line.startsWith('playVideo:MV_END01_phone60.mp4'));
    assert(movieLine >= 0);
    const phases = process.argv.slice(2);
    if (!phases.length || phases.includes('--chart')) {
      await verifyFlowchart(browser);
      await verifyRetimedChoice(browser);
    }
    if (!phases.length || phases.includes('--status')) await verifyStatusAndOptions(browser);
    if (!phases.length || phases.includes('--endings')) {
      await verifyEnding(browser, {strategy: 'first', scene: movieScene, line: movieLine, movie: true,
        ending: 'mac_056_0x002d30.txt', values: [35, 26, 20, 25]});
      await verifyEnding(browser, {strategy: 'last', scene: 'mac_056_0x00000c.txt', line: 0, choose: '伊织的事',
        ending: 'mac_056_0x0024f8.txt', values: [15, 17, 24, 21]});
    }
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
