// 从新游戏连续实跑到最远章节或 end，并逐章记录标题、首句、语音与状态变量。
// 用法（在 浏览器测试环境）：node 跑主线到终点.cjs [--max-seconds 5400] [--pick 0] [--report 路径]
//
// 状态变量读回走页面真实加载的模块 URL（Vite 会给模块加 ?t=<时间戳>），
// 直接 import('/src/...') 之类不带查询串的路径会拿到另一份空实例，读出来永远是 {}。

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const {enterDiscTitle, discButton: button} = require('./进入打盘版标题.cjs');

const arg = (name, fallback) => {
  const index = process.argv.indexOf(name);
  return index > -1 ? process.argv[index + 1] : fallback;
};
const HD = process.argv.includes('--hd');
const FAST = process.argv.includes('--fast');
const ORIGIN = `http://127.0.0.1:${HD ? 4204 : 4203}/`;
const MAX_SECONDS = Number(arg('--max-seconds', 5400));
const PICK = Number(arg('--pick', 0));   // 选项一律选第几个（0 起）
const REPORT = path.resolve(__dirname, arg('--report', '../数据/主线实跑_全流程.json'));

const titleTable = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../数据/章节标题静态表.json'), 'utf8'));
const TITLES = new Map(titleTable.records.map(record => [`MAC_${String(record.index).padStart(3, '0')}`, record.title]));


async function startGame(page) {
  await enterDiscTitle(page, ORIGIN);
  await button(page, '开始游戏').waitFor({ state: 'visible', timeout: 15000 });
  await button(page, '开始游戏').click();
}

// 在页面里装探针：场景流、句子流、选项流、变量快照、章节标题卡。
async function installProbe(page) {
  await page.evaluate(async () => {
    const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes(suffix));
    const managerUrl = live('/Core/Modules/stage/stageStateManager.ts');
    if (!managerUrl) throw new Error('页面没有加载 stageStateManager');
    const manager = (await import(managerUrl)).stageStateManager;
    const webgalUrl = live('/Core/WebGAL.ts');
    const WebGAL = webgalUrl ? (await import(webgalUrl)).WebGAL : null;

    const sceneName = () => {
      try { return WebGAL.sceneManager.sceneData.currentScene.sceneName || ''; } catch (error) { return ''; }
    };
    const snapshot = () => {
      const state = manager.getCalculationStageState();
      const data = { scene: sceneName(), showText: state.showText || '', showName: state.showName || '',
                     choose: (state.choose || []).map(item => item.text || item.key) };
      try {
        data.sentenceId = WebGAL.sceneManager.sceneData.currentSentenceId;
        const commands = WebGAL.sceneManager.sceneData.currentScene.commands || [];
        const introCommand = commands.find(command => command.command === 'intro');
        data.introCommand = introCommand ? introCommand.content : null;
      } catch (error) { data.sentenceId = -1; data.introCommand = null; }
      data.GameVar = { ...state.GameVar };
      return data;
    };

    const probe = { scenes: [], texts: [], choices: [], snapshot, managerUrl };
    let lastScene = null;
    let lastText = null;
    let lastChoice = '';
    let introWatch = 0;
    // 快速点击时 10ms 轮询会漏掉整段（MAC_056 只有几行）；用 DOM 变更再触发一次采样。
    const recordText = () => {
      const state = manager.getCalculationStageState();
      const key = `${state.showName}|${state.showText}`;
      if (state.showText && key !== lastText) {
        lastText = key;
        probe.texts.push({ t: Date.now(), scene: sceneName(), name: state.showName, text: state.showText });
      }
    };
    if (typeof MutationObserver !== 'undefined') {
      new MutationObserver(recordText).observe(document.body, { subtree: true, childList: true, characterData: true });
    }
    probe.timer = setInterval(() => {
      const data = snapshot();
      if (data.scene !== lastScene) {
        lastScene = data.scene;
        const keys = ['mac_6007', 'mac_6000', 'mac_entry', 'mac_a01c', 'mac_a018', 'mac_6028', 'mac_6029'];
        const picked = { vars_count: Object.keys(data.GameVar).length };
        for (const key of keys) if (key in data.GameVar) picked[key] = data.GameVar[key];
        probe.scenes.push({ t: Date.now(), scene: data.scene, sentenceId: data.sentenceId, GameVar: picked,
                            intro: null, introCommand: data.introCommand || null });
        introWatch = 60;   // 标题卡（intro）紧随场景加载，采样约 600 ms
      }
      if (introWatch > 0) {
        introWatch--;
        const event = probe.scenes[probe.scenes.length - 1];
        if (event && !event.intro) {
          // 逐字渲染会把每个字拆成一行，去掉空白后拼回整串再和章节标题比对。
          const body = document.body.innerText.replace(/\s+/g, '');
          if (body.length > 2) event.intro = body.slice(0, 200);
        }
      }
      const text = `${data.showName}|${data.showText}`;
      if (data.showText && text !== lastText) {
        lastText = text;
        probe.texts.push({ t: Date.now(), scene: data.scene, name: data.showName, text: data.showText });
      }
      const choiceKey = `${data.scene}#${data.choose.join('\u0001')}`;
      if (data.choose.length && choiceKey !== lastChoice) {
        lastChoice = choiceKey;
        probe.choices.push({ t: Date.now(), scene: data.scene, options: data.choose.slice() });
      }
      if (!data.choose.length) lastChoice = '';
    }, 10);
    window.__probe = probe;
  });
}

const readSnapshot = page => page.evaluate(() => window.__probe.snapshot());
const probeSawEnd = page => page.evaluate(() =>
  window.__probe.texts.some(item => item.text.includes('0x2D88')));

async function visibleChoices(page) {
  return page.evaluate(() => {
    const root = document.getElementById('chooseContainer');
    if (!root || !root.childElementCount) return [];
    // 选项容器用 emotion 生成的类名（css-xxxx），不认 Choose_item，只取叶子节点。
    const items = [...root.querySelectorAll('div')].filter(element =>
      !element.childElementCount && element.textContent.trim());
    return items.map(element => {
      const rect = element.getBoundingClientRect();
      return { text: element.innerText.trim(), x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
    }).filter(item => item.x > 0 && item.y > 0);
  });
}

async function clickChoice(page, choice) {
  for (let attempt = 0; attempt < 5; attempt++) {
    await page.mouse.click(choice.x, choice.y);
    await page.waitForTimeout(60);
    if (!(await visibleChoices(page)).length) return true;
  }
  return false;
}

// 只留关键操作数，避免报告膨胀。
const pickState = (gameVar = {}) => {
  const keys = ['mac_6007', 'mac_6000', 'mac_entry', 'mac_a01c', 'mac_a018', 'mac_6028', 'mac_6029'];
  const result = {};
  for (const key of keys) if (key in gameVar) result[key] = gameVar[key];
  result.vars_count = Object.keys(gameVar).length;
  return result;
};

const SCENE_DIR = path.resolve(__dirname, HD ? '../新游戏打盘高清版/public/game/scene' : '../新游戏打盘版/public/game/scene');

// 极短章节（MAC_056 只有几行）在 6ms 点击下可能整段落在两次采样之间；
// 此时用该章入口场景文件里的首句补齐，并在报告里标明来源。
function firstLineFromSceneFile(scene) {
  if (!scene) return null;
  const file = path.join(SCENE_DIR, scene);
  if (!fs.existsSync(file)) return null;
  const skip = ['intro:', 'setVar:', 'label:', 'jumpLabel:', 'choose:', 'changeScene:', 'wait:', 'bgm:', 'playBgm:'];
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (!line || skip.some(prefix => line.startsWith(prefix)) || line.includes('本版边界') || line.trim() === 'end;') continue;
    return line.replace(/ -VOICE_\d+\.wav;\s*$/, '').replace(/;\s*$/, '');
  }
  return null;
}

const chapterOf = scene => {
  const match = /^(mac_\d+)_/.exec(scene || '');
  return match ? `MAC_${match[1].slice(4)}` : null;
};

async function run() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio'],
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  const errors = [];
  const voices = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
  page.on('response', response => {
    const file = new URL(response.url()).pathname.split('/').pop() || '';
    if (/^VOICE_\d+\.wav$/i.test(file)) voices.push({ t: Date.now(), file, status: response.status() });
  });

  const report = { origin: ORIGIN, pick: PICK, fast: FAST, started_at: new Date().toISOString(), choices: [],
                   chapters: [], end: null, runtime: {} };
  try {
    await startGame(page);
    await page.waitForTimeout(1200);
    await installProbe(page);
    if (FAST) await page.evaluate(async () => {
      const live = suffix => performance.getEntriesByType('resource').map(entry => entry.name)
        .find(name => name.includes(suffix));
      const {WebGAL} = await import(live('/Core/WebGAL.ts'));
      const {nextSentence} = await import(live('/gamePlay/nextSentence.ts'));
      WebGAL.gameplay.isFast = true;
      window.__probe.fastTimer = setInterval(() => {
        if (!document.querySelector('#chooseContainer')?.textContent.trim()) nextSentence();
      }, 5);
    });

    const start = Date.now();
    let clicks = 0;
    let lastSignature = '';
    let same = 0;
    let ended = false;
    while (Date.now() - start < MAX_SECONDS * 1000) {
      const choices = await visibleChoices(page);
      if (choices.length) {
        const picked = choices[Math.min(PICK, choices.length - 1)];
        const snapshot = await readSnapshot(page);
        const pickedIndex = choices.indexOf(picked);
        const ok = await clickChoice(page, picked);
        report.choices.push({ t: Date.now() - start, at: Date.now(), scene: snapshot.scene,
                              options: choices.map(item => item.text), picked: picked.text,
                              picked_index: pickedIndex, clicked: ok });
        if (!ok) throw new Error(`选项 ${picked.text} 点击后仍然显示（场景 ${snapshot.scene}）`);
        continue;
      }

      // 点在上方中间：能推进正文，又不会误点到居中排布的选项。
      if (FAST) await page.waitForTimeout(15);
      else await page.mouse.click(640, 80);
      clicks++;
      if (clicks % 25 === 0) {
        const snapshot = await readSnapshot(page);
        const signature = `${snapshot.scene}#${snapshot.sentenceId}`;
        if (signature === lastSignature) same++; else { lastSignature = signature; same = 0; }

        const terminal = await page.evaluate(() => window.__probe.scenes
          .findLast(item => /^mac_056_0x00(?:2d30|2d48|24f8|25c4|2710|27fc|28a4)\.txt$/.test(item.scene)));
        if (terminal && await button(page, '开始游戏').isVisible()) {
          report.end = {kind: 'webgal_returned_to_title', script: 'MAC_056.bin', offset: '0x2D88',
                        raw_hex: '01010000', scene: terminal.scene};
          ended = true;
          break;
        }
        // Older evidence files used a visible boundary line before end.
        const empty = !snapshot.scene;
        const titleBack = empty && await button(page, 'PRESS THE SCREEN TO START').isVisible().catch(() => false);
        if (empty && same >= 1 || titleBack) {
          if (await probeSawEnd(page)) {
            const boundary = await page.evaluate(() =>
              window.__probe.texts.filter(item => item.text.includes('0x2D88')).pop());
            report.end = { kind: 'offline_end_instruction', script: 'MAC_056.bin', offset: '0x2D88',
                           raw_hex: '01010000', scene: boundary.scene, visible_boundary: boundary.text };
            ended = true;
            break;
          }
        }
        if (same >= 120) {
          report.runtime.stall = { scene: snapshot.scene, sentenceId: snapshot.sentenceId,
                                   showName: snapshot.showName, showText: snapshot.showText,
                                   GameVar: pickState(snapshot.GameVar), clicks };
          break;
        }
      }
    }
    report.runtime.seconds = Math.round((Date.now() - start) / 1000);
    report.runtime.clicks = clicks;
    report.runtime.ended_on_title = ended;
    report.voices = voices;
    report.errors = errors;
    report.probe = await page.evaluate(() => ({
      scenes: window.__probe.scenes, texts: window.__probe.texts, choices: window.__probe.choices,
      managerUrl: window.__probe.managerUrl,
    }));
    await page.evaluate(() => {
      clearInterval(window.__probe.timer);
      clearInterval(window.__probe.fastTimer);
    });
  } finally {
    await context.close();
    await browser.close();
  }
  return report;
}

// 把探针的原始流整理成逐章记录：标题、首句、进入场景、章节内语音、进入时的变量。
function summarize(report) {
  const probe = report.probe || { scenes: [], texts: [], choices: [] };
  const chapters = [];
  const seen = new Set();
  for (const sceneEvent of probe.scenes) {
    const chapter = chapterOf(sceneEvent.scene);
    if (!chapter || seen.has(chapter)) continue;
    seen.add(chapter);
    const firstText = probe.texts.find(item => item.t >= sceneEvent.t && chapterOf(item.scene) === chapter
      && !item.text.includes('本版边界'));
    const fallbackText = probe.texts.find(item => item.scene === sceneEvent.scene)
      || probe.texts.find(item => chapterOf(item.scene) === chapter && !item.text.includes('本版边界'));
    const title = TITLES.get(chapter) || null;
    const intro = sceneEvent.intro || '';
    // 引擎把每句话叠了三层渲染，逐字重复三次；压掉连续重复再比标题。
    // 引擎每句叠三层渲染，标题字符会连写三次；两种形式都比一次。
    const tripled = value => [...value].map(char => char.repeat(3)).join('');
    const introCommand = sceneEvent.introCommand || '';
    const titleInIntro = title ? introCommand.includes(title) || intro.includes(tripled(title)) || intro.includes(title) : false;
    const nextChapterEvent = probe.scenes.find(item => item.t > sceneEvent.t && chapterOf(item.scene)
      && chapterOf(item.scene) !== chapter);
    const until = nextChapterEvent ? nextChapterEvent.t : Infinity;
    const chapterVoices = [];
    for (const voice of report.voices || []) {
      if (voice.t < sceneEvent.t || voice.t >= until) continue;
      const number = (voice.file.match(/\d+/) || [''])[0];
      if (number && !chapterVoices.includes(number)) chapterVoices.push(number);
    }
    chapters.push({
      chapter,
      title,
      title_seen_in_runtime: titleInIntro,
      intro_snapshot: intro || null,
      entry_scene: sceneEvent.scene,
      entry_sentence: sceneEvent.sentenceId,
      first_text: firstText ? firstText.text : (fallbackText ? fallbackText.text : firstLineFromSceneFile(sceneEvent.scene)),
      first_text_source: firstText ? 'runtime' : fallbackText ? 'runtime_scan' : 'scene_file',
      first_text_name: firstText ? firstText.name : null,
      state_readback: pickState(sceneEvent.GameVar),
      preceding_choice: (() => {
        const prior = (probe.choices || []).filter(item => item.t < sceneEvent.t);
        const last = prior[prior.length - 1];
        if (!last || sceneEvent.t - last.t > 120000) return null;
        return { scene: last.scene, picked: last.text || null };
      })(),
      voices: chapterVoices,
      voices_count: chapterVoices.length,
      seconds_from_start: Math.round((sceneEvent.t - (probe.scenes[0] || { t: sceneEvent.t }).t) / 1000),
    });
  }
  report.chapters = chapters;
  // 实证：MAC_009 选第 N 项后，MAC_010 入口应读回 mac_6007 = N、mac_6000 = N。
  const mac009Choice = (report.choices || []).find(item => item.scene === 'mac_009_0x00000c.txt');
  const mac010 = chapters.find(item => item.chapter === 'MAC_010');
  if (mac009Choice && mac010) {
    report.state_checks = [{
      name: 'MAC_009 选项写回 mac_6007 / mac_6000',
      picked: mac009Choice.picked,
      picked_index: mac009Choice.picked_index,
      readback: { mac_6007: mac010.state_readback.mac_6007, mac_6000: mac010.state_readback.mac_6000 },
      pass: mac010.state_readback.mac_6007 === mac009Choice.picked_index &&
            mac010.state_readback.mac_6000 === mac009Choice.picked_index,
    }];
  }
  const last = chapters[chapters.length - 1];
  report.summary = {
    chapters_reached: chapters.length,
    last_chapter: last ? last.chapter : null,
    last_title: last ? last.title : null,
    last_first_text: last ? last.first_text : null,
    total_voices: new Set((report.voices || []).map(voice => voice.file)).size,
    stalled: Boolean(report.runtime.stall),
    end_instruction_reached: Boolean(report.end),
  };
}

function writeReport(report) {
  report.finished_at = new Date().toISOString();
  summarize(report);
  fs.writeFileSync(REPORT, `${JSON.stringify(report, null, 2)}\n`);
  console.log(`章节 ${report.summary.chapters_reached}，最远 ${report.summary.last_chapter}「${report.summary.last_title}」`);
  console.log(`末章首句：${report.summary.last_first_text}`);
  console.log(`语音 ${report.summary.total_voices} 个，点击 ${report.runtime.clicks}，耗时 ${report.runtime.seconds}s`);
  if (report.summary.end_instruction_reached) console.log('结束指令：', report.end.script, report.end.offset, report.end.raw_hex);
  if (report.summary.stalled) console.log('停点：', report.runtime.stall.scene, report.runtime.stall.showText);
  console.log('报告:', REPORT);
}

if (process.argv.includes('--summarize-only')) {
  // 不重跑浏览器，只按现有探针流重算逐章小结（用于修正统计口径）。
  const report = JSON.parse(fs.readFileSync(REPORT, 'utf8'));
  writeReport(report);
  process.exit(report.summary.stalled ? 2 : report.summary.end_instruction_reached ? 0 : 3);
}

run().then(report => {
  writeReport(report);
  process.exit(report.summary.stalled ? 2 : report.summary.end_instruction_reached ? 0 : 3);
}).catch(error => {
  console.error(error);
  process.exit(1);
});
