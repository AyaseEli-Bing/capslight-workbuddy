# capslight（WorkBuddy 版）

[English](README.md) | **简体中文**

把 Caps Lock 键上那颗绿灯，变成 WorkBuddy 的实时状态指示灯。

WorkBuddy 干活时它慢闪，回合结束时它常亮，WorkBuddy 等你响应时它快闪。
它**不改变键盘的任何行为**——Caps Lock 始终是关的，打字始终是小写。

| 状态 | 灯光 | 时机 |
|---|---|---|
| `working` | 慢闪（0.7 秒一个周期，短促亮） | WorkBuddy 正在思考 / 正在跑工具 |
| `waiting` | 快闪（0.22 秒） | 它在等你：权限确认、提问 |
| `done` | 常亮 | 这一轮结束了 |
| `off` | 熄灭 | 会话已关闭 |

本仓库是 [insolowetrust/capslight](https://github.com/insolowetrust/capslight)（原版面向 Claude Code）
移植到 WorkBuddy 的版本。WorkBuddy 内部跑的是一个 CodeBuddy 系 agent，它的 hook 体系与 Claude Code
足够接近，可以做直译式移植——但有三处差异必须改，而且每一处都是真 bug 而非改名，详见
[移植要点](#移植要点)。

## 工作原理

`bin/capsled` 是一个 Swift 写的 IOKit 小工具，有两条点亮 LED 的路径：

1. **`hid`（默认）** —— 直接写键盘的 HID LED 元素
   （`kHIDPage_LEDs` / `kHIDUsage_LED_CapsLock`）。**它不碰修饰键状态**，
   所以灯在闪的同时你的打字仍然是小写。这正是不能图省事用下面那条路径的原因。
2. **`modifier`** —— `IOHIDSetModifierLockState`，作为兜底保留。更可靠，但它会**真的把 Caps Lock 打开**，
   于是每闪一次，你输入的字母就会跳成大写。

想知道你的硬件支持哪条路径：`make probe`。在 MacBook 内置键盘上两条都可用，
且**不需要 root，也不需要"输入监控"权限**。

`bin/caps-indicator` 是架在 `capsled` 之上的状态机。它负责持有后台闪烁进程及其 PID，
并把状态**按 WorkBuddy 会话分别记录**在 `~/.workbuddy/capsled/sessions/` 下。
同时开着多个会话时，LED 显示优先级最高的那个状态（`waiting` > `working` > `done` > `off`）——
所以其中一个会话结束，不会把另一个还在跑的会话的指示灯一起关掉。

## 安装

只需要 Xcode Command Line Tools（提供 `swiftc` 和 `python3`），没有其他依赖。

```sh
git clone https://github.com/AyaseEli-Bing/capslight-workbuddy.git
cd capslight-workbuddy
./install.sh
```

`install.sh` 一次做完：检查前置条件 → 编译二进制 → 探测硬件支持哪条后端 →
软链到 `~/.workbuddy/bin/` → 写入 hook → 最后跑一遍灯光的可视化测试。
加 `--no-test` 可跳过最后的测试。

你在 `~/.workbuddy/settings.json` 里**原有的 hook 不会被改动**——capslight 只追加自己的条目，
配置里的其他内容（包括 WorkBuddy 自己写进去的 `sandbox`、`enabledPlugins`、`claw` 等）保持原样。
首次改动前会备份一份到 `~/.workbuddy/settings.json.bak-capslight`。
重复执行是安全的：它替换自己的条目，而不是不断追加重复项。

如果你习惯用 make：`make install` 等效，只是省掉检查与测试。

**hook 不需要重启 WorkBuddy 就生效**——agent 运行时对 settings 文件挂了监视，
所以已打开会话的**下一次工具调用**就已经走新 hook 了。

事件映射：

| Hook 事件 | 状态 |
|---|---|
| `UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`PostToolUseFailure` | `working` |
| `SubagentStart`、`SubagentStop` | `working` |
| `PreCompact`、`PostCompact` | `working` |
| `PermissionDenied`、`ElicitationResult` | `working` |
| `PermissionRequest`、`Elicitation` | `waiting` |
| `Notification` | `waiting` 或 `done`，由 `notification_type` 决定 |
| `Stop`、`StopFailure` | `done` |
| `SessionEnd` | `off` |

hook 超时设为 5 秒，且全部以 `exit 0` 结束，因此**绝不可能阻塞或拒绝任何工具调用**——
最坏情况只是灯的颜色显示错了。

## 移植要点

与 Claude Code 原版相比有三处差异，每一处都是实际踩出来的 bug，而不是改个名字。

**1. hook payload 末尾没有换行符。** WorkBuddy 把 hook JSON 写进 stdin 后关闭管道，
但**最后一个字节是 `}`，不是 `\n`**。原版这样读 payload：

```bash
while IFS= read -r -t 1 line; do payload="$payload$line"; done
```

在 macOS 自带的 **bash 3.2** 上，这个循环会**把整个 payload 丢掉**：
最后一行没有换行符，`read` 会把内容赋给变量但同时返回非零，
于是循环条件不成立、循环体一次都不执行，什么都没追加。
结果是每个 hook 都拿到空 payload —— 没有 session id，也无法区分两种 `Notification`。
现在改成一次读完：

```bash
IFS= read -r -t 1 -d '' payload || true
```

`-t 1` 超时仍然保留：脚本有可能继承一个没人关闭的管道（被别的脚本包裹、cron、launchd），
那种情况下用 `cat` 会永久挂住。

**2. `Notification` 是同一个坑，但 WorkBuddy 会告诉你属于哪一种。**
在两边，`Notification` 都同时承担两件互不相干的事：真正需要你处理的事情，
以及紧跟 `Stop` 之后到来的"等你输入"。把它直接映射成 `waiting`，
会导致**每次任务结束、agent 安静下来时灯都开始快闪**。
原版的办法是在自由文本 `message` 里做关键词匹配；而 WorkBuddy 额外提供了 `notification_type`，
这才是应该拿来判断的字段：

| `notification_type` | 状态 |
|---|---|
| `permission_prompt`、`elicitation_dialog`、`agent_needs_input` | `waiting` |
| `idle_prompt`、`agent_completed` | `done` |
| 其他（例如登录后触发的 `auth_success`） | **保持不变** |

无法识别的类型**保持灯的状态不变**。在这里猜一个状态就等于发布一个错误状态，
而任何高于当前状态的错误猜测，都会表现为"灯在说谎，谎报 agent 在干什么"。
实测中 `auth_success` 确实会在会话进行到一半时出现，所以这个分支不是理论上的防御。

当 payload 里**完全没有** `notification_type` 时（更老的版本、或别的 agent 写了同一个 hook），
才回退到原版的关键词匹配。这个关键词列表刻意保持得很窄：
**不包含 `input`**，因为空闲消息的原文是 "waiting for your **input**"，
一旦匹配上就会把上面这个 bug 原样复现。

**3. 接了更多事件。** WorkBuddy 暴露的 hook 面比 Claude Code 更宽，
所以一些原本会"卡在旧状态"的情况现在被覆盖了：
工具调用失败仍然意味着这一轮在继续（`PostToolUseFailure`）；
子代理和上下文压缩都发生在主回合内部（`SubagentStart`、`SubagentStop`、`PreCompact`、`PostCompact`）；
你拒绝一次权限请求意味着 agent 带着现有条件继续干（`PermissionDenied`），
而不是让灯一直卡在"需要你"的快闪上。

## 日常检查

```sh
make test          # 带停顿地走一遍所有状态——盯着你的键盘看
make probe         # 看哪条后端可用
bin/capsled on     # 手动点亮
bin/capsled off
bin/caps-indicator status          # 是否静音，以及当前状态
bin/caps-indicator reset           # 紧急按钮：杀掉闪烁进程并把灯熄灭
```

如果完全没反应，先跑 `make probe`。如果两条后端都返回 `unavailable`，
说明这块键盘不肯把 LED 交出来（某些第三方蓝牙键盘会这样）。

如果灯亮了但显示的是**错的**状态，打开面包屑日志，看 hook 实际发来了什么：

```sh
touch ~/.workbuddy/capsled/debug         # 开始记录
tail -f ~/.workbuddy/capsled/debug.log   # 每个 hook 一行：参数、事件、payload
rm ~/.workbuddy/capsled/debug            # 停止记录（日志文件需自己删）
```

`CAPSLIGHT_DEBUG=1` 可以对单次调用达到同样效果。

## 调整闪烁

通过环境变量调整：

```
CAPS_WORKING_INTERVAL=0.7   CAPS_WORKING_DUTY=0.35
CAPS_WAITING_INTERVAL=0.22  CAPS_WAITING_DUTY=0.5
CAPS_BLINK_MAX_SECONDS=900  CAPS_SESSION_TTL_MINUTES=30
```

`DUTY` 是一个周期内灯亮的比例。0.35 是短促的点亮（余光扫到时更不打扰），0.5 是均匀闪。

强制指定后端：`bin/capsled --backend modifier on`。

## 临时关掉它

有时候你就是不想让键盘闪——录屏、开会、做演示。不用卸载：

```sh
caps-indicator disable   # 灯熄灭并保持熄灭
caps-indicator enable    # 下一次 hook 到来时恢复正常
caps-indicator status    # 是否静音，以及当前状态
```

hook 仍然挂着，只是立刻返回、什么都不做。这个开关是 `~/.workbuddy/capsled/disabled` 这个标志文件，
所以重启后依然有效，并且一次作用于所有会话。
在仓库目录里也可以用 `make disable` / `make enable` / `make status`。
静音期间 `caps-indicator reset` 依然可用——灯万一卡住，它是你的退路。

## 卸载

```sh
make uninstall
```

会熄灭灯、从 `~/.workbuddy/settings.json` 移除 hook、删除软链、清空状态目录。
你原来的配置仍然在 `~/.workbuddy/settings.json.bak-capslight`。

### 它到底动了什么

在运行一个会改你配置的脚本之前，这些值得先知道：

- `~/.workbuddy/settings.json` —— 按上面的表格，为每个事件追加一条 command hook，仅此而已。
  首次改动前会留一份原始副本 `.bak-capslight`；写入走"临时文件 + 原子重命名"，
  所以中途被打断也不会把你的配置截断。如果这文件不是合法 JSON，安装器会明确报错并**不做任何改动**。
  卸载时只移除自己的条目，随后把它清空的 event 键一并删掉。
- `~/.workbuddy/bin/` —— 两个指回本仓库的软链。
- `~/.workbuddy/capsled/` —— 闪烁进程的 PID、按会话的状态、以及静音标志。

设置 `WORKBUDDY_CONFIG_DIR` 后，两个安装脚本和指示灯脚本都会跟随它，与 agent 运行时保持一致。

不跑 root，不下载任何东西，不回传任何数据。

## 已知限制

- 闪烁过程中按真实的 Caps Lock 键，系统会覆盖 LED 状态。下一次闪会把它纠正回来，
  但你可能会看到某一拍乱掉。
- 默认权限模式下 WorkBuddy 会对大量工具调用索要权限，所以"快闪"会比较频繁。
  不喜欢的话，把该会话换成更宽松的权限模式。
- 如果 WorkBuddy 被 `kill -9`，`SessionEnd` 永远不会到达。两重"死人开关"兜底：
  闪烁进程在 15 分钟无人刷新后自行退出，会话记录在静默 30 分钟后被清理。
  会话活着时每个 hook 都会刷新自己的记录，所以正常情况下两者都不会触发。
  想立刻清干净就跑 `bin/caps-indicator reset`。这两个阈值可用
  `CAPS_BLINK_MAX_SECONDS` 和 `CAPS_SESSION_TTL_MINUTES` 调整。
- 外接键盘也会一起被驱动——指令是同时发给所有 HID 键盘的。

## 致谢

原版 [capslight](https://github.com/insolowetrust/capslight) 由 Max Solo 编写
（[t.me/aiukraine_wetrust](https://t.me/aiukraine_wetrust)）。
本次移植保留了原版的设计：Swift 的 LED 驱动、以及闪烁与优先级状态机均未改动。

MIT 许可。随便你怎么用。
