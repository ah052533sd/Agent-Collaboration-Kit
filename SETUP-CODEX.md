# 给 Codex 的安装说明书

> **怎么用：** 在目标仓库打开 Codex，把本文件整份粘贴进去（或说「按 SETUP-CODEX.md 执行」并把文件放进仓库）。
> 下面的内容是给 Codex 的指令，不是给人读的操作手册。

---

你要让当前仓库的 Claude Code ↔ Codex 协作机制在**你这一侧**真正生效，然后自己验证，最后报告给用户。

装完的效果：两个 Agent 共享同一套规范、同一份过程流水；一方做过的判断、否决过的路径、留下的未决项，另一方下次开会话时自动出现在上下文里，不需要用户手工转述。

**你这一侧比 Claude 多一道关卡**：Codex 的项目级 hook 必须经过本机信任审查才会执行。这一步只能由用户在 Codex 界面完成，你不能代劳（原因见第 3 节）。

## 0. 前置检查（不满足就停下问用户）

```bash
git rev-parse --show-toplevel     # 必须是 git 仓库
git rev-parse --short HEAD        # 必须至少有一个 commit
/usr/bin/python3 -V               # 必须存在；脚本兼容 3.9
ls journal/bin/ .codex/hooks.json 2>&1
```

**仓库没有任何 commit 时停下**：协议里的 HEAD 比对、空转判定全部依赖 HEAD 存在。先问用户是否可以建立第一个 commit。

## 1. 文件是否已就位

如果 `journal/bin/` 里已有五个脚本、`.codex/hooks.json` 也在，说明另一侧（Claude）已经装过，**跳到第 2 节**。

如果没有，从工具包 `template/` 复制到仓库根目录（本步骤幂等，已存在且一致就跳过）：

| 来源 | 目标 |
|---|---|
| `template/journal/bin/*.py` | `journal/bin/` |
| `template/journal/README.md` | `journal/README.md` |
| `template/.codex/hooks.json` | `.codex/hooks.json` |
| `template/.claude/settings.json` | `.claude/settings.json` |

然后按 `template/AGENTS.md` 写协议（已有 `AGENTS.md` 就把「多 Agent 协作协议」整节插到最前面，**保留原有全部内容**），并按 `template/CLAUDE.md` 写指针文件。两处填空必须问用户：

1. **第 1 条的任务目录**——本仓库放任务产物的地方叫什么。不要预建空目录。
2. **第 2 条的知识层写入门槛**——A 档（所有写入都要确认）还是 B 档（纯新增可直接写，改写删除需确认）。**不要替用户决定**。

追加 `.gitignore`：`.journal-state/`（hook 运行态，不进版本控制）。

Commit 时只 stage 实际涉及的路径，message 用 `[codex]` 前缀，禁止 `git add -A`。

## 2. 读协议（装完先读，别跳过）

按顺序读：`AGENTS.md` 的「多 Agent 协作协议」→ `journal/README.md` → 本仓库知识层的入口文件。

重点确认三件事，并在报告里复述你的理解：

- 你写知识层时的门槛是哪一档；
- 关键判断要**立即**用 `journal/bin/append.py` 追加，不是等会话结束；
- 读对方的原始会话记录只能用 `journal/bin/peek.py`，**禁止对 `.jsonl` 直接 cat**（实测单个 rollout 达 135 MB）。

## 3. 信任审批（你这一侧的唯一硬阻塞）

先看当前状态：

```bash
grep -n "hooks.json" ~/.codex/config.toml
```

如果没有本仓库 `.codex/hooks.json` 的条目，说明 hook 尚未受信任，**你的 SessionStart 不会注入任何东西**。

**你要做的**：告诉用户去哪里批，然后等他批完。已知入口（实测于 codex-cli `0.146.0-alpha.3.1`，**以你的实际版本为准，对不上就自己查清楚再说**）：

- **Desktop 构建**：设置 → 钩子 → 来自项目配置文件 → 信任
- **CLI**：`/hooks` 命令进入审核与信任入口

用户批的是**具体的 hook 定义**，不是仓库：`hooks.json` 改一个字，信任就失效，要重批。

**你不能做的**（这两条是硬约束，不要绕）：

- 不要直接编辑 `~/.codex/config.toml` 写入 `trusted_hash`；
- 不要使用任何绕过 hook 信任的启动参数。

理由：hook 可执行任意命令，自批等于取消这道安全控制。如果你认为自己确有合法途径，先说明理由并问用户，不要直接动手。

批准后**必须新开或恢复一次会话**——信任状态在会话启动时读取，当前会话不会自动生效。

## 4. 验证（逐项跑，把实际输出贴给用户）

### V1 读取侧能跑（不依赖信任状态）

```bash
echo '{"hook_event_name":"SessionStart","session_id":"verify"}' | /usr/bin/python3 journal/bin/context.py --agent codex
```

期望：一段 JSON，`additionalContext` 里含「协作流水（过程记录，不具备规范效力）」。这一步只证明脚本和路径没问题，**不代表 hook 已生效**。

### V2 每轮提醒够短

```bash
echo '{"hook_event_name":"UserPromptSubmit","session_id":"verify"}' | /usr/bin/python3 journal/bin/context.py --agent codex \
  | /usr/bin/python3 -c "import json,sys; print(len(json.load(sys.stdin)['hookSpecificOutput']['additionalContext']), '字符')"
```

期望：约 280–370 字符（提醒里含仓库绝对路径，路径长则偏多）。
**不要用 `wc -c` 量**——那数的是整段 JSON 的字节数，中文一字三字节，量出来的不是注入长度。

### V2b 会话中途追赶（长会话不必重开也能收到对方的新条目）

SessionStart 每会话只跑一次，所以对方在你会话进行中写的条目，靠它是拿不到的。每轮提醒的 hook 会顺带比对一次本会话水位，把新条目带进来。验证：

```bash
mkdir -p .journal-state
echo '{"hook_event_name":"SessionStart","session_id":"mid"}' | /usr/bin/python3 journal/bin/context.py --agent codex > /dev/null
/usr/bin/python3 journal/bin/append.py --agent claude --title "中途测试" --judgment "临时条目" > /dev/null
for i in 1 2; do
  echo '{"hook_event_name":"UserPromptSubmit","session_id":"mid"}' | /usr/bin/python3 journal/bin/context.py --agent codex \
    | /usr/bin/python3 -c "import json,sys; print('第 $i 轮带出新条目:', '本次会话期间新增' in json.load(sys.stdin)['hookSpecificOutput']['additionalContext'])"
done
```

期望：**第 1 轮 True，第 2 轮 False**——带出一次，水位前移，同一条不重复灌。验证完删掉这条测试条目和 `.journal-state/`。

### V3 写入侧能跑

```bash
/usr/bin/python3 journal/bin/append.py --agent codex --title "安装验证" --judgment "验证 append 可用，稍后删除"
```

期望：打印出 `journal/<今天>.md` 路径，文件里出现 `## [codex] HH:MM TZ — 安装验证`。**验证完删掉这条测试条目**。

### V4 空转会话不写信封

```bash
mkdir -p .journal-state/codex && git rev-parse --short HEAD > .journal-state/codex/idle.head
git status --porcelain           # 先确认工作区干净
echo '{"hook_event_name":"SessionEnd","session_id":"idle"}' | /usr/bin/python3 journal/bin/end.py --agent codex
```

期望：**没有任何新增信封**。这条坏掉的话，流水会被无内容条目淹没（实测出现过一天 25 条信封对 4 条语义），反过来挤占注入预算。验证完删掉 `.journal-state/`。

### V5 信任状态已写入（批准之后再跑）

```bash
grep -A1 "$(git rev-parse --show-toplevel)/.codex/hooks.json" ~/.codex/config.toml
```

期望：出现 `session_start`、`user_prompt_submit`、`session_end` 三条 `trusted_hash`。

### V6 真实会话注入（批准之后，新开会话）

新会话开头应当出现「协作流水」块，且：

```bash
ls .journal-state/codex/
```

期望：出现以本次 session id 命名的 `.head` 文件。**这两项同时成立，才算你这一侧真的生效**——V1 通过但这里失败，说明卡在信任审批，不是脚本问题。

### V7 兜底通道

```bash
/usr/bin/python3 journal/bin/peek.py --agent claude
```

期望：输出 Claude 在本项目的近 24h 记录摘要，或「近 1 天没有本项目的 claude 会话记录」。两者都算通过。

### V8 跨 Agent 握手（最终验收）

前七项只证明单边可用，这一项才证明「协作」成立：

1. 你在会话开头应当能看到 Claude 之前写的语义条目（如果它先装的）。看不到就说明 V6 没真的过，回去查。
2. 你写一条真实的语义条目回应它：
   ```bash
   /usr/bin/python3 journal/bin/append.py --agent codex --session-id "<本次会话 id>" \
     --title "Codex 侧生效验证" \
     --doing "完成信任审批并验证 SessionStart 注入" \
     --finding "<你实测到的结果，例如 hooks.state 三条 hash、注入块是否出现>" \
     --open "<留给对方的问题，没有就省略这行>"
   ```
3. 请用户开一次 Claude 会话，它应当在开头看到你这条——**看到即握手成功**。

## 5. 三条绝对不要做的事

1. **不要在 `.codex/hooks/` 下另写一份脚本。** 两侧共用 `journal/bin/*.py` 是硬要求：曾经两侧各写一份，半天内漂移出四个 bug，其中「游标把会话信封当成语义条目」会让对方的判断**永久不被读到且不报错**。要改行为就改共用实现，并同时验证两侧。
2. **不要自行批准 hook**（见第 3 节）。
3. **不要把半成品写进知识层。** 未验证的判断、被否决的路径进 `journal/`——那层不需要用户确认。

## 6. 报告

给用户一张表：V1–V8 各自的实际输出、卡在哪一步、协议两处填空最终填成什么、以及你对协议里任何**你认为执行不了或会拖慢你**的条款的异议。异议直接说，不要为了一致性附和——这套协议就是靠两侧互相挑毛病定稿的。

## 附：已知环境差异（实测）

- Codex 0.146.0-alpha.3.1 会把 SessionEnd hook 的 timeout 上限压到 3 秒，配更大值无效，因此模板里直接写 3。
- `~/.codex/sessions/` 是**跨项目全局目录**，`peek.py` 按每个 rollout 首行的 `session_meta.cwd` 过滤本项目记录——不要自己写 `find + cat` 去读，会把别的项目的会话一起读进来，而且体积极大。
