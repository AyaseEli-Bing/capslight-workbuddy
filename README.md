# capslight for WorkBuddy

**English** | [简体中文](README.zh-CN.md)

The green LED on your Caps Lock key as a live status indicator for WorkBuddy.

It blinks while WorkBuddy is working, goes solid when the turn is done, and blinks fast
when WorkBuddy is waiting on you. It changes nothing about how your keyboard behaves —
Caps Lock stays off and your typing stays lowercase.

| State | LED | When |
|---|---|---|
| `working` | slow blink (0.7s cycle, short flashes) | WorkBuddy is thinking / running tools |
| `waiting` | fast blink (0.22s) | it needs you: permission prompt, question |
| `done` | solid on | the turn finished |
| `off` | dark | the conversation closed |

This is a port of [insolowetrust/capslight](https://github.com/insolowetrust/capslight)
(written for Claude Code) to WorkBuddy. WorkBuddy runs a CodeBuddy-derived agent whose
hook system is close enough to be a straight port, with a few differences that turned out
to matter — see [Porting notes](#porting-notes).

## How it works

`bin/capsled` is a small IOKit utility in Swift. It has two ways to light the LED:

1. **`hid`** (default) — writes straight to the keyboard's HID LED element
   (`kHIDPage_LEDs` / `kHIDUsage_LED_CapsLock`). **It does not touch the modifier state**,
   so your typing stays lowercase while the light blinks. That's the whole reason not to
   use the simpler approach below.
2. **`modifier`** — `IOHIDSetModifierLockState`, kept as a fallback. More reliable, but it
   genuinely turns Caps Lock on, so text would jump to CAPS every time the LED flashes.

To see what your hardware supports: `make probe`. On a MacBook's built-in keyboard both
work, with no root and no Input Monitoring permission.

`bin/caps-indicator` is a state machine on top of `capsled`. It owns the background blink
process and its PID, and tracks state **per WorkBuddy session** in
`~/.workbuddy/capsled/sessions/`. With several conversations open, the LED shows the
highest-priority state (`waiting` > `working` > `done` > `off`) — so one conversation
finishing won't switch off the indicator for another that's still running.

## Install

All you need is the Xcode Command Line Tools (`swiftc`, `python3`). No other dependencies.

```sh
git clone https://github.com/AyaseEli-Bing/capslight-workbuddy.git
cd capslight-workbuddy
./install.sh
```

`install.sh` does the lot: checks prerequisites, builds the binary, probes which backend
your hardware supports, symlinks into `~/.workbuddy/bin/`, wires up the hooks, and finishes
with a visual test of the LED. Pass `--no-test` to skip that last step.

Your existing hooks in `~/.workbuddy/settings.json` are left alone — capslight adds its own
separate entries and the rest of your config (including everything WorkBuddy itself keeps
in there: `sandbox`, `enabledPlugins`, `claw`, …) stays as it was. A backup is written to
`~/.workbuddy/settings.json.bak-capslight` before the first change. Re-running is safe: it
replaces its own entries rather than duplicating them.

If you prefer make: `make install` does the same thing without the checks and the test.

**The hooks are picked up without restarting WorkBuddy** — the agent runtime watches the
settings file, so the next tool call in an open conversation already goes through them.

Event mapping:

| Hook | State |
|---|---|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure` | `working` |
| `SubagentStart`, `SubagentStop` | `working` |
| `PreCompact`, `PostCompact` | `working` |
| `PermissionDenied`, `ElicitationResult` | `working` |
| `PermissionRequest`, `Elicitation` | `waiting` |
| `Notification` | `waiting` or `done`, resolved from `notification_type` |
| `Stop`, `StopFailure` | `done` |
| `SessionEnd` | `off` |

Hooks have a 5 second timeout. All of them exit 0, so they can never block or deny a tool
call — the worst case if something goes wrong is that the LED shows the wrong colour.

## Porting notes

Three things differ from the Claude Code original, and each one was a real bug rather than
a cosmetic rename.

**1. The hook payload has no trailing newline.** WorkBuddy writes the hook JSON to stdin
and closes the pipe, but the last byte is `}` — not `\n`. The original read the payload
with `while IFS= read -r -t 1 line; do payload="$payload$line"; done`, and on the bash 3.2
that ships with macOS that loop **throws the entire payload away**: the unterminated final
line is read into the variable but the loop condition then fails, so nothing is appended.
Every hook silently saw an empty payload, which meant no session id and no way to tell the
two kinds of `Notification` apart. The reader is now a single
`IFS= read -r -t 1 -d '' payload || true`. The timeout still covers the case where the
script inherits a pipe nobody ever closes.

**2. `Notification` is the same trap, but WorkBuddy tells you which kind it is.** In both
agents, `Notification` fires for two unrelated things: something that genuinely needs your
attention, and the "waiting for your input" that lands right after `Stop`. Mapping it
straight to `waiting` meant the LED started blinking fast every time a task finished and
the agent went quiet. The original worked around this by matching keywords in the free-text
`message`. WorkBuddy additionally sends a `notification_type`, which is the right thing to
key off:

| `notification_type` | State |
|---|---|
| `permission_prompt`, `elicitation_dialog`, `agent_needs_input` | `waiting` |
| `idle_prompt`, `agent_completed` | `done` |
| anything else (e.g. `auth_success`, which fires after you log in) | **unchanged** |

An unrecognised type leaves the LED exactly as it is. Guessing here means publishing a
wrong state, and a wrong guess above the current state shows up as a light that lies about
what the agent is doing. In practice `auth_success` does fire mid-session, so this branch
is not theoretical.

When there is no `notification_type` at all — an older build, or a different agent writing
the same hook — it falls back to the original keyword match. That list is kept narrow on
purpose: `input` is *not* in it, because the idle message reads "waiting for your input"
and matching on that would reintroduce the exact bug above.

**3. More events are wired up.** WorkBuddy exposes a larger hook surface than Claude Code,
so a few states that used to be left stale are now covered: a failed tool call still means
the turn is running (`PostToolUseFailure`), subagents and compaction happen inside the main
turn (`SubagentStart`, `SubagentStop`, `PreCompact`, `PostCompact`), and you denying a
prompt means the agent carries on with what it has (`PermissionDenied`) rather than leaving
the LED stuck on the attention blink.

## Checking it

```sh
make test          # walks through every state with pauses — watch your keyboard
make probe         # which backend is available
bin/capsled on     # light it manually
bin/capsled off
bin/caps-indicator status          # muted or active, and the current state
bin/caps-indicator reset           # panic button: kill the blinker, turn the LED off
```

If nothing happens, start with `make probe`. If both backends come back `unavailable`,
that keyboard won't hand over its LED (happens on some third-party Bluetooth models).

If the LED lights up but shows the *wrong* thing, turn on the breadcrumb log and watch
what the hooks actually send:

```sh
touch ~/.workbuddy/capsled/debug         # start logging
tail -f ~/.workbuddy/capsled/debug.log   # one line per hook: argument, event, payload
rm ~/.workbuddy/capsled/debug            # stop (the log file stays until you delete it)
```

`CAPSLIGHT_DEBUG=1` does the same for a single run.

## Tuning the blink

Via environment variables:

```
CAPS_WORKING_INTERVAL=0.7   CAPS_WORKING_DUTY=0.35
CAPS_WAITING_INTERVAL=0.22  CAPS_WAITING_DUTY=0.5
CAPS_BLINK_MAX_SECONDS=900  CAPS_SESSION_TTL_MINUTES=30
```

`DUTY` is the fraction of each cycle the LED stays lit. 0.35 gives short flashes (less
distracting in peripheral vision), 0.5 gives an even blink.

To force a backend: `bin/capsled --backend modifier on`.

## Turning it off

Sometimes you don't want a blinking keyboard — a screen recording, a meeting, a demo.
No need to uninstall:

```sh
caps-indicator disable   # LED goes dark and stays dark
caps-indicator enable    # back to normal on the next hook
caps-indicator status    # muted or active, and the current state
```

The hooks stay wired; they just return immediately and do nothing. The switch is a flag
file at `~/.workbuddy/capsled/disabled`, so it survives restarts and applies to every
conversation at once. `make disable` / `make enable` / `make status` do the same from the
checkout. `caps-indicator reset` keeps working while muted — it's the way out if the LED
ever gets stuck.

## Uninstall

```sh
make uninstall
```

Turns the LED off, removes the hooks from `~/.workbuddy/settings.json`, deletes the
symlinks and clears the state directory. Your original settings are still in
`~/.workbuddy/settings.json.bak-capslight`.

### What it touches

Worth knowing before you run a script that edits your config:

- `~/.workbuddy/settings.json` — adds one command hook per event listed above, nothing
  else. A pristine copy is kept as `.bak-capslight` before the first change, and writes go
  through a temp file plus atomic rename, so an interrupted run can't truncate your
  settings. If the file isn't valid JSON, the installer says so and changes nothing.
  Uninstalling removes only its own entries, then drops the event keys it left empty.
- `~/.workbuddy/bin/` — two symlinks pointing back at this checkout.
- `~/.workbuddy/capsled/` — the blinker's PID, per-session state and the mute flag.

Set `WORKBUDDY_CONFIG_DIR` and both the installers and the indicator follow it, matching
what the agent runtime does.

Nothing runs as root, nothing is downloaded, nothing phones home.

## Known limitations

- Pressing the real Caps Lock key mid-blink makes the system overwrite the LED state. The
  next flash puts it back, but you may see one beat go out of step.
- WorkBuddy asks for permission on a lot of tool calls in the default permission mode, so
  the fast blink is common while you're being asked. Switch the conversation to a
  permissive mode if you'd rather it didn't.
- If WorkBuddy is killed with `kill -9`, `SessionEnd` never fires. Two dead-man's switches
  cover that: the blinker gives up after 15 minutes without anyone refreshing it, and a
  session record is dropped after 30 minutes of silence. A live session touches its record
  on every hook, so neither fires in normal use. To clear it immediately, run
  `bin/caps-indicator reset`. Both are tunable via `CAPS_BLINK_MAX_SECONDS` and
  `CAPS_SESSION_TTL_MINUTES`.
- External keyboards are driven too — the command goes to every HID keyboard at once.

## Credits

Original [capslight](https://github.com/insolowetrust/capslight) by Max Solo
([t.me/aiukraine_wetrust](https://t.me/aiukraine_wetrust)). This port to WorkBuddy keeps
the original design, and the Swift LED driver and the blink/priority state machine are
unchanged.

MIT. Do whatever you like with it.
