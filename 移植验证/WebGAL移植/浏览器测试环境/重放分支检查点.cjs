// 从真实主线中捕获的 WebGAL 原生存档快照重放每个选项点。
// 此脚本不造变量：先在浏览器中启动应用，再以引擎 loadGameFromStageData 恢复真实游玩时保存的快照，
// 对每个选项进行真实鼠标点击，继续自动推进到默认主线汇合点或 end。
// 用法：node 重放分支检查点.cjs --workers 3 [--only mac_009_0x00000c.txt]

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const {enterDiscTitle} = require('./进入打盘版标题.cjs');
const arg = (name, fallback) => {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
};
const WORKERS = Number(arg('--workers', 3));
const ONLY = arg('--only', null);
const CHECKPOINTS_FILE = path.resolve(__dirname, '../数据/分支检查点.json');
const MAIN_FILE = path.resolve(__dirname, '../数据/主线实跑_全流程.json');
const REPORT_FILE = path.resolve(__dirname, arg('--report', '../数据/分支扫描_真实检查点.json'));
const ONLY_INDEX = arg('--option-index', null);
const checkpointsReport = JSON.parse(fs.readFileSync(CHECKPOINTS_FILE, 'utf8'));
const mainReport = JSON.parse(fs.readFileSync(MAIN_FILE, 'utf8'));
const checkpoints = new Map(checkpointsReport.checkpoints.map(item => [`${item.scene}|${item.sentenceId}`, item]));
const sceneCheckpoint = new Map(checkpointsReport.checkpoints.map(item => [item.scene, item]));
const mainlineScenes = [];
for (const event of mainReport.probe.scenes) {
  if (event.scene && mainlineScenes[mainlineScenes.length - 1] !== event.scene) mainlineScenes.push(event.scene);
}

const points = [];
for (const item of checkpointsReport.checkpoints) {
  if (ONLY && item.scene !== ONLY) continue;
  const choices = item.choices;
  if (!choices?.length) continue;
  for (let index = 0; index < choices.length; index++) {
    if (ONLY_INDEX !== null && index !== Number(ONLY_INDEX)) continue;
    points.push({ scene: item.scene, sentenceId: item.sentenceId, choices, index,
                  checkpoint: item.checkpoint, choiceText: choices[index] });
  }
}

const button = (page, name) => page.getByText(name, { exact: true }).first();
async function startBlank(page) {
  await enterDiscTitle(page);
  await page.waitForTimeout(250);
  const chinese = button(page, '简体中文');
  if (await chinese.isVisible().catch(() => false)) await chinese.click();
  await page.waitForTimeout(250);
  const starts = page.getByText('开始游戏', { exact: true });
  for (let i = 0; i < await starts.count(); i++) {
    if (await starts.nth(i).isVisible().catch(() => false)) {
      await starts.nth(i).click();
      break;
    }
  }
  // 等开场场景链跑完再读档：过早读档会被仍在执行的 start 场景写回初始变量（例如把 mac_6010 重置为 0）。
  await page.waitForTimeout(2000);
}

async function importProbe(page) {
  return page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(entry => entry.name);
    const live = suffix => resources.find(name => name.includes(suffix));
    const stateUrl = live('/Core/Modules/stage/stageStateManager.ts');
    const webgalUrl = live('/Core/WebGAL.ts');
    const loadUrl = live('/Core/controller/storage/loadGame.ts');
    if (!stateUrl || !webgalUrl || !loadUrl) throw new Error('页面尚未加载所需运行时模块');
    const manager = (await import(stateUrl)).stageStateManager;
    const WebGAL = (await import(webgalUrl)).WebGAL;
    const loadGameFromStageData = (await import(loadUrl)).loadGameFromStageData;
    const probe = { scenes: [], texts: [], managerUrl: stateUrl, snapshot: () => {
      const state = manager.getCalculationStageState();
      return { scene: WebGAL.sceneManager.sceneData.currentScene.sceneName,
        sentenceId: WebGAL.sceneManager.sceneData.currentSentenceId,
        showText: state.showText || '', showName: state.showName || '', GameVar: { ...state.GameVar } };
    } };
    let scene = null;
    let textKey = null;
    const timer = setInterval(() => {
      const state = manager.getCalculationStageState();
      const currentScene = WebGAL.sceneManager.sceneData.currentScene.sceneName;
      if (currentScene !== scene) {
        scene = currentScene;
        probe.scenes.push({ t: Date.now(), scene, sentenceId: WebGAL.sceneManager.sceneData.currentSentenceId,
          GameVar: { ...state.GameVar } });
      }
      const key = `${state.showName}|${state.showText}`;
      if (state.showText && key !== textKey) {
        textKey = key;
        probe.texts.push({ t: Date.now(), scene: currentScene, text: state.showText, name: state.showName });
      }
    }, 20);
    window.__branchProbe = { manager, WebGAL, loadGameFromStageData, probe, timer };
    return { managerUrl: stateUrl };
  });
}

async function visibleChoices(page) {
  return page.evaluate(() => {
    const root = document.getElementById('chooseContainer');
    if (!root) return [];
    return [...root.querySelectorAll('div')].filter(element => !element.childElementCount && element.textContent.trim())
      .map(element => { const r = element.getBoundingClientRect();
        return { text: element.textContent.trim(), x: r.x + r.width / 2, y: r.y + r.height / 2, top: r.top, left: r.left }; });
  });
}

// 选项面板是滑入动画：等所有选项进入视口且位置连续两次不变，再开始读取/点击。
async function settleChoices(page, timeoutMs = 3000) {
  const started = Date.now();
  let previous = '';
  while (Date.now() - started < timeoutMs) {
    const options = await visibleChoices(page);
    if (options.length) {
      const signature = options.map(option => `${option.text}@${Math.round(option.y)}`).join('|');
      const onScreen = options.every(option => option.y > 0 && option.y < 720);
      if (onScreen && signature === previous) return options;
      previous = signature;
    } else {
      previous = '';
    }
    await page.waitForTimeout(120);
  }
  return visibleChoices(page);
}

async function executeLoad(page, save) {
  // 先在页面里完成原生读档；随后由 Node 侧轮询，避免在单个 evaluate 内长时间等待时错过 React 的渲染帧。
  await page.evaluate(async rawSave => {
    const { loadGameFromStageData } = window.__branchProbe;
    // 移除缩略图与历史回想文本以降低复制成本；场景栈、句子指针与 GameVar 保持真实原样。
    loadGameFromStageData({ ...rawSave, backlog: [], previewImage: '' });
  }, save);
  let snapshot = null;
  let options = [];
  for (let attempt = 0; attempt < 80; attempt++) {
    await page.waitForTimeout(100);
    snapshot = await page.evaluate(() => window.__branchProbe.probe.snapshot());
    if (snapshot.scene && snapshot.scene !== 'start.txt') {
      options = await visibleChoices(page);
      if (options.length) { options = await settleChoices(page); break; }
    }
  }
  return { ...snapshot, options };
}

async function clickVisibleOption(page, option) {
  // 用真实鼠标点击选项元素；Playwright 会等待元素位置稳定，避免点进滑入中的空白。
  const target = page.locator('#chooseContainer').getByText(option.text, { exact: true }).last();
  try {
    await target.click({ timeout: 8000 });
  } catch (error) {
    return { clicked: false, error: String(error.message || error) };
  }
  for (let attempt = 0; attempt < 100; attempt++) {
    await page.waitForTimeout(50);
    if (!(await visibleChoices(page)).length) return { clicked: true };
  }
  return { clicked: false, error: '点击后选项面板未消失' };
}

const sceneChapter = scene => {
  const match = /^(mac_\d+)_/.exec(scene || '');
  return match ? `MAC_${match[1].slice(4)}` : null;
};

async function runPoint(browser, point) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const voices = [];
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('response', response => {
    const file = new URL(response.url()).pathname.split('/').pop() || '';
    if (/^VOICE_\d+\.wav$/i.test(file)) voices.push({ file, status: response.status(), t: Date.now() });
  });
  const result = { scene: point.scene, sentenceId: point.sentenceId, index: point.index,
    choice: point.choiceText, expected_options: point.choices, source_checkpoint: 'runtime-generated save' };
  try {
    await startBlank(page);
    await importProbe(page);
    const restored = await executeLoad(page, point.checkpoint);
    result.restored_scene = restored.scene;
    result.restored_sentence = restored.sentenceId;
    result.vars_before = restored.GameVar;
    let options = restored.options?.length ? restored.options : await visibleChoices(page);
    if (!options.length) {
      for (let attempt = 0; attempt < 20 && !options.length; attempt++) {
        await page.mouse.click(640, 80);
        await page.waitForTimeout(40);
        options = await visibleChoices(page);
      }
    }
    result.options_visible = options.map(option => option.text);
    if (restored.scene !== point.scene || !options.length) {
      result.status = 'checkpoint_restore_failed';
      result.error = `期望 ${point.scene} 选项 ${point.choiceText}；实际 ${restored.scene}, ${JSON.stringify(result.options_visible)}`;
      return result;
    }
    // 按选项文字定位；同一选项组内文字唯一，位置以浏览器实际布局为准。
    const actualOption = options.find(option => option.text === point.choiceText);
    if (!actualOption) {
      result.status = 'option_mismatch';
      result.error = `未渲染出选项「${point.choiceText}」：${JSON.stringify(result.options_visible)}`;
      return result;
    }
    result.option_position = options.findIndex(option => option.text === point.choiceText) + 1;
    const voiceStart = Date.now();
    const clickOutcome = await clickVisibleOption(page, actualOption);
    const clicked = clickOutcome.clicked;
    result.clicked = clicked;
    if (clickOutcome.error) result.click_error = clickOutcome.error;
    const after = await page.evaluate(() => window.__branchProbe.probe.snapshot());
    result.target_scene = after.scene;
    result.vars_after_click = after.GameVar;
    if (!clicked) {
      result.status = 'option_click_failed';
      return result;
    }

    const cpIndex = mainlineScenes.indexOf(point.scene);
    const convergence = new Set(cpIndex >= 0 ? mainlineScenes.slice(cpIndex + 1) : []);
    const observedScenes = new Set();
    let convergedAt = null;
    let end = false;
    let clickCount = 0;
    for (; clickCount < 1800; clickCount++) {
      // 先快速判空，只有真的出现选项时才等动画稳定，避免每次点击都付出等待成本。
      let nested = await visibleChoices(page);
      if (nested.length) nested = await settleChoices(page, 1200);
      if (nested.length) {
        result.nested_choices ||= [];
        result.nested_choices.push({ scene: (await page.evaluate(() => window.__branchProbe.probe.snapshot())).scene,
                                     options: nested.map(option => option.text), picked: nested[0].text });
        await clickVisibleOption(page, nested[0]);
        continue;
      }
      await page.mouse.click(640, 80);
      if (clickCount % 8 !== 0) continue;
      const state = await page.evaluate(() => window.__branchProbe.probe.snapshot());
      if (state.scene) observedScenes.add(state.scene);
      const sawEnd = await page.evaluate(() => window.__branchProbe.probe.texts.some(item => item.text.includes('0x2D88')));
      if (sawEnd) { end = true; break; }
      // 收束 = 回到选项点之后的主线场景，且已经离开刚点击产生的分支入口。
      // 默认路线本身就是主线，若不排除分支入口会在 0 次点击时误判为收束，分支段落实际没有走完。
      if (state.scene && convergence.has(state.scene) && state.scene !== point.scene
          && state.scene !== result.target_scene && clickCount >= 16) { convergedAt = state.scene; break; }
      if (!state.scene && clickCount > 20) break;
    }
    const probe = await page.evaluate(() => ({ scenes: window.__branchProbe.probe.scenes,
      texts: window.__branchProbe.probe.texts }));
    result.scene_path = [...observedScenes];
    result.scene_events = probe.scenes.filter(item => sceneChapter(item.scene) || item.scene === point.scene);
    result.first_texts = probe.texts.filter(item => item.t >= voiceStart && item.scene !== 'start.txt').slice(0, 18);
    result.voices = voices.filter(item => item.t >= voiceStart).map(item => ({ id: (item.file.match(/\d+/) || [''])[0], status: item.status }));
    result.converged_at = convergedAt;
    result.reached_end = end;
    result.clicks_after_choice = clickCount;
    result.status = convergedAt ? 'converged' : end ? 'end' : 'stalled';
    result.page_errors = pageErrors;
    return result;
  } catch (error) {
    result.status = 'error';
    result.error = String(error.stack || error);
    return result;
  } finally {
    await context.close();
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio'] });
  const RETRY_FAILED = process.argv.includes('--retry-failed');
  const prior = fs.existsSync(REPORT_FILE) ? JSON.parse(fs.readFileSync(REPORT_FILE, 'utf8')).results || [] : [];
  const RETRY_SHALLOW = process.argv.includes('--retry-shallow');
  let existing = RETRY_FAILED ? prior.filter(item => item.status === 'converged' || item.status === 'end') : prior;
  if (RETRY_SHALLOW) existing = existing.filter(item => item.status !== 'converged'
    || (item.clicks_after_choice >= 16 && item.converged_at !== item.target_scene));
  const done = new Set(existing.map(item => `${item.scene}|${item.sentenceId}|${item.index}`));
  const queue = points.filter(item => !done.has(`${item.scene}|${item.sentenceId}|${item.index}`));
  const results = existing.slice();
  console.log(`resume ${results.length}/${points.length}; pending ${queue.length}`);
  const workers = Array.from({ length: WORKERS }, async () => {
    while (queue.length) {
      const point = queue.shift();
      const result = await runPoint(browser, point);
      results.push(result);
      fs.writeFileSync(REPORT_FILE, JSON.stringify({ source: CHECKPOINTS_FILE, total: points.length,
        updated_at: new Date().toISOString(), results }, null, 2));
      if (results.length % 5 === 0) console.log(`${results.length}/${points.length}: ${point.scene} #${point.index + 1} ${result.status}`);
    }
  });
  await Promise.all(workers);
  await browser.close();
  const totals = results.reduce((acc, item) => { acc[item.status] = (acc[item.status] || 0) + 1; return acc; }, {});
  console.log('coverage', JSON.stringify(totals), 'report', REPORT_FILE);
}

main().catch(error => { console.error(error); process.exit(1); });
