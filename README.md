# 多 Agent 协作工具包（Claude Code / Codex / TRAE）

让同一个仓库里的多个 AI Agent 共享同一套规范和同一份过程记录：**一方做过的判断、否决过的路径、留下的未决项，另一方下次开会话时自动出现在上下文里**，不需要你手工在两边转述。

经两个真实项目落地验证（一个知识库型、一个调研型）。Claude Code 与 Codex 两侧是定稿版本；**TRAE 是实验性接入**——它没有 lifecycle hook，读写靠规则文件驱动，等级低一档，详见下面「TRAE 的等级不一样」。

## 它解决什么问题

两个 Agent 各写各的，你就变成了人肉同步管道：跟 Codex 讨论完的结论，得手工粘给 Claude；Claude 否决过的方案，Codex 过两天又提一遍。更糟的是**你不知道对方否决过什么**——结论能转述，判断过程转述不了。

这套机制加了一层「协作流水」：不是结论层，是过程层，允许写半成品。装了 hook 的一侧自动读写，成本受控（每轮提醒约 330 字符，会话开始只注入比你上次记录更新的内容）。

## 三步装完

0. 拿到工具包：

   ```bash
   git clone https://github.com/ah052533sd/Agent-Collaboration-Kit.git
   ```

1. 把整个文件夹放到目标仓库旁边（或直接放进仓库，装完删掉）。
2. 在仓库里开 **Claude Code**，把 [`SETUP-CLAUDE.md`](SETUP-CLAUDE.md) 整份粘进去。它会装文件、写协议、跑六项验证。
3. 在同一仓库开 **Codex**，把 [`SETUP-CODEX.md`](SETUP-CODEX.md) 整份粘进去。它会引导你完成 hook 信任审批，再跑八项验证。
4. **（可选）** 要让 TRAE 也参与，把 [`SETUP-TRAE.md`](SETUP-TRAE.md) 粘给它。没有 hook 要装，但它得先实测确认自己的规则文件路径。

**最终验收看一件事**：Claude 写一条流水 → 你开一次 Codex，它开头就看到了 → Codex 回一条 → 你开一次 Claude，它开头也看到了。握手成功即装好。

装的过程中 Agent 会问你两个问题（任务产物放哪个目录、知识层写入要不要每次确认），照它给的判断依据答即可。

## 包里有什么

```
README.md              你正在看的这份
SETUP-CLAUDE.md        丢给 Claude Code 执行（含验证流程）
SETUP-CODEX.md         丢给 Codex 执行（含信任审批 + 验证流程）
SETUP-TRAE.md          丢给 TRAE 执行（无 hook，含规则文件路径实测）
DESIGN-NOTES.md        为什么长成这样：关键取舍、被否决的方案、实测数据
AGENTS.md / CLAUDE.md  维护本仓库时给 Agent 的规则（不是给你装的协议）
check-drift.py         漂移检查：脚本/Hook 一致性、硬约束、协议差异、流水健康度
reviews/               每周复查报告（本地生成，不进版本控制）
template/
  AGENTS.md            协作协议，各方共用的唯一真相源（两处需按项目填空）
  CLAUDE.md            指针文件，只指向 AGENTS.md
  journal/README.md    协作流水这一层的规则
  journal/bin/*.py     五个脚本，各方共用一份实现
  .claude/settings.json  Claude 三个 hook
  .codex/hooks.json      Codex 三个 hook
  .trae/rules/project_rules.md  TRAE 的常驻规则（它没有 hook，靠这个）
  gitignore-additions.txt
```

## TRAE 的等级不一样

按「规范的执行力分三档」（见 [DESIGN-NOTES.md](DESIGN-NOTES.md)），Claude 和 Codex 靠 hook 站在**机制强制**档——想不执行也不行；**TRAE 只能站在上下文规范档**，因为 2026-07 实测它不提供任何 lifecycle hook。

具体差别：

| | Claude / Codex | TRAE |
|---|---|---|
| 会话开始读未读条目 | hook 自动注入 | 自己跑 `context.py --agent trae --manual` |
| 每轮写入提醒 | hook 自动，约 330 字符 | 无 |
| 会话结束留痕 | hook 写单行信封 | 不写——它的会话记忆自动落盘，信息比信封更全 |
| 读另外两方的原始记录 | 可以 | **可能不行**，它跑在沙箱里 |

所以 **TRAE 漏写 journal 时没有任何兜底，而且不报错**。它适合当「额度耗尽时接力的第三棒」，不适合当需要并发协作的对等一方。装之前想清楚这一点。

## 维护：本包是唯一真相源

协议**不放全局**（`~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`），放在本包里，各项目持有拷贝。理由三条：全局文件不进 git，规则为什么这么定就追不回来、也交不出去；没装这套机制的项目会被指挥去调用不存在的脚本；而且 Claude 和 Codex 的全局文件本来就是两份，全局化只是把漂移从「项目 × N」换成「工具 × 2」，还没有 `git diff` 能发现。

所以维护方式是**单一真相源 + 漂移检测**：

```
改协议 → 先改 template/AGENTS.md → 再同步到各项目 → 周日复查兜底
```

**每周日上午自动复查**（Claude 本地定时任务 `agent-protocol-review`，只读、不改文件、不 commit）：

1. 跑 `check-drift.py`——三处脚本与 Codex Hook 定义是否一致、硬约束是否还在、协议节逐行差异、近 7 天流水的信封/语义比例
2. 读两个仓库近 7 天的 journal 和 git log，逐条问这 6 条规则：**拦住过错误吗 / 被违反过吗 / 被绕过了吗 / 变成噪音了吗**
3. 产出 `reviews/<日期>.md`：删 / 改 / 补 / 下沉四类建议，每条带证据和影响面
4. 你拍板后，改工具包模板，再同步到各项目

**默认动作是删**——协议每一行都是每个 Agent 每次会话的常驻成本，规则越多单条被遵守的概率越低。保留需要证据，删除不需要。唯一例外是防漂移条款（「不引入写入锁」「全量注入是有意保留的」这类），它们看着像解释，实际是防止下一个 Agent 出于好意把已权衡过的决定优化掉。

随时想查一次：

```bash
/usr/bin/python3 "Agent Collaboration Kit/check-drift.py"
```

## 两条设计上的硬要求

**1. 脚本只有一份，各方共用，只差 `--agent` 参数。**
最早的版本是两侧各写一份实现，半天之内就漂移出四个 bug，其中最隐蔽的一个让一方的判断**永久不被对方读到，且不报任何错**。共用一份实现是结构性消除，不是省事。加第三方时这条又赚了一次：读取游标本来就是「我 vs 其他所有人」，加一方不用动。

**2. `CLAUDE.md` 只放指针，协议只写在 `AGENTS.md`。**
两份规范一定会漂移。

## 前置条件

- macOS，`/usr/bin/python3`（系统自带 3.9 即可，无第三方依赖）
- 目标仓库是 git 仓库，**且至少有一个 commit**（HEAD 不存在时协议里的并发检查全部失效）
- Codex 侧需要你在界面上批准一次项目 hook——安全控制，Agent 不能代劳，也不该代劳
- TRAE 侧无需批准任何东西；规则文件放 `.trae/rules/project_rules.md`（2026-07 实测生效，换版本需重测，流程见 `SETUP-TRAE.md` 第 3 节）

## 一句话原理

`knowledge/`（或你项目的知识层）存已确认的结论，任务目录存产物和证据，**两者都会过滤掉过程**。`journal/` 是唯一按时间、跨任务、允许写半成品的层，专门装「试过什么、否决了什么、为什么」。会话开始时（TRAE 之外由 hook 自动）只注入比你上次记录更新的条目，会话结束时自动补一条单行信封记录「这里发生过一个会话、原始记录在哪」。真要复核对方的原始上下文时，用 `peek.py` 抽取——单个原始记录实测出现过 135 MB，直接读会撑爆上下文。
