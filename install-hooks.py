#!/usr/bin/env python3
"""Add the capslight command hooks to ~/.workbuddy/settings.json, leaving existing hooks alone."""
import json
import os
import shutil
import sys
import tempfile

# WorkBuddy reads its user settings from <config dir>/settings.json, and honours
# WORKBUDDY_CONFIG_DIR — the agent runtime does, so the installer must too.
CONFIG_DIR = os.environ.get("WORKBUDDY_CONFIG_DIR") or os.path.expanduser("~/.workbuddy")
SETTINGS = os.path.join(CONFIG_DIR, "settings.json")
BACKUP = SETTINGS + ".bak-capslight"
CMD = os.path.join(CONFIG_DIR, "bin", "caps-indicator")
MARKER = "caps-indicator"

MAPPING = {
    # --- the agent is mid-turn ------------------------------------------------
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    # A failed tool call does not end the turn. Without this the LED would be left showing
    # whatever it showed before, and a long run of failures would look like a stall.
    "PostToolUseFailure": "working",
    # Subagents and teammates run inside the same turn as the main agent.
    "SubagentStart": "working",
    "SubagentStop": "working",
    # Compaction happens between tool calls, with the turn still running.
    "PreCompact": "working",
    "PostCompact": "working",
    # You denied a prompt: the agent carries on with what it already has.
    "PermissionDenied": "working",
    # You answered the agent's question: back to work.
    "ElicitationResult": "working",

    # --- it needs you ---------------------------------------------------------
    "PermissionRequest": "waiting",
    "Elicitation": "waiting",

    # WorkBuddy uses Notification for two unrelated things — a real permission prompt and
    # the idle "waiting for your input" that arrives right after Stop — so it is routed
    # through the notification_type-aware handler in caps-indicator.
    "Notification": "notify",

    # --- the turn is over -----------------------------------------------------
    "Stop": "done",
    # The turn ended badly. Still finished, and the LED must not keep blinking.
    "StopFailure": "done",

    # --- the conversation closed ---------------------------------------------
    "SessionEnd": "off",
}


def die(msg):
    print(f"install-hooks: {msg}", file=sys.stderr)
    sys.exit(1)


def load_settings():
    if not os.path.exists(SETTINGS):
        return {}
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        die(
            f"{SETTINGS} is not valid JSON (line {e.lineno}, column {e.colno}: {e.msg}).\n"
            "            Nothing was changed. Fix the file and re-run."
        )
    except OSError as e:
        die(f"cannot read {SETTINGS}: {e}")


def save_settings(settings):
    """Write via a temp file in the same directory, then rename — so an interrupted run
    can never leave the user with a truncated settings.json."""
    directory = os.path.dirname(SETTINGS)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".settings-capslight-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, SETTINGS)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


settings = load_settings()

# Keep one pristine copy of whatever was here before capslight ever touched it.
if os.path.exists(SETTINGS) and not os.path.exists(BACKUP):
    shutil.copy2(SETTINGS, BACKUP)

hooks = settings.setdefault("hooks", {})
if not isinstance(hooks, dict):
    die('"hooks" in settings.json is not an object — refusing to touch it')

added, refreshed = [], []
for event, state in MAPPING.items():
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        die(f'hooks["{event}"] is not a list — refusing to touch it')

    # drop earlier copies of our hook, so re-running stays idempotent
    before = len(entries)
    entries[:] = [
        e for e in entries
        if not any(MARKER in str(h.get("command", "")) for h in e.get("hooks", []))
    ]
    (refreshed if len(entries) != before else added).append(event)

    entries.append({
        "hooks": [{
            "type": "command",
            "command": f'"{CMD}" {state}',
            "timeout": 5,
        }]
    })

save_settings(settings)

print("settings:", SETTINGS)
print("added:   ", ", ".join(added) or "-")
print("updated: ", ", ".join(refreshed) or "-")
