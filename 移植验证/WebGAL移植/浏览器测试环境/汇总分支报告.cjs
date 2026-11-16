// 汇总「含嵌套选项」的逐项实跑结果。
// 用法：node 汇总分支报告.cjs [--report ../数据/分支扫描_含嵌套_全量.json] [--out ../数据/分支扫描_汇总.md]

const fs = require('node:fs');
const path = require('node:path');
const arg = (name, fallback) => {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
};
const reportFile = path.resolve(__dirname, arg('--report', '../数据/分支扫描_含嵌套_全量.json'));
const outFile = path.resolve(__dirname, arg('--out', '../数据/分支扫描_汇总.md'));
const report = JSON.parse(fs.readFileSync(reportFile, 'utf8'));

const points = report.points || {};
const pointList = Object.values(points).sort((a, b) => (a.depth - b.depth) || a.id.localeCompare(b.id));
const rows = report.results.slice().sort((a, b) => (a.depth - b.depth) || a.pointId.localeCompare(b.pointId) || a.index - b.index);
const totals = {};
for (const row of rows) totals[row.status] = (totals[row.status] || 0) + 1;
const mainPoints = pointList.filter(point => point.depth === 0);
const nestedPoints = pointList.filter(point => point.depth > 0);
const voiceIds = row => (row.voices || []).map(voice => voice.id).filter((id, index, list) => id && list.indexOf(id) === index);
const parentText = row => (row.parent ? `${row.parent.pointId}「${row.parent.option}」` : '主线');
// 回访的选项点分两类：①循环——回访的点正在当前点的祖先链上，展开会无限递归；
// ②汇合——该点已由别处（主线或其它分支）覆盖，属于正常汇合，不重复入队。
const ancestorsOf = pointId => {
  const chain = new Set();
  let current = points[pointId];
  while (current?.parent) {
    chain.add(current.parent.pointId);
    current = points[current.parent.pointId];
  }
  return chain;
};
const loopRows = [];
for (const row of rows) {
  const chain = ancestorsOf(row.pointId);
  for (const nested of row.nested_points || []) {
    if (nested.created) continue;
    const kind = chain.has(nested.pointId) ? '循环（回到祖先选项点）' : '汇合（该选项点已覆盖）';
    loopRows.push({ row, nested, kind });
  }
}

const lines = [];
lines.push('# 逐选项浏览器实跑汇总（含嵌套选项）');
lines.push('');
lines.push(`- 来源报告：\`${path.basename(reportFile)}\`${report.updated_at ? `（更新 ${report.updated_at}）` : ''}`);
lines.push(`- 选项点：**${pointList.length}**（主线 ${mainPoints.length} + 嵌套 ${nestedPoints.length}），选项行：**${rows.length}**`);
lines.push(`- 状态统计：${Object.entries(totals).map(([status, count]) => `${status} ${count}`).join(' / ')}`);
lines.push('- 口径：每个选项点逐项真实点击；从真实游玩时引擎原生存档读档，未手写状态变量。');
lines.push('- `converged` = 离开分支入口、推进 ≥16 次点击后回到默认主线后续场景；`end` = 到达结束指令；`loop`/`unexpandable` = 显式标注的循环或不可展开项。');
lines.push('');
lines.push('| # | 选项点 | 层级 | 来源 | 场景 | 句号 | 选项 | 点击后场景 | 收束/终点 | 语音 | 状态 |');
lines.push('| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |');
rows.forEach((row, index) => {
  const ids = voiceIds(row);
  const voiceText = ids.length ? `${ids.length} 条（${ids.slice(0, 3).join('、')}${ids.length > 3 ? '…' : ''}）` : '无';
  const outcome = row.converged_at ? `→ ${row.converged_at}` : row.reached_end ? '到达 end 指令' : (row.error || '未收敛');
  const source = row.depth === 0 ? '主线' : `父选项 ${parentText(row)}`;
  const scene = `\`${row.scene}\``;
  lines.push(`| ${index + 1} | ${row.pointId} | ${row.depth === 0 ? '主线' : `嵌套 D${row.depth}`} | ${source} | ${scene} | ${row.sentenceId} | ${row.choice} | \`${row.target_scene || '未记录'}\` | ${outcome} | ${voiceText} | ${row.status} |`);
});
lines.push('');
lines.push('## 嵌套选项点清单');
lines.push('');
if (!nestedPoints.length) lines.push('无。');
for (const point of nestedPoints) {
  lines.push(`- ${point.id}（D${point.depth}）\`${point.scene}\` 句 ${point.sentenceId}，${point.choices.length} 项：${point.choices.join(' / ')}；来源：${point.parent ? `${point.parent.pointId}「${point.parent.option}」` : '未知'}`);
}
lines.push('');
lines.push('## 循环 / 汇合标注（不重复入队）');
lines.push('');
lines.push('判定依据：回访的 (场景, 句号) 若在当前选项点的祖先链上，则继续展开会无限递归，记为循环；否则该点已由主线或其它分支覆盖，记为汇合。两种情况都不重复建点，父项按第 1 项继续推进收束；被回访的点本身都有自己的逐项记录。');
lines.push('');
if (!loopRows.length) {
  lines.push('无：所有遇到的选项点都是首次出现，没有回访同一 (场景, 句号) 的情况。');
} else {
  const cycleCount = loopRows.filter(item => item.kind.startsWith('循环')).length;
  const mergeCount = loopRows.filter(item => item.kind.startsWith('汇合')).length;
  lines.push(`- 循环：${cycleCount} 处；汇合：${mergeCount} 处。`);
  for (const { row, nested, kind } of loopRows) {
    lines.push(`- ${kind}：${row.rowId}「${row.choice}」推进时遇到 \`${nested.scene}\` 句 ${nested.sentenceId}（选项：${nested.options.join(' / ')}），已存在为 ${nested.pointId}；父项按第 1 项「${nested.autoPicked}」继续推进。`);
  }
}
lines.push('');
lines.push('## 未完成项');
lines.push('');
const failed = rows.filter(row => row.status !== 'converged' && row.status !== 'end');
if (!failed.length) {
  lines.push('无：全部选项行均由真实点击到达可判定的收束点。');
} else {
  for (const row of failed) {
    lines.push(`- ${row.rowId}（D${row.depth}）\`${row.scene}\`「${row.choice}」：${row.status}，${row.error || '无错误信息'}`);
  }
}
fs.writeFileSync(outFile, `${lines.join('\n')}\n`);
console.log(`汇总 ${rows.length} 行（${pointList.length} 点，其中嵌套 ${nestedPoints.length}）→ ${outFile}`);
