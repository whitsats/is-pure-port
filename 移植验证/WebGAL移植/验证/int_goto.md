# `int_goto`（`0x03`）：同一剧本内的绝对跳转

> **调用返回更新：** `int_call`/`int_return` 已依据原指令对照实现，带栈的嵌套构造测试通过；真实调试脚本可进入子程序，但在未实现的随机运算处停止。详见 [同剧本调用返回](同剧本调用返回.md)。

> **2026-11-15 修正：** 旧版 `changeScene:./game/scene/文件名.txt;` 会被 `webgal-parser` 再次加上场景目录，导致错误路径被 Vite 返回 HTML。应使用 `changeScene:文件名.txt;`。转换器及新的跨剧本样片已修正；旧生成场景和旧报告仍保留为历史记录，不能作为切换成功的证据。

**结论（2026-11-14）：** `int_goto` 已接入 `convert_program`，并在一段真实的
`MAC_001.bin 0x3B94` 路径上连续执行两次跳转，产出 87 句台词、2 条等待，随后停在
`0x51E4` 的 `ext_goto`。转换器不再把这条控制流指令当作未知指令停止。

本轮进一步把 `0x51E4` 的 `ext_goto` 接上：目标为 `MAC_002.bin 0x0C`，用
`--scene-dir` 生成父/目标两个场景，父场景末用 `changeScene` 接续，目标执行到
`0x74` 的 `reg_calc 0x17` 时显式停止（见第 4 节）。

## 1. ELF 证据

| 项目 | 地址/值 | 依据 |
| --- | --- | --- |
| 命令表项 | `0x03`，名称 `int_goto`，8 字节 | `数据/跳转与等待ELF证据.json` 的 `command_table["0x03"]` |
| 处理函数 | `0x00119590` | 命令表 `handler` |
| 目标字段 | `u32@4` | `0x001195A8` `lw $v1, 4($a2)` |
| 脚本基址 | `ctx+0x44` 的 `+0xC` | `0x001195A4` `lw $v0, 0xc($a1)` |
| 新 ip | `script_base + target` | `0x001195AC` `addu $v0, $v0, $v1`；`0x001195B4` `sw $v0, 8($a1)` |
| 其他字段 | 不读 `ip[1]`，不写状态块 | 处理函数只读 `ip@0`、`u32@4` 与脚本基址 |

处理函数是单状态的：没有 `ctx+0x10` 状态机，也没有 `ext_goto` 的加载/等待步骤。
因此转换器可以直接把当前命令位置改为目标偏移；目标必须已经落在解析器识别出的命令边界上，
否则显式停止，不猜测目标处的指令长度。

证据生成器：`转换器/跳转与等待证据.py`（新增 `int_goto_evidence`），
证据文件：`数据/跳转与等待ELF证据.json`。旧版（无 `int_goto`）保留为
`数据/跳转与等待ELF证据_无int_goto.json`。

## 2. 覆盖与目标边界

- `数据/入口片段_扩展候选.json`（73 个剧本）共 **835** 处 `int_goto`。
- 旧版 `数据/入口片段.json`（65 个剧本）共 **827** 处；逐条检查后，827 个目标全部落在
  同一剧本已解析的命令边界上。`tests/test_int_goto.py` 固定了这一检查。
- 目标不一定是“向前”跳；现有 `convert_program` 的 `visited` 防环规则会在重复到达同一
  偏移时停止并给出“可能成环”的原因。本轮没有把循环展开成无限执行，也没有静默跳过。
- `int_goto` 是原程序的控制流，不是 WebGAL 语句；转换器把它记入报告 `int_gotos`，
  `webgal.mapped = true` 表示“已按原语义跟进”，不生成伪造的 `jump` 命令。

## 3. 真实片段：`MAC_001.bin 0x3B94`

原字节：

```text
0x3B94  03 00 00 00 24 3C 00 00   # int_goto 0x3C24
0x3C24  03 00 00 00 5C 42 00 00   # int_goto 0x425C
```

从 `0x3B94` 开始执行：

- 第一次跳到 `0x3C24`，跳过 `0x3B9C`–`0x3C1C` 的 file/SE/条件块；
- 第二次跳到 `0x425C`，继续执行后续对白；
- 最终 87 条 `msg_disp2`、2 条 `time_wait`，报告中的 `int_gotos` 为
  `[(0x3B94, 0x3C24), (0x3C24, 0x425C)]`；
- 停在 `0x51E4` 的 `ext_goto`（目标资源组 0 索引 2）；这个单文件产物不生成场景，跨剧本
  接续另见第 4 节，不是未知指令被跳过。

产物：

- `数据/int_goto片段_MAC001_0x3B94_v74.txt`（89 行 = 87 句 + 2 条 wait）
- `数据/int_goto片段_MAC001_0x3B94_v74.txt.json`（含 `int_gotos`、`sources`、`stop`）
- 语音校验：`数据/语音校验_MAC001_语音231至281.json`（49 条，文件提取链与 PCM 均通过）
- 语音副本：`数据/语音_int_goto/`

复现：

```bash
cd 移植验证/WebGAL移植
python -B 转换器/跳转与等待证据.py --output 数据/跳转与等待ELF证据.json \
  --scripts ../输出-保护边修复/MAC
python -B 转换器/emit_webgal.py --script MAC_001.bin --offset 0x3B94 \
  --output '数据/int_goto片段_MAC001_0x3B94_v74.txt' \
  --mapping '数据\三版译文与汉化盘核查_补字码.tsv' \
  --voice-manifest 数据/语音校验_MAC001_语音231至281.json \
  --voice-dir 数据/语音_int_goto --program
python -B -m unittest discover -s tests
```

开头产物也因报告新增 `int_gotos` / `int_goto_mapping` 字段而重建；文本未变（仍是
74 句 + 1 条 `wait:2000;`，停在 `MAC_001 0x58` 的 `0x17`）。重跑到临时文件与仓库产物
逐字节一致。

## 4. `ext_goto` 多场景接续

`MAC_001 0x51E4` 的 `06000200` 由 `parse_ext_goto` 静态解析为组 0、索引 2，即
`MAC_002.bin` 的入口 `0x0C`；目标文件头/入口已由 `parse_ext_goto` 核对。目标从
`0x0C` 执行到 `0x74` 的 `reg_calc 0x17` 停止，没有台词，但 `msg_mode`、fade、file、SE、
graph 命令都被执行/记账。

`convert_chain` 现在额外返回 `scene_sequences`：每段保留自己的 `lines`，`--scene-dir`
把它们写成独立 WebGAL 场景（使用时把目录内容放到 `game/scene/`），并在 `ext_goto` 段末追加：

```text
changeScene:mac_002_0x00000c.txt;
```

这是 WebGAL 4.6.6 已注册的 `changeScene` 命令；`webgal-parser` 的 `contentParser` 已对场景文件名调用 `assetSetter`，故原脚本只应写文件名。目标场景没有可生成台词时，只写一条 `__commment`：

```text
__commment:MAC_002.bin 0x00000C 执行到 0x000074 的 reg_calc 后显式停止;
```

这不是剧情占位，也不掩盖 `0x17`：`int_goto跨剧本片段...json` 的 `stop` 仍完整记录
`reg_calc 0x17` 的具体原因。

报告里这条 `ext_goto` 的 `webgal.mapped` 现在是 `true`，`command` 就是上面那条
`changeScene`；它不再是“只记录、未映射”的事件。

产物：

- `数据/int_goto跨剧本片段_MAC001至MAC002_v74.txt(.json)`（89 行，`scene_files` 两条）
- `数据/跨剧本场景_MAC001至MAC002/mac_001_0x003b94.txt`（90 行：89 + `changeScene`）
- `数据/跨剧本场景_MAC001至MAC002/mac_002_0x00000c.txt`（停止注释）

复现时增加：

```bash
python -B 转换器/emit_webgal.py --script MAC_001.bin --offset 0x3B94 \
  --output '数据/int_goto跨剧本片段_MAC001至MAC002_v74.txt' \
  --mapping '数据\三版译文与汉化盘核查_补字码.tsv' \
  --voice-manifest 数据/语音校验_MAC001_语音231至281.json \
  --voice-dir 数据/语音_int_goto --program --follow-goto \
  --scene-dir '数据/跨剧本场景_MAC001至MAC002'
```

目标入口不是已解析命令边界时，`convert_chain` 在进入目标前停止并写
`ext_goto_target` / “不是已解析的命令边界”；`write_scene_chain` 也不会生成通往该未知目标的
`changeScene`，只保留带停止注释的目标场景文件。不会把未知目标当空操作执行。

## 5. 仍然阻塞

- `int_call`（`0x04`）/`int_return`（`0x05`）：调用栈字段已可从 `0x1195C8`/`0x119650`
  读出，但现有真实调用目标（`MAC_069 0x0C`、`MAC_063/064/065` 的子程序）都会进入
  `reg_calc 0x12` 或剧本内存读写，尚不能完整跑通一次“调用后返回”的真实路径。
- `ext_call`/`ext_return`：当前 73 个片段没有 `ext_call`，不能在真实剧本上验证调用。
- `reg_calc 0x10`：当前片段没有实际出现；虽有处理函数证据，但缺少真实执行证据，未实现。
- `if` 参数 8/9：当前片段没有实际出现；不能凭静态表项臆造分支语义。
- `reg_calc 8/9/0x0B/0x0C/0x12/0x13–0x16` 与 `0x17`：分别需要剧本内存模型、运行时随机
  种子或运行时位表/场景表，仍显式停止。
- `ext_goto` 的组 0 运行时名字表与“索引 → `MAC_xxx.bin`”仍未静态证明；本轮沿用
  `../MAC_命令表/跨剧本跳转候选.tsv` 的候选规则，并核对目标文件头/入口，不声称已还原名字表。
