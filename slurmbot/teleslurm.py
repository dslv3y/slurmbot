#!/usr/bin/env python3
# Usage: python -m slurmbot.teleslurm [-c CHAT] [-s] [-q] [--slurm-id ID] [message]
#
# -c CHAT: use config keys BOT_TOKEN_CHAT, CHAT_ID_CHAT, THREAD_CHAT (e.g. -c chat1 → BOT_TOKEN_chat1).
#          If omitted, uses BOT_TOKEN, CHAT_ID, THREAD from config.
# -s: include server status (CPU/memory).
# -q: include squeue output.
# --slurm-id: prepend job id to message; defaults to $SLURM_JOB_ID when run inside a Slurm job.
#
# Config: ~/.config/slurmbot/default.yaml (or SLURMBOT_CONFIG). Requires BOT_TOKEN, CHAT_ID, THREAD.
# How to get BOT_TOKEN: open Telegram → @BotFather → /newbot → follow prompts → paste the token into config.
# How to get CHAT_ID: message your bot, then open https://api.telegram.org/bot<BOT_TOKEN>/getUpdates and find "chat":{"id":...}.

import sys
import argparse
import os
import urllib.parse
import warnings
import yaml

try:
    import requests
except ImportError:
    requests = None

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/slurmbot/default.yaml")


def load_config(path=None):
    path = path or os.environ.get("SLURMBOT_CONFIG") or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def get_chat_config(config, chat_key):
    """Resolve BOT_TOKEN, CHAT_ID, THREAD for a chat key. chat_key '' or None = default."""
    if not config:
        return None, None, None
    if chat_key:
        suffix = "_" + chat_key
        token = config.get("BOT_TOKEN" + suffix) or config.get("BOT_TOKEN")
        chat_id = config.get("CHAT_ID" + suffix) or config.get("CHAT_ID")
        thread = config.get("THREAD" + suffix) if ("THREAD" + suffix) in config else config.get("THREAD", "0")
    else:
        token = config.get("BOT_TOKEN")
        chat_id = config.get("CHAT_ID")
        thread = config.get("THREAD", "0")
    return token, chat_id, thread


def _telegram_warn(msg, extra_lines=None):
    """Emit a warning for telegram/teleslurm issues (no hard errors)."""
    full = msg
    if extra_lines:
        full = full + "\n" + "\n".join(extra_lines)
    warnings.warn(full, UserWarning, stacklevel=2)


def send_telegram_message(text, BOT_TOKEN, CHAT_ID, THREAD):
    """Send a message via Telegram bot.
    message_thread_id is only for forum supergroups (chat_id like -100...); omit for private chats.
    """
    if not requests:
        _telegram_warn(
            "teleslurm: 'requests' is required. pip install requests",
            extra_lines=["Then retry sending the message."],
        )
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        thread = str(int(THREAD)) if THREAD else "0"
    except (ValueError, TypeError):
        thread = "0"
    chat_id_str = str(CHAT_ID).strip()
    is_supergroup = chat_id_str.startswith("-100")
    if thread == "0" or not is_supergroup:
        payload = {"chat_id": CHAT_ID, "text": text}
    else:
        payload = {"chat_id": CHAT_ID, "message_thread_id": int(thread), "text": text}
    try:
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        err_raw = str(e).replace(BOT_TOKEN, "<BOT_TOKEN>") if BOT_TOKEN else str(e)
        token = BOT_TOKEN or "<BOT_TOKEN>"
        get_updates_url = f"https://api.telegram.org/bot{token}/getUpdates"
        # Working link: GET with chat_id and text (open in browser to resend)
        msg_for_url = (text or "slurmbot test").strip() or "slurmbot test"
        send_url = (
            f"https://api.telegram.org/bot{token}/sendMessage"
            f"?chat_id={urllib.parse.quote(str(CHAT_ID))}&text={urllib.parse.quote(msg_for_url)}"
        )
        lines = [
            "teleslurm: failed to send message (e.g. timeout, 400, or network). "
            "Check BOT_TOKEN, THREAD, and CHAT_ID in your config.",
            f"Raw: {err_raw}",
            "",
            "Re-send message (open in browser; uses same chat_id and message):",
            f"  {send_url}",
            "",
            "Get chat_id from updates (open in browser or curl):",
            f"  {get_updates_url}",
        ]
        print("\n".join(lines), file=sys.stderr)
        return None


def _slurm_squeue_lines():
    """Return squeue -h output lines, or [] on failure."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["squeue", "-h"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return [l for l in out.strip().split("\n") if l.strip()]
    except Exception:
        return []


def _slurm_allocated_procs():
    """Total allocated CPUs across all jobs (squeue -h -o '%C'). Return 0 if unavailable."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["squeue", "-h", "-o", "%C"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        total = 0
        for line in out.strip().splitlines():
            line = line.strip()
            if line and line.isdigit():
                total += int(line)
        return total
    except Exception:
        return 0


def _slurm_allocated_gpus():
    """Total allocated GPUs from squeue GRES (e.g. gpu:2). Return 0 if unavailable."""
    import subprocess
    import re
    try:
        out = subprocess.check_output(
            ["squeue", "-h", "-o", "%b"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        total = 0
        for line in out.strip().splitlines():
            # Match gpu:N or gpu:type:N
            for m in re.finditer(r"gpu(?::[^:,]+)?:(\d+)", line, re.IGNORECASE):
                total += int(m.group(1))
        return total
    except Exception:
        return 0


def get_server_load():
    """Get server CPU and memory usage (Linux/Unix systems) and optional Slurm stats."""
    import subprocess
    try:
        cpu_cmd = "top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'"
        cpu_usage = subprocess.check_output(cpu_cmd, shell=True, text=True).strip()
        mem_cmd = "free -m | awk '/Mem:/ {print $3/$2 * 100}'"
        memory_usage = subprocess.check_output(mem_cmd, shell=True, text=True).strip()
        load = {"cpu_usage": float(cpu_usage), "memory_usage": float(memory_usage)}
    except Exception as e:
        _telegram_warn(f"teleslurm: could not get server load: {e}")
        load = {"cpu_usage": 0.0, "memory_usage": 0.0}
    load["squeue_len"] = len(_slurm_squeue_lines())
    load["slurm_procs"] = _slurm_allocated_procs()
    load["slurm_gpus"] = _slurm_allocated_gpus()
    return load


def handle_status_command(argv=None):
    parser = argparse.ArgumentParser(
        description="Send Telegram message (config: BOT_TOKEN, CHAT_ID, THREAD in ~/.config/slurmbot/default.yaml)"
    )
    parser.add_argument(
        "-c", "--chat",
        type=str,
        default="",
        metavar="CHAT",
        help="Chat key in config: use BOT_TOKEN_CHAT, CHAT_ID_CHAT, THREAD_CHAT (e.g. -c chat1)",
    )
    parser.add_argument("-s", "--status", action="store_true", help="Include server status")
    parser.add_argument("-q", "--squeue", action="store_true", help="Include squeue output")
    parser.add_argument("--slurm-id", type=str, default=None, metavar="ID", help="Slurm job ID to prepend (default: $SLURM_JOB_ID)")
    parser.add_argument("message", nargs="*", help="Message to send")
    args = parser.parse_args(argv)

    config_path = os.environ.get("SLURMBOT_CONFIG") or DEFAULT_CONFIG_PATH
    config = load_config(config_path)
    chat_key = (args.chat or "").strip()
    BOT_TOKEN, CHAT_ID, THREAD = get_chat_config(config, chat_key if chat_key else None)

    if not BOT_TOKEN or not CHAT_ID:
        _telegram_warn(
            "teleslurm: BOT_TOKEN and CHAT_ID must be set in config.",
            extra_lines=[
                f"Config path: {config_path}",
                "Get BOT_TOKEN: Telegram → @BotFather → /newbot → paste token in config.",
            ],
        )
        return None

    slurm_id = args.slurm_id or os.environ.get("SLURM_JOB_ID", "")
    if args.message:
        message_parts = " ".join(args.message)
    elif not sys.stdin.isatty():
        message_parts = sys.stdin.read().strip()
    else:
        message_parts = ""
    # Prepend job id only if not already present (e.g. "jobname finished (jobid)" or "jobname failed (jobid)" from trap)
    already_has_jobid = slurm_id and str(slurm_id) in message_parts and " (" in message_parts
    if slurm_id and message_parts and not message_parts.strip().startswith(str(slurm_id)) and not already_has_jobid:
        message_parts = f"{slurm_id} {message_parts}"
    elif slurm_id and not message_parts:
        message_parts = str(slurm_id)

    if args.status:
        load = get_server_load()
        message_parts = message_parts or ""
        lines = [
            f"{message_parts}\n\n🤖 Server status",
            f"💻 CPU: {load['cpu_usage']:.2f}%\n📝 Memory: {load['memory_usage']:.2f}%\n\n",
			f"🚶🚶🚶 squeue length: {load.get('squeue_len', 0)}",
        ]
        if load.get("slurm_procs_total", 0) > 0:
            avail = load.get("slurm_procs_available", 0)
            tot = load["slurm_procs_total"]
            lines.append(f"🌚 Avial. procs: {avail} / {tot}")
        elif load.get("slurm_procs", 0) > 0:
            lines.append(f"🌚 Slurm procs: {load['slurm_procs']} allocated")
        if load.get("slurm_gpus_total", 0) > 0:
            avail = load.get("slurm_gpus_available", 0)
            tot = load["slurm_gpus_total"]
            lines.append(f"🚀 Avial. GPUs: {avail} / {tot} (available / total)")
        elif load.get("slurm_gpus", 0) > 0:
            lines.append(f"🚀 Slurm GPUs: {load['slurm_gpus']} allocated")
        message = "\n".join(lines)
    else:
        message = message_parts or "No message provided"

    if args.squeue:
        import subprocess
        sq = subprocess.run("squeue", shell=True, text=True, capture_output=True)
        sq_clean = "".join(i.lstrip() for i in sq.stdout.split("         "))
        message += "\n\n" + sq_clean

    return send_telegram_message(message, BOT_TOKEN=BOT_TOKEN, CHAT_ID=CHAT_ID, THREAD=THREAD or "0")


if __name__ == "__main__":
    handle_status_command()
