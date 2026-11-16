// 逐选项分支覆盖（含嵌套选项）的探索与实跑驱动。
// 机制：
//  1) 以真实主线游玩时捕获的 42 个选项点原生存档为种子（数据/分支检查点.json）。
//  2) 每个选项点逐项真实点击；点击后若分支内部再次出现选项，当场用 generateCurrentStageData 存下该点的原生快照，
//     作为新的选项点入队（带 parent/depth），再按第 1 项推进，以便父项继续判定收束。
//  3) 已在集合中的同 (scene,sentenceId) 选项点不重复入队，记为该点被回访（循环/汇合），显式记录依据。
//  4) 收束 = 离开分支入口、推进 >= 16 次点击后落到默认主线后续场景；到达结束指令记 end。
// 用法：
//   node 探索嵌套分支.cjs --workers 3 [--retry-failed]
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const {enterDiscTitle} = require('./进入打盘版标题.cjs');

const arg = (name, fallback) => {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
};
const WORKERS = Number(arg('--workers', 3));
const REPORT_FILE = path.resolve(__dirname, arg('--report', '../数据/分支扫描_含嵌套_全量.json'));
const SEED_FILE = path.resolve(__dirname, '../数据/分支检查点.json');
const MAIN_FILE = path.resolve(__dirname, '../数据/主线实跑_全流程.json');

const mainReport = JSON.parse(fs.readFileSync(MAIN_FILE, 'utf8'));
const mainlineScenes = [];
for (const event of mainReport.probe.scenes) {
  if (event.scene && mainlineScenes[mainlineScenes.length - 1] !== event.scene) mainlineScenes.push(event.scene);
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
    if (await starts.nth(i).isVisible().catch(() => false)) { await starts.nth(i).click(); break; }
  }
  // 等开场场景链跑完再读档，否则开场场景会把初始变量写回覆盖真实状态。
  await page.waitForTimeout(2000);
}

async function importProbe(page) {
  return page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(entry => entry.name);
    const live = suffix => resources.find(name => name.includes(suffix));
    const stateUrl = live('/Core/Modules/stage/stageStateManager.ts');
    const webgalUrl = live('/Core/WebGAL.ts');
    const loadUrl = live('/Core/controller/storage/loadGame.ts');
    const saveUrl = live('/Core/controller/storage/saveGame.ts');
    if (!stateUrl || !webgalUrl || !loadUrl || !saveUrl) throw new Error('页面尚未加载所需运行时模块');
    const manager = (await import(stateUrl)).stageStateManager;
    const WebGAL = (await import(webgalUrl)).WebGAL;
    const loadGameFromStageData = (await import(loadUrl)).loadGameFromStageData;
    const saveModule = await import(saveUrl);
    const probe = { scenes: [], texts: [] };
    let scene = null;
    let textKey = null;
    const timer = setInterval(() => {
      const state = manager.getCalculationStageState();
      const currentScene = WebGAL.sceneManager.sceneData.currentScene?.sceneName || '';
      if (currentScene !== scene) {
        scene = currentScene;
        probe.scenes.push({ scene: currentScene, sentenceId: WebGAL.sceneManager.sceneData.currentSentenceId,
          GameVar: { ...state.GameVar } });
      }
      const key = `${state.showName}|${state.showText}`;
      if (state.showText && key !== textKey) {
        textKey = key;
        probe.texts.push({ scene: currentScene, text: state.showText, name: state.showName });
      }
    }, 20);
    window.__branchProbe = { manager, WebGAL, loadGameFromStageData, saveModule, probe, timer,
      snapshot: () => {
        const state = manager.getCalculationStageState();
        return { scene: WebGAL.sceneManager.sceneData.currentScene?.sceneName || '',
          sentenceId: WebGAL.sceneManager.sceneData.currentSentenceId,
          showText: state.showText || '', GameVar: { ...state.GameVar } };
      } };
    return { ok: true };
  });
}

async function visibleChoices(page) {
  return page.evaluate(() => {
    const root = document.getElementById('chooseContainer');
    if (!root) return [];
    return [...root.querySelectorAll('div')].filter(element => !element.childElementCount && element.textContent.trim())
      .map(element => { const r = element.getBoundingClientRect();
        return { text: element.textContent.trim(), x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  });
}

// 选项面板是滑入动画：等全部选项进入视口且位置连续两次不变后再读/点。
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
  await page.evaluate(async rawSave => {
    const { loadGameFromStageData } = window.__branchProbe;
    loadGameFromStageData({ ...rawSave, backlog: [], previewImage: '' });
  }, save);
  let snapshot = null;
  let options = [];
  for (let attempt = 0; attempt < 80; attempt++) {
    await page.waitForTimeout(100);
    snapshot = await page.evaluate(() => window.__branchProbe.snapshot());
    if (snapshot.scene && snapshot.scene !== 'start.txt') {
      options = await visibleChoices(page);
      if (options.length) { options = await settleChoices(page); break; }
    }
  }
  return { ...snapshot, options };
}

async function clickOption(page, text) {
  const target = page.locator('#chooseContainer').getByText(text, { exact: true }).last();
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

async function captureCheckpoint(page) {
  return page.evaluate(() => {
    const { saveModule, manager } = window.__branchProbe;
    const state = manager.getCalculationStageState();
    const raw = saveModule.generateCurrentStageData(0, false);
    return { checkpoint: { ...raw, backlog: [], previewImage: '' }, GameVar: { ...state.GameVar } };
  });
}

const pointKey = (scene, sentenceId) => `${scene}|${sentenceId}`;

async function runRow(browser, state, row) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const voices = [];
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('response', response => {
    const file = new URL(response.url()).pathname.split('/').pop() || '';
    if (/^VOICE_\d+\.wav$/i.test(file)) voices.push({ file, status: response.status() });
  });
  const point = state.points[row.pointId];
  const result = { rowId: `${point.id}#${row.index}`, pointId: point.id, parent: point.parent, depth: point.depth,
    scene: point.scene, sentenceId: point.sentenceId, index: row.index, choice: point.choices[row.index],
    expected_options: point.choices, source_checkpoint: point.source };
  try {
    await startBlank(page);
    await importProbe(page);
    const restored = await executeLoad(page, point.checkpoint);
    result.restored_scene = restored.scene;
    result.vars_before = restored.GameVar;
    if (restored.scene !== point.scene || !restored.options.length) {
      result.status = 'checkpoint_restore_failed';
      result.error = `期望 ${point.scene}，实际 ${restored.scene}，选项 ${JSON.stringify(restored.options.map(o => o.text))}`;
      return result;
    }
    result.options_visible = restored.options.map(option => option.text);
    if (JSON.stringify(result.options_visible) !== JSON.stringify(point.choices)) {
      result.status = 'option_list_changed';
      result.error = `捕获时 ${JSON.stringify(point.choices)}，读档后 ${JSON.stringify(result.options_visible)}`;
      return result;
    }
    const target = restored.options.find(option => option.text === result.choice);
    if (!target) {
      result.status = 'option_missing';
      result.error = '读档后未渲染出该选项';
      return result;
    }
    const voiceStart = voices.length;
    const clickOutcome = await clickOption(page, result.choice);
    result.clicked = clickOutcome.clicked;
    if (clickOutcome.error) result.click_error = clickOutcome.error;
    const after = await page.evaluate(() => window.__branchProbe.snapshot());
    result.target_scene = after.scene;
    result.vars_after_click = after.GameVar;
    if (!clickOutcome.clicked) { result.status = 'option_click_failed'; return result; }

    // 嵌套选项点自身不在主线列表里：以它所属主线根选项点为基准，判断分支是否回到主线后续。
    const baseScene = point.rootScene || point.scene;
    const cpIndex = mainlineScenes.indexOf(baseScene);
    const convergence = new Set(cpIndex >= 0 ? mainlineScenes.slice(cpIndex + 1) : mainlineScenes);
    const observed = new Set();
    let convergedAt = null;
    let end = false;
    let clicks = 0;
    for (; clicks < 2400; clicks++) {
      let nested = await visibleChoices(page);
      if (nested.length) {
        nested = await settleChoices(page, 1500);
        const snapshot = await page.evaluate(() => window.__branchProbe.snapshot());
        const text = nested.map(option => option.text);
        const key = pointKey(snapshot.scene, snapshot.sentenceId);
        const existingId = state.byKey[key];
        let nestedPointId = existingId || null;
        let created = false;
        if (!nestedPointId) {
          const captured = await captureCheckpoint(page);
          const id = `N${String(Object.keys(state.points).length + 1).padStart(3, '0')}`;
          state.points[id] = { id, scene: snapshot.scene, sentenceId: snapshot.sentenceId, choices: text,
            checkpoint: captured.checkpoint, GameVar: captured.GameVar, source: 'nested-runtime-save',
            parent: { pointId: point.id, option: result.choice, rowId: result.rowId },
            depth: point.depth + 1, rootScene: point.rootScene || point.scene,
            rootPointId: point.rootPointId || point.id, discovered_at: new Date().toISOString() };
          state.byKey[key] = id;
          nestedPointId = id;
          created = true;
          for (let index = 0; index < text.length; index++) state.queue.push({ pointId: id, index });
          persist();
        }
        (result.nested_points ||= []).push({ pointId: nestedPointId, scene: snapshot.scene,
          sentenceId: snapshot.sentenceId, options: text, created,
          // 父项要继续判定收束，这里按第 1 项推进；该嵌套点自身会在自己的行里被逐项覆盖。
          autoPicked: nested[0].text,
          note: created ? '新选项点，已入队逐项覆盖' : '该选项点已在集合中（循环或汇合），不重复入队' });
        const auto = await clickOption(page, nested[0].text);
        if (!auto.clicked) { result.status = 'nested_auto_pick_failed'; result.error = auto.error; break; }
        continue;
      }
      await page.mouse.click(640, 80);
      if (clicks % 8 !== 0) continue;
      const snapshot = await page.evaluate(() => window.__branchProbe.snapshot());
      if (snapshot.scene) observed.add(snapshot.scene);
      const sawEnd = await page.evaluate(() => window.__branchProbe.probe.texts.some(item => item.text.includes('0x2D88')));
      if (sawEnd) { end = true; break; }
      if (snapshot.scene && convergence.has(snapshot.scene) && snapshot.scene !== point.scene
          && snapshot.scene !== result.target_scene && clicks >= 16) { convergedAt = snapshot.scene; break; }
      if (!snapshot.scene && clicks > 20) break;
    }
    const probe = await page.evaluate(() => ({ scenes: window.__branchProbe.probe.scenes,
      texts: window.__branchProbe.probe.texts }));
    result.scene_path = [...observed];
    result.scene_events = probe.scenes.filter(item => /^(mac_\d+|branch_|choice_|opening_|start)/.test(item.scene));
    result.first_texts = probe.texts.slice(-60).slice(0, 12);
    result.voices = voices.slice(voiceStart).map(item => ({ id: (item.file.match(/\d+/) || [''])[0], status: item.status }));
    result.converged_at = convergedAt;
    result.reached_end = end;
    result.clicks_after_choice = clicks;
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

function backfillRoots(points) {
  // 早期创建的嵌套点可能没有 rootScene：沿 parent 链回到主线点补齐，避免收束基准退化为「任意主线场景」。
  const resolve = (point, seen = new Set()) => {
    if (point.rootScene) return point.rootScene;
    // 主线点自身就是收束基准；早期报告里种子点没有该字段。
    if (point.depth === 0) { point.rootScene = point.scene; point.rootPointId = point.id; return point.rootScene; }
    if (!point.parent || seen.has(point.id)) return null;
    const parent = points[point.parent.pointId];
    if (!parent) return null;
    seen.add(point.id);
    point.rootScene = resolve(parent, seen);
    point.rootPointId = point.rootPointId || parent.rootPointId || (parent.depth === 0 ? parent.id : null);
    return point.rootScene;
  };
  for (const point of Object.values(points)) resolve(point);
}

function loadState() {
  if (fs.existsSync(REPORT_FILE)) {
    const saved = JSON.parse(fs.readFileSync(REPORT_FILE, 'utf8'));
    backfillRoots(saved.points);
    saved.byKey = saved.byKey || {};
    for (const id of Object.keys(saved.points)) {
      const point = saved.points[id];
      saved.byKey[pointKey(point.scene, point.sentenceId)] = id;
    }
    saved.queue = saved.queue || [];
    return saved;
  }
  const seeds = JSON.parse(fs.readFileSync(SEED_FILE, 'utf8')).checkpoints;
  const state = { points: {}, byKey: {}, results: [], queue: [], seeds: SEED_FILE };
  seeds.forEach((seed, index) => {
    const id = `M${String(index + 1).padStart(2, '0')}`;
    state.points[id] = { id, scene: seed.scene, sentenceId: seed.sentenceId, choices: seed.choices,
      checkpoint: seed.checkpoint, GameVar: seed.GameVar, source: 'mainline-runtime-save',
      parent: null, depth: 0, rootScene: seed.scene, rootPointId: id };
    state.byKey[pointKey(seed.scene, seed.sentenceId)] = id;
    for (let option = 0; option < seed.choices.length; option++) state.queue.push({ pointId: id, index: option });
  });
  return state;
}

function persist() {
  fs.writeFileSync(REPORT_FILE, JSON.stringify({ updated_at: new Date().toISOString(),
    metric: 'rows=每个选项点×每个选项；points 含主线与嵌套选项点', points: state.points,
    results: state.results, queue: state.queue }));
}

let state = loadState();
if (process.argv.includes('--retry-depth')) {
  // 只重跑嵌套行：修正收束基准后需要重新采集它们的收束证据。
  const kept = state.results.filter(item => item.depth === 0);
  const pending = new Set();
  state.results = kept;
  for (const id of Object.keys(state.points)) {
    const point = state.points[id];
    if (point.depth === 0) continue;
    for (let index = 0; index < point.choices.length; index++) {
      const rowId = `${id}#${index}`;
      if (!pending.has(rowId)) { pending.add(rowId); state.queue.push({ pointId: id, index }); }
    }
  }
}
if (process.argv.includes('--retry-failed')) {
  const good = new Set(state.results.filter(item => item.status === 'converged' || item.status === 'end').map(item => item.rowId));
  state.results = state.results.filter(item => good.has(item.rowId));
  const pending = new Set();
  for (const id of Object.keys(state.points)) {
    const point = state.points[id];
    for (let index = 0; index < point.choices.length; index++) {
      const rowId = `${id}#${index}`;
      if (!good.has(rowId) && !pending.has(rowId)) { pending.add(rowId); state.queue.push({ pointId: id, index }); }
    }
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', args: ['--mute-audio'] });
  const done = new Set(state.results.map(item => item.rowId));
  const inFlight = new Set();
  const workers = Array.from({ length: WORKERS }, async () => {
    for (;;) {
      const row = state.queue.find(item => !done.has(`${item.pointId}#${item.index}`) && !inFlight.has(`${item.pointId}#${item.index}`));
      if (!row) {
        const pendingLeft = Object.keys(state.points).some(id => {
          const point = state.points[id];
          return point.choices.some((_, index) => !done.has(`${id}#${index}`) && !inFlight.has(`${id}#${index}`));
        });
        // 其他 worker 手中可能还有会带出新嵌套点的行；等它们结束再决定退出。
        if (!pendingLeft && inFlight.size === 0) return;
        await new Promise(resolve => setTimeout(resolve, 500));
        continue;
      }
      const rowId = `${row.pointId}#${row.index}`;
      inFlight.add(rowId);
      const result = await runRow(browser, state, row);
      inFlight.delete(rowId);
      done.add(rowId);
      state.results.push(result);
      if (state.results.length % 5 === 0) persist();
      console.log(`${state.results.length} 行：${result.pointId} 深度${result.depth} ${result.scene} #${row.index + 1} ${result.choice} → ${result.status}`);
    }
  });
  await Promise.all(workers);
  await browser.close();
  persist();
  const totals = {};
  for (const item of state.results) totals[item.status] = (totals[item.status] || 0) + 1;
  const nested = Object.values(state.points).filter(point => point.depth > 0);
  console.log('选项点', Object.keys(state.points).length, '其中嵌套', nested.length,
    '行', state.results.length, JSON.stringify(totals), 'report', REPORT_FILE);
}

main().catch(error => { console.error(error); persist(); process.exit(1); });
