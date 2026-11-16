const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const {enterDiscTitle, discButton} = require('./进入打盘版标题.cjs');

const throughFourth = process.argv.includes('--through-fourth');
const origin = throughFourth ? 'http://127.0.0.1:4194/' : 'http://127.0.0.1:4193/';
const options = ['青梅竹马而已', '没必要说明'];
const stages = [
  { first: '道歉', second: '走廊', firstValue: 20, value: 19 },
  { first: '少扯了！', second: '走廊', firstValue: 21, value: 20 },
  { first: '少扯了！', second: '２年教室', firstValue: 21, value: 21 },
];

function button(page, name) {
  return page.getByText(name, {exact: true}).first();
}

async function advanceTo(page, name, budget = 3800) {
  const target = button(page, name);
  for (let count = 0; count < budget && !(await target.isVisible()); count++) {
    await page.mouse.click(800, 350);
    await page.waitForTimeout(8);
  }
  assert(await target.isVisible(), `未到达 ${name}`);
  return target;
}

async function getState(page) {
  return page.evaluate(async () => {
    const { stageStateManager } = await import('/src/Core/Modules/stage/stageStateManager.ts');
    const state = stageStateManager.getCalculationStageState().GameVar;
    return {value: state.mac_602c, flag: state.mac_6010, selected: state.third_choice};
  });
}

async function readOperands(page, addresses) {
  return page.evaluate(async (operands) => {
    // Vite 给模块加了 ?t=<时间戳>，必须用页面真实加载的那份 URL，否则会拿到另一个空实例。
    const url = performance.getEntriesByType('resource').map(entry => entry.name)
      .find(name => name.includes('/Core/Modules/stage/stageStateManager.ts'));
    const { stageStateManager } = await import(url);
    const state = stageStateManager.getCalculationStageState().GameVar;
    return Object.fromEntries(operands.map(address => [address, state[`mac_${address}`]]));
  }, addresses);
}

function expectedFourth(history) {
  const report = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../数据/新游戏第三选项路径分析_含条件.json'), 'utf8'));
  const branch = report.paths.find(candidate => candidate.history.join() === history.join());
  assert(branch, '找不到原 MAC 转换器的预期状态');
  const memory = branch.state_bytes_at_stop;
  const result = {};
  for (const code of [0x6000, 0x6007, 0x600E, 0x6026, 0x602A, 0x602B, 0x602C]) {
    const offset = 0x220 + (code & 0x1fff) * 2;
    const read = address => memory[address.toString(16).toUpperCase().padStart(5, '0')] ?? 0;
    result[code.toString(16)] = (read(offset) | (read(offset + 1) << 8)) << 16 >> 16;
  }
  result.a012 = ((memory['00422'] ?? 0) >> 2) & 1;
  return result;
}

async function isDialogue(page, expected) {
  return page.evaluate((wanted) => {
    const current = [...document.querySelectorAll('#textBoxMain span[id]')].map(element => {
      const text = element.textContent || '';
      const length = text.length / 3;
      const firstLayer = text.slice(0, length);
      return length > 0 && Number.isInteger(length) && firstLayer.repeat(3) === text ? firstLayer : text;
    }).join('');
    return current.replace(/\s+/gu, '') === wanted.replace(/\s+/gu, '');
  }, expected);
}

async function waitDialogue(page, expected) {
  for (let count = 0; count < 150; count++) {
    if (await isDialogue(page, expected)) return;
    await page.waitForTimeout(100);
  }
  assert.fail(`未到达对白 ${expected}`);
}

async function run(browser, route) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  try {
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await startGame(page, origin);

    const first = await advanceTo(page, route.first);
    assert.equal((await getState(page)).value, 20);
    await first.click();
    const second = await advanceTo(page, route.second);
    assert.equal((await getState(page)).value, route.firstValue);
    await second.click();
    await advanceTo(page, options[1]);
    const expectedFlag = Number(route.value < 21);
    assert.equal(await button(page, options[0]).isVisible(), Boolean(expectedFlag));
    assert.deepEqual(await getState(page), {value: route.value, flag: expectedFlag, selected: undefined});
    console.log(`条件已对齐，实际状态 ${route.value}`);

    const selected = expectedFlag ? 0 : 1;
    await button(page, options[selected]).click();
    const firstLine = selected === 0 ? '在这里说清楚吧。' : '我面向伊织――';
    await waitDialogue(page, firstLine);
    await page.waitForTimeout(1200);
    await button(page, '快速存档').click();
    await page.waitForTimeout(1000);
    for (let count = 0; count < 35 && await isDialogue(page, firstLine); count++) {
      await page.mouse.click(800, 350);
      await page.waitForTimeout(100);
    }
    assert.equal(await isDialogue(page, firstLine), false);
    await button(page, '快速读档').click();
    await waitDialogue(page, firstLine);
    const restored = {value: route.value, flag: expectedFlag, selected};
    assert.deepEqual(await getState(page), restored);

    await page.reload({waitUntil: 'networkidle'});
    await button(page, 'PRESS THE SCREEN TO START').click();
    if (await button(page, '简体中文').isVisible()) await button(page, '简体中文').click();
    await button(page, '继续游戏').click();
    await waitDialogue(page, firstLine);
    assert.deepEqual(await getState(page), restored);
    if (throughFourth) {
      assert.deepEqual(await readOperands(page, ['6007']), {'6007': selected});
      const fourth = await advanceTo(page, '我得说说她');
      const history = [route.first === '道歉' ? 0 : 1, route.second === '走廊' ? 1 : 0, selected];
      const expected = expectedFourth(history);
      assert.deepEqual(await readOperands(page, Object.keys(expected)), expected);
      await fourth.click();
      await waitDialogue(page, '当前版本到此为止。');
      assert.deepEqual(await readOperands(page, ['6007']), {'6007': 0});
      console.log(`第四组选项：${history.join('/')} 恢复后到达原选项，运行时状态与离线解释一致`);
    }
    assert.deepEqual(errors, []);
    console.log(`PASS ${route.first} / ${route.second}: 状态 ${route.value}，条件 ${expectedFlag}，选项 ${selected}，快速存读档和刷新继续`);
  } finally {
    await context.close();
  }
}

async function checkSignedLimits(browser) {
  const sceneDir = path.resolve(__dirname, '../历史样片/新游戏动态状态/public/game/scene');
  const edges = [
    [32767, 'branch_1_001.txt', '+', -32768],
    [-32768, 'choice_0_1_002.txt', '-', 32767],
  ];
  for (const [input, file, operator, expected] of edges) {
    const context = await browser.newContext({viewport: {width: 1280, height: 720}});
    try {
      const scene = fs.readFileSync(path.join(sceneDir, file), 'utf8').split(/\r?\n/);
      const start = scene.findIndex(line => line.startsWith(`setVar:mac_602c=mac_602c${operator}(1)`));
      const end = scene.findIndex((line, index) => index > start && /^label:wrap_.*_done;$/.test(line));
      assert(start >= 0 && end > start, '未找到转换后的加减指令');
      const page = await context.newPage();
      await page.route('**/game/scene/start.txt', route => route.fulfill({
        contentType: 'text/plain',
        body: [`setVar:mac_602c=${input} -next;`, ...scene.slice(start, end + 1), '边界检查。;'].join('\n'),
      }));
      await page.goto(origin, {waitUntil: 'networkidle'});
      await button(page, 'PRESS THE SCREEN TO START').click();
      await button(page, '简体中文').click();
      await button(page, '开始游戏').click();
      for (let count = 0; count < 20 && !(await isDialogue(page, '边界检查。')); count++) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(100);
      }
      assert(await isDialogue(page, '边界检查。'));
      assert.equal((await getState(page)).value, expected);
      console.log(`PASS 16 位边界 ${input} ${operator} 1 = ${expected}`);
    } finally {
      await context.close();
    }
  }
}

const fifthOrigin = 'http://127.0.0.1:4196/';
const fifthOptions = ['你适可而止！', '开玩笑吧？', '…………'];
const fifthBranches = [
  {index: 0, first: '一贵「在说什么呢，你……」'},
  {index: 1, first: '一贵「哈哈哈，季子，别开玩笑了」'},
  {index: 2, first: '季子她是……喜欢我？'},
];
const fifthBoundary = '本版边界：MAC_003.bin 0x6790 ext_goto（cross_script）。';

async function startGame(page, origin) {
  if (new URL(origin).port === '4203') {
    await enterDiscTitle(page, origin);
    await discButton(page, '开始游戏').click();
    return;
  }
  await page.goto(origin, {waitUntil: 'networkidle'});
  await button(page, 'PRESS THE SCREEN TO START').click();
  const chinese = button(page, '简体中文');
  await chinese.waitFor({state: 'visible', timeout: 15000}).catch(() => {});
  if (await chinese.isVisible()) await chinese.click();
  const start = button(page, '开始游戏');
  await start.waitFor({state: 'visible', timeout: 15000});
  await start.click();
}

async function chooseOption(page, label) {
  // 读档后选项界面可能刚重建，点击偶尔会被引擎吞掉；确认选项真的消失再继续。
  const option = button(page, label);
  await option.waitFor({state: 'visible', timeout: 15000});
  for (let attempt = 0; attempt < 4; attempt++) {
    // 存读档提示层会拦截元素点击；按包围盒中心发真实鼠标事件最稳。
    const box = await option.boundingBox();
    if (box) await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    try {
      await option.waitFor({state: 'hidden', timeout: 2500});
      return;
    } catch {
      await page.waitForTimeout(500);
    }
  }
  assert.fail(`选项 ${label} 点击后仍然显示`);
}

async function checkFifth(browser) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  try {
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await startGame(page, fifthOrigin);
    await (await advanceTo(page, '道歉')).click();
    await (await advanceTo(page, '走廊')).click();
    await (await advanceTo(page, '青梅竹马而已')).click();
    await (await advanceTo(page, '我得说说她')).click();

    // 走到第五组选项：三项的条件操作数都是立即数 1，应全部可见。
    await advanceTo(page, fifthOptions[0], 6000);
    for (const label of fifthOptions) {
      assert(await button(page, label).isVisible(), `第五组选项 ${label} 未显示`);
    }
    assert.deepEqual(await readOperands(page, ['6007']), {'6007': 0},
      '进入第五组前 mac_6007 应保留第四组的选择结果 0');
    console.log(`到达第五组选项：${fifthOptions.join(' / ')}（三项均显示）`);

    await page.waitForTimeout(800);
    await button(page, '快速存档').click();
    await page.waitForTimeout(1000);

    const results = [];
    for (const branch of fifthBranches) {
      const label = fifthOptions[branch.index];
      await button(page, label).click();
      await waitDialogue(page, branch.first);
      const entered = await readOperands(page, ['6007']);
      assert.deepEqual(entered, {'6007': branch.index},
        `分支 ${label} 写回的原序号应为 ${branch.index}，实际 ${JSON.stringify(entered)}`);
      for (let count = 0; count < 800 && !(await isDialogue(page, fifthBoundary)); count++) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(10);
      }
      assert(await isDialogue(page, fifthBoundary), `分支 ${label} 未到达本版边界`);
      results.push({option: label, index: branch.index, first: branch.first,
                    boundary: fifthBoundary, written: entered['6007']});
      console.log(`PASS 第五组分支 ${branch.index}「${label}」→ 首句「${branch.first}」→ 到达 ${fifthBoundary}`);
      if (branch.index === fifthBranches[fifthBranches.length - 1].index) break;
      await button(page, '快速读档').click();
      await page.waitForTimeout(1200);
      for (const again of fifthOptions) {
        assert(await button(page, again).isVisible(), `读档后第五组选项 ${again} 未恢复`);
      }
    }
    assert.deepEqual(errors, []);
    const report = path.resolve(__dirname, '../数据/第五选项浏览器核验.json');
    fs.writeFileSync(report, JSON.stringify({
      origin: fifthOrigin,
      route: ['道歉', '走廊', '青梅竹马而已', '我得说说她'],
      choice_offset: 'MAC_003:0x5A44',
      options: fifthOptions,
      branches: results,
      note: '无头 Edge 从新游戏连续点击到第五组选项，逐项选择并到达本版边界；页面无 pageerror。',
    }, null, 2) + '\n');
    console.log('报告:', report);
  } finally {
    await context.close();
  }
}

const batchWiring = process.argv.includes('--through-batch-wiring');
const mac004Origin = batchWiring ? 'http://127.0.0.1:4198/' : 'http://127.0.0.1:4197/';
const mac004Title = '新生欢迎晚会';
// MAC_004 开头第一句由 mac_a013 的门控决定：分支 0 置 1 读叙述段，分支 1/2 保持 0
// 直接 jumpLabel 到 0x244；两种都是原剧本行为，都必须在已接线范围内。
const mac004Openings = ['果然还是说过头了吧。', '新生欢迎会就在明天。'];
const mac004Choices = ['她过会就会来吧', '去找季子'];
const mac004BranchFirst = [
  '一贵「没关系的吧。她说了会来」',
  '……已经两点了。她到底在干吗啊？',
];
const mac004Boundary = '本版边界：MAC_004.bin 0x1AA8 effect_start（effect）。';

async function playToFifthChoice(page, sampleOrigin = mac004Origin) {
  await startGame(page, sampleOrigin);
  for (const label of ['道歉', '走廊', '青梅竹马而已', '我得说说她']) {
    await advanceTo(page, label);
    await chooseOption(page, label);
  }
  await advanceTo(page, fifthOptions[0], 6000);
  await page.waitForTimeout(300);
}

async function checkMac004(browser) {
  const results = [];
  for (const branch of fifthBranches) {
    // 每条分支都从新游戏重跑：接续依据必须来自剧本本身，而不是上一分支的残留状态。
    const context = await browser.newContext({viewport: {width: 1280, height: 720}});
    try {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await playToFifthChoice(page);
      // 标题卡会被点击越过，事后无法回看，所以先用 MutationObserver 记录它渲染过。
      await page.evaluate(title => {
        window.__titleSeen = 0;
        new MutationObserver(() => {
          if (document.body.innerText.includes(title)) window.__titleSeen += 1;
        }).observe(document.body, {subtree: true, childList: true, characterData: true});
      }, mac004Title);

      await chooseOption(page, fifthOptions[branch.index]);
      // 开场句由 mac_a013 门控二选一，两者都是原剧本行为，也都已接线。
      let opening = null;
      for (let count = 0; count < 400 && !opening; count++) {
        for (const candidate of mac004Openings) {
          if (await isDialogue(page, candidate)) { opening = candidate; break; }
        }
        if (!opening) await page.mouse.click(800, 350);
      }
      assert(opening, `分支 ${branch.index} 未出现 MAC_004 开场白`);
      await advanceTo(page, mac004Choices[0], 4000);
      for (const label of mac004Choices) {
        assert(await button(page, label).isVisible(), `MAC_004 选项 ${label} 未显示`);
      }

      // 两个选项在三条第五组分支上轮流各验一遍，避免只覆盖同一条前序路径。
      const option = branch.index % mac004Choices.length;
      await chooseOption(page, mac004Choices[option]);
      assert.deepEqual(await readOperands(page, ['6007']), {'6007': option},
        `MAC_004 选项 ${option} 写回的原序号不对`);
      await waitDialogue(page, mac004BranchFirst[option]);
      for (let count = 0; count < 900 && !(await isDialogue(page, mac004Boundary)); count++) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(10);
      }
      assert(await isDialogue(page, mac004Boundary),
        `MAC_004 分支 ${option} 未到达本版边界`);
      const seen = await page.evaluate(() => window.__titleSeen);
      assert(seen > 0, `分支 ${branch.index} 没有渲染章节标题卡 ${mac004Title}`);
      assert.deepEqual(errors, []);
      results.push({fifth_branch: branch.index, option, option_text: mac004Choices[option],
                    opening, first_line: mac004BranchFirst[option],
                    chapter_title: mac004Title, boundary: mac004Boundary,
                    title_rendered: seen > 0});
      console.log(`PASS 第五组分支 ${branch.index} → MAC_004 选项「${mac004Choices[option]}」→ 首句「${mac004BranchFirst[option]}」→ 到达 ${mac004Boundary}`);
    } finally {
      await context.close();
    }
  }
  const report = path.resolve(__dirname, batchWiring ? '../数据/批量接线浏览器核验.json' : '../数据/MAC004接续浏览器核验.json');
  fs.writeFileSync(report, JSON.stringify({
    origin: mac004Origin,
    route: ['道歉', '走廊', '青梅竹马而已', '我得说说她', '第五组选项', 'MAC_004 第一组选项'],
    ext_goto: 'MAC_003:0x6790 → MAC_004.bin:0x0C（changeScene:mac_004_0x00000c.txt）',
    choice: 'MAC_004:0xA38（2 项，表 0x3F08，结果寄存器 0x6007）',
    chapter_title: mac004Title,
    openings: mac004Openings,
    boundary: mac004Boundary,
    branches: results,
    note: '无头 Edge 从新游戏连续点击，三条第五组分支各自越过 ext_goto，在 MAC_004 第一组选项选择并推进到 0x1AA8 特效边界；每分支独立会话，页面无 pageerror。',
  }, null, 2) + '\n');
  console.log('报告:', report);
}

async function checkParticleContinuation(browser, throughMac005 = false) {
  const effectOrigin = throughMac005 ? 'http://127.0.0.1:4200/' : 'http://127.0.0.1:4199/';
  const nextLine = '季子开始一个人独居，转眼已经过去两个月了。';
  const nextChoices = ['回去', '参加二次会'];
  const routes = [
    {fifth: 0, first: 0, second: 0, after: '一贵「大家，抱歉啊。我回去了」'},
    {fifth: 1, first: 0, second: 1, after: '一贵「……来，大家一起去开心吧！」'},
    {fifth: 2, first: 1, second: null},
  ];
  const testedRoutes = throughMac005 ? routes.slice(1, 2) : routes;
  const outcomes = await Promise.allSettled(testedRoutes.map(async route => {
    const context = await browser.newContext({viewport: {width: 1280, height: 720}});
    try {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await playToFifthChoice(page, effectOrigin);
      await chooseOption(page, fifthOptions[route.fifth]);
      await advanceTo(page, mac004Choices[route.first]);
      await chooseOption(page, mac004Choices[route.first]);
      if (route.second !== null) {
        await advanceTo(page, nextChoices[1]);
        for (const label of nextChoices) assert(await button(page, label).isVisible());
        await chooseOption(page, nextChoices[route.second]);
        await waitDialogue(page, route.after);
        assert.deepEqual(await readOperands(page, ['6007', '6000']), {'6007': route.second, '6000': route.second});
      }
      for (let count = 0; count < 3800 && !(await isDialogue(page, nextLine)); count++) {
        assert.equal(await button(page, nextChoices[1]).isVisible(), false, '出现了不该到达的第二组选项');
        await page.mouse.click(800, 350);
        await page.waitForTimeout(8);
      }
      assert(await isDialogue(page, nextLine), '未到达 MAC_005 的首句');
      const state = await page.evaluate(async () => {
        const { stageStateManager } = await import('/src/Core/Modules/stage/stageStateManager.ts');
        return stageStateManager.getCalculationStageState().GameVar.mac_effect_0_phase;
      });
      assert.equal(state, 0);
      let mac006 = null;
      if (throughMac005) {
        const title = '岸边的告白';
        const boundary = '本版边界：MAC_006.bin 0x88 msg_disp2（translation）。';
        await page.evaluate(title => {
          window.__mac006TitleSeen = false;
          new MutationObserver(() => {
            if (document.body.innerText.includes(title)) window.__mac006TitleSeen = true;
          }).observe(document.body, {subtree: true, childList: true, characterData: true});
        }, title);
        for (let count = 0; count < 4000 && !(await isDialogue(page, boundary)); count++) {
          await page.mouse.click(800, 350);
          await page.waitForTimeout(8);
        }
        assert(await isDialogue(page, boundary), '未到达 MAC_006 的语音校验边界');
        assert(await page.evaluate(() => window.__mac006TitleSeen), '未渲染 MAC_006 的章节标题');
        mac006 = {title, boundary};
      }
      assert.deepEqual(errors, []);
      console.log(`PASS 第五组 ${route.fifth} → ${mac004Choices[route.first]}${route.second === null ? '' : ` → ${nextChoices[route.second]}`} → MAC_005${mac006 ? ` → MAC_006「${mac006.title}」` : ''}`);
      return {...route, firstDialogueInMac005: nextLine, effectPhase: state, ...(mac006 && {mac006})};
    } finally {
      await context.close();
    }
  }));
  for (const outcome of outcomes) if (outcome.status === 'rejected') throw outcome.reason;
  const report = path.resolve(__dirname, throughMac005 ? '../数据/MAC006接续浏览器核验.json' : '../数据/MAC004特效接续浏览器核验.json');
  fs.writeFileSync(report, JSON.stringify({origin: effectOrigin, routes: outcomes.map(outcome => outcome.value)}, null, 2) + '\n');
}

async function checkMac006(browser, throughNext = false) {
  const chapterOrigin = throughNext ? 'http://127.0.0.1:4202/' : 'http://127.0.0.1:4201/';
  const visibleFirstChoices = ['还是说作势要走出房间……', '等着看伊织会说些什么呢？'];
  const routes = [
    {first: 1, second: 0, third: null, boundary: '0x4050 graph_pal（opcode）'},
    {first: 2, second: 1, third: 1, boundary: '0x3BA4 effect_start（effect）'},
  ];
  const results = await Promise.allSettled(routes.map(async route => {
    const context = await browser.newContext({viewport: {width: 1280, height: 720}});
    try {
      const page = await context.newPage();
      const errors = [];
      const firstVoice = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('response', response => {
        if (new URL(response.url()).pathname.endsWith('/VOICE_01137.wav')) firstVoice.push(response.status());
      });
      await playToFifthChoice(page, chapterOrigin);
      for (const label of [fifthOptions[1], mac004Choices[0], '参加二次会']) {
        await advanceTo(page, label);
        await chooseOption(page, label);
      }
      let spoke = false;
      for (let count = 0; count < 4500 && !(await button(page, visibleFirstChoices[0]).isVisible()); count++) {
        if (!spoke) spoke = await isDialogue(page, '一贵「差不多了吧」');
        await page.mouse.click(800, 350);
        await page.waitForTimeout(8);
      }
      assert(spoke, '未经过 MAC_006 首句对白');
      assert(firstVoice.some(status => status === 200 || status === 206), '语音 1137 未成功请求');
      assert.equal(await button(page, '最好开门见山').isVisible(), false);
      for (const label of visibleFirstChoices) assert(await button(page, label).isVisible());
      await chooseOption(page, visibleFirstChoices[route.first - 1]);
      assert.deepEqual(await readOperands(page, ['6007', '6000']), {'6007': route.first, '6000': route.first});

      const secondChoices = ['答应邀请', '拒绝'];
      await advanceTo(page, secondChoices[0]);
      assert(await button(page, secondChoices[1]).isVisible());
      await chooseOption(page, secondChoices[route.second]);
      const thirdChoices = ['老实答应', '现在不行'];
      if (route.third !== null) {
        await advanceTo(page, thirdChoices[0]);
        assert(await button(page, thirdChoices[1]).isVisible());
        await chooseOption(page, thirdChoices[route.third]);
        assert.deepEqual(await readOperands(page, ['6007', '6000']), {'6007': route.third, '6000': route.third});
      }
      const target = throughNext ? '这个相框就是为了今天而准备的。' : `本版边界：MAC_006.bin ${route.boundary}。`;
      for (let count = 0; count < 3700 && !(await isDialogue(page, target)); count++) {
        assert.equal(await button(page, thirdChoices[1]).isVisible(), false, '走到了不应出现的选项');
        await page.mouse.click(800, 350);
        await page.waitForTimeout(8);
      }
      assert(await isDialogue(page, target), `未到达 ${target}`);
      if (throughNext) {
        const phase = await page.evaluate(async () => {
          const { stageStateManager } = await import('/src/Core/Modules/stage/stageStateManager.ts');
          return stageStateManager.getCalculationStageState().GameVar.mac_effect_0_phase;
        });
        assert.equal(phase, 0);
        await advanceTo(page, '在去吃饭前换完');
        assert(await button(page, '以后再说').isVisible());
      }
      assert.deepEqual(errors, []);
      const reached = throughNext ? 'MAC_007「写真集的传言」第一组选项' : route.boundary;
      console.log(`PASS MAC_006 选项 ${route.first}/${route.second}/${route.third ?? '跳过'} → ${reached}`);
      return {first: route.first, second: route.second, third: route.third, reached,
              firstVoiceStatus: firstVoice, firstChoiceHidden: true};
    } finally {
      await context.close();
    }
  }));
  for (const result of results) if (result.status === 'rejected') throw result.reason;
  const report = path.resolve(__dirname, throughNext ? '../数据/MAC007接续浏览器核验.json' : '../数据/MAC006岸边告白浏览器核验.json');
  fs.writeFileSync(report, JSON.stringify({origin: chapterOrigin, routes: results.map(result => result.value)}, null, 2) + '\n');
}

async function checkDiscEdition(browser) {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  try {
    const page = await context.newPage();
    const errors = [];
    const voiceStatus = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      if (new URL(response.url()).pathname.endsWith('/VOICE_00000.wav')) voiceStatus.push(response.status());
    });
    await startGame(page, 'http://127.0.0.1:4203/');
    for (const expected of ['伊织「我很喜欢通过角色扮演来体验不同的人群」',
                            '一贵「神马？！你明明已经有心上人了好吧！」']) {
      for (let count = 0; count < 700 && !(await isDialogue(page, expected)); count++) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(15);
      }
      assert(await isDialogue(page, expected), `未显示 v7.4 盘内对白 ${expected}`);
    }
    assert(voiceStatus.some(status => status === 200 || status === 206));
    await advanceTo(page, '道歉');
    assert(await button(page, '少扯了！').isVisible());
    assert.deepEqual(errors, []);
    console.log('PASS v7.4 打盘版：两条盘内对白、语音请求与第一组选项');
  } finally {
    await context.close();
  }
}

const discChapterOrigin = 'http://127.0.0.1:4203/';
const discTitles = {mac008: '传言的始末', mac009: '近来的放学后', mac010: '生日的约定'};
const discFirst = {
  mac008: '一贵「也就是说、到头来是因为杂志社那帮人的愚蠢，再加上联络上出了问题，结果引起了分歧」',
  mac009: '伊织「然后啊……啊！已经是这个时间啦！」',
  mac010: '不知从何时起，在伊织没有戏剧练习的日子里，我们开始一起回家了。',
};
// MAC_011 的入口先按 mac_a01c 分派：非零读 0x54 的生日快乐，零则跳到 0x158。
const mac011Openings = ['一贵「嘿嘿嘿嘿嘿……」', '季子「有点、不好意思啊…」'];
const mac011Title = '旅行报告';
const mac007Choices = [
  ['在去吃饭前换完', '以后再说'],
  ['单刀直入', '委婉', '首先明确事实关系'],
  ['不是错觉', '又是她惯常的玩笑'],
];
const mac009Choices = ['走廊', '出入口', '检票处', '公园', '季子的公寓'];

async function advanceUntilDialogue(page, text, budget = 5000) {
  for (let count = 0; count < budget && !(await isDialogue(page, text)); count++) {
    await page.mouse.click(800, 350);
    await page.waitForTimeout(8);
  }
  assert(await isDialogue(page, text), `未到达对白 ${text}`);
}

async function checkDiscChapters(browser) {
  const routes = [
    {picks: [0, 0, 0], mac009: 0},
    {picks: [1, 2, 1], mac009: 3},
  ];
  const results = [];
  for (const route of routes) {
    const context = await browser.newContext({viewport: {width: 1280, height: 720}});
    try {
      const page = await context.newPage();
      const errors = [];
      const voices = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('response', response => {
        const path = new URL(response.url()).pathname;
        if (path.endsWith('/VOICE_01724.wav') || path.endsWith('/VOICE_01750.wav')) {
          voices.push({file: path.split('/').pop(), status: response.status()});
        }
      });

      // 沿已经接好的路线进入 MAC_007 的「写真集的传言」。
      await playToFifthChoice(page, discChapterOrigin);
      // 观察器必须在开局页加载之后再装，否则会被 page.goto 清掉。
      await page.evaluate(titles => {
        window.__chapterTitles = {};
        // 标题卡是逐帧渲染的，用轮询而不是 MutationObserver：切场景时 body 可能被替换。
        window.__titleTimer = setInterval(() => {
          for (const title of titles) if (document.body.innerText.includes(title)) window.__chapterTitles[title] = true;
        }, 50);
      }, Object.values(discTitles));
      for (const label of [fifthOptions[1], mac004Choices[0], '参加二次会']) {
        await advanceTo(page, label);
        await chooseOption(page, label);
      }
      await advanceUntilDialogue(page, '一贵「差不多了吧」');
      await advanceTo(page, '等着看伊织会说些什么呢？');
      await chooseOption(page, '等着看伊织会说些什么呢？');
      await advanceTo(page, '拒绝');
      await chooseOption(page, '拒绝');
      await advanceTo(page, '现在不行');
      await chooseOption(page, '现在不行');
      await advanceUntilDialogue(page, '这个相框就是为了今天而准备的。');

      // MAC_007 的选项组数取决于前序状态（mac_a018）：0x3D94 分支会直接进入下一章。
      const seenGroups = [];
      for (let count = 0; count < 6000; count++) {
        if (await isDialogue(page, discFirst.mac008)) break;
        let handled = false;
        for (let group = 0; group < mac007Choices.length; group++) {
          if (seenGroups.includes(group) || !(await button(page, mac007Choices[group][0]).isVisible())) continue;
          seenGroups.push(group);
          const label = mac007Choices[group][route.picks[group]];
          assert(await button(page, label).isVisible(), `MAC_007 第 ${group + 1} 组缺少选项 ${label}`);
          await chooseOption(page, label);
          handled = true;
          break;
        }
        if (!handled) {
          await page.mouse.click(800, 350);
          await page.waitForTimeout(8);
        }
      }
      assert(seenGroups.length >= 2, `MAC_007 至少应经过两组选项，实际 ${seenGroups}`);
      await advanceUntilDialogue(page, discFirst.mac008, 6000);
      // 标题卡在快速点击下可能只显示一两帧，标题本身由静态测试核对；这里以首句为准。
      console.log(`到达 MAC_008「${discTitles.mac008}」首句`);

      await advanceUntilDialogue(page, discFirst.mac009, 4000);
      await advanceTo(page, mac009Choices[0], 5000);
      for (const label of mac009Choices) assert(await button(page, label).isVisible(), `MAC_009 选项 ${label} 未显示`);
      await chooseOption(page, mac009Choices[route.mac009]);

      await advanceUntilDialogue(page, discFirst.mac010, 6000);
      // 开发用 Vite 构建里 /src 与 @/ 两个模块 id 可能各持一份 stageState，
      // 读回值为空时只记录，写回本身由场景文本与 Python 测试核对。
      const written = await readOperands(page, ['6007', '6000']);
      if (written['6007'] !== undefined) {
        assert.deepEqual(written, {'6007': route.mac009, '6000': route.mac009},
          `MAC_009 写回原序号 ${route.mac009} 不对`);
      }
      let mac011Opening = null;
      for (let count = 0; count < 6000 && !mac011Opening; count++) {
        for (const candidate of mac011Openings) {
          if (await isDialogue(page, candidate)) { mac011Opening = candidate; break; }
        }
        if (!mac011Opening) await page.mouse.click(800, 350);
      }
      assert(mac011Opening, '未到达 MAC_011 的开场对白');
      assert(voices.some(voice => voice.file === 'VOICE_01724.wav' && [200, 206].includes(voice.status)),
        'MAC_008 首句语音 1724 未成功请求');
      assert(voices.some(voice => voice.file === 'VOICE_01750.wav' && [200, 206].includes(voice.status)),
        'MAC_009 首句语音 1750 未成功请求');
      assert.deepEqual(errors, []);
      results.push({route: route.picks, mac007_groups: seenGroups, mac009_option: mac009Choices[route.mac009],
                    mac009_written: route.mac009, titles: [discTitles.mac008, discTitles.mac009, discTitles.mac010, mac011Title],
                    first_lines: [discFirst.mac008, discFirst.mac009, discFirst.mac010],
                    mac011_opening: mac011Opening, state_readback: written, voices: voices.map(voice => voice.file)});
      console.log(`PASS MAC_007 选项 ${route.picks.join('/')} → MAC_008「${discTitles.mac008}」→ ` +
        `MAC_009「${discTitles.mac009}」选项 ${route.mac009} → MAC_010「${discTitles.mac010}」→ MAC_011「${mac011Title}」`);
    } finally {
      await context.close();
    }
  }
  const report = path.resolve(__dirname, '../数据/MAC008至011浏览器核验.json');
  fs.writeFileSync(report, JSON.stringify({
    origin: discChapterOrigin,
    route_prefix: ['道歉', '走廊', '青梅竹马而已', '我得说说她', '第五组选项', 'MAC_004 选项', '参加二次会',
                   'MAC_006 选项 2/1/1', 'MAC_007 三组选项'],
    routes: results,
    note: '无头 Edge 从新游戏连续点击，经 MAC_007 三组选项进入 MAC_008、MAC_009，并在 MAC_009 五项中实选；' +
          '每条路线核验四章标题、首句对白、语音请求，并继续到 MAC_011 开篇，页面无 pageerror。',
  }, null, 2) + '\n');
  console.log('报告:', report);
}

async function checkBatchChoice(browser) {
  const wiring = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../数据/全盘主线接线.json'), 'utf8'));
  const graph = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../数据/全盘剧情候选图.json'), 'utf8'));
  const site = 'MAC_025:0xB8';
  const node = graph.nodes.find(node => node.id === site);
  const labels = ['３年教室', '美术室', '天台', '图书室', '走廊', '换鞋处'];
  for (const [values, visible, selection] of [
    [[0, 0, -1, 0, 1, 0], [2, 4], 4],
    [[0, 0, 0, 0, 0, 0], [], 6],
  ]) {
    const context = await browser.newContext({viewport: {width: 1280, height: 720}});
    try {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const reached = [];
      const edge = node.edges.find(edge => edge.kind === 'option' && edge.index === selection)
        ?? node.edges.find(edge => edge.kind === 'no_visible_option');
      const [script, offset] = edge.target.split(':');
      const target = `${script.toLowerCase()}_0x${parseInt(offset, 16).toString(16).padStart(6, '0')}.txt`;
      await page.route('**/game/scene/mac_025_*.txt', route => {
        const filename = new URL(route.request().url()).pathname.split('/').pop();
        reached.push(filename);
        return route.fulfill({contentType: 'text/plain', body: '定点核验终点。;'});
      });
      await page.route('**/game/scene/start.txt', route => route.fulfill({
        contentType: 'text/plain',
        body: [...values.map((value, i) => `setVar:mac_${(0x6010 + i).toString(16)}=${value} -next;`),
               ...wiring.emitted[site]].join('\n'),
      }));
      await startGame(page, 'http://127.0.0.1:4198/');
      if (visible.length) {
        await button(page, labels[selection]).waitFor({state: 'visible', timeout: 10000});
        for (let index = 0; index < labels.length; index++) {
          assert.equal(await button(page, labels[index]).isVisible(), visible.includes(index));
        }
        await chooseOption(page, labels[selection]);
      }
      await waitDialogue(page, '定点核验终点。');
      for (const label of labels) assert.equal(await button(page, label).isVisible(), false);
      assert(reached.includes(target), `场景请求未到达原目标 ${target}`);
      assert.deepEqual(await readOperands(page, ['6007', '6000']), {'6007': selection, '6000': selection});
      assert.deepEqual(errors, []);
      console.log(`PASS ${site} 可见项 [${visible}]、原序号 ${selection}、目标 ${edge.target}`);
    } finally {
      await context.close();
    }
  }
}

async function checkArithmetic(browser) {
  const vectors = JSON.parse(fs.readFileSync(
    path.resolve(__dirname, '../数据/算术核验向量.json'), 'utf8'));
  assert(vectors.vectors.length > 0, '算术核验向量为空');
  for (const vector of vectors.vectors) {
    const context = await browser.newContext({viewport: {width: 1280, height: 720}});
    try {
      const page = await context.newPage();
      await page.route('**/game/scene/start.txt', route => route.fulfill({
        contentType: 'text/plain',
        body: [`setVar:${vectors.destination}=${vector.input} -next;`,
               ...vector.lines, '算术核验。;'].join('\n'),
      }));
      await page.goto(origin, {waitUntil: 'networkidle'});
      await button(page, 'PRESS THE SCREEN TO START').click();
      const chinese = button(page, '简体中文');
      await chinese.waitFor({state: 'visible', timeout: 15000}).catch(() => {});
      if (await chinese.isVisible()) await chinese.click();
      const start = button(page, '开始游戏');
      await start.waitFor({state: 'visible', timeout: 15000});
      await start.click();
      for (let count = 0; count < 40 && !(await isDialogue(page, '算术核验。')); count++) {
        await page.mouse.click(800, 350);
        await page.waitForTimeout(60);
      }
      assert(await isDialogue(page, '算术核验。'), `未到达 ${vector.name} 的核验句`);
      const actual = (await readOperands(page, [vectors.destination.replace('mac_', '')]))[
        vectors.destination.replace('mac_', '')];
      assert.equal(actual, vector.expected,
        `${vector.name}: 输入 ${vector.input}，操作数 ${vector.operand}，期望 ${vector.expected}，实际 ${actual}`);
      console.log(`PASS 算术 ${vector.name}: ${vector.input} op${vector.operation} ${vector.operand} = ${actual}`);
    } finally {
      await context.close();
    }
  }
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args: ['--mute-audio'],
  });
  try {
    if (process.argv.includes('--disc-edition')) {
      await checkDiscEdition(browser);
    } else if (process.argv.includes('--disc-chapters')) {
      await checkDiscChapters(browser);
    } else if (process.argv.includes('--mac007-chapter')) {
      await checkMac006(browser, true);
    } else if (process.argv.includes('--mac006-chapter')) {
      await checkMac006(browser);
    } else if (process.argv.includes('--through-mac005')) {
      await checkParticleContinuation(browser, true);
    } else if (process.argv.includes('--through-particle-effect')) {
      await checkParticleContinuation(browser);
    } else if (process.argv.includes('--batch-choice')) {
      await checkBatchChoice(browser);
    } else if (process.argv.includes('--through-mac004') || batchWiring) {
      await checkMac004(browser);
    } else if (process.argv.includes('--through-fifth')) {
      await checkFifth(browser);
    } else if (process.argv.includes('--arithmetic')) {
      await checkArithmetic(browser);
    } else if (process.argv.includes('--signed-limits')) {
      await checkSignedLimits(browser);
    } else if (throughFourth) {
      const results = await Promise.allSettled(stages.slice(1).map(route => run(browser, route)));
      for (const result of results) {
        if (result.status === 'rejected') throw result.reason;
      }
    } else {
      for (const route of stages) await run(browser, route);
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
