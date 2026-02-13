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
        send_url = "https://api.telegram.org/bot<BOT_TOKEN>/sendMessage"
        get_updates_url = "https://api.telegram.org/bot<BOT_TOKEN>/getUpdates"
        _telegram_warn(
            "teleslurm: failed to send message (e.g. timeout, 400, or network). "
            "Check BOT_TOKEN, THREAD, and CHAT_ID in your config.",
            extra_lines=[
                f"Raw: {err_raw}",
                "",
                "Re-send message (POST with chat_id and text):",
                f"  {send_url}",
                "",
                "Get chat_id from updates:",
                f"  {get_updates_url}",
            ],
        )
        return None


def get_server_load():
    """Get server CPU and memory usage (Linux/Unix systems)"""
    import subprocess
    try:
        cpu_cmd = "top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'"
        cpu_usage = subprocess.check_output(cpu_cmd, shell=True, text=True).strip()
        mem_cmd = "free -m | awk '/Mem:/ {print $3/$2 * 100}'"
        memory_usage = subprocess.check_output(mem_cmd, shell=True, text=True).strip()
        return {"cpu_usage": float(cpu_usage), "memory_usage": float(memory_usage)}
    except Exception as e:
        _telegram_warn(f"teleslurm: could not get server load: {e}")
        return {"cpu_usage": 0.0, "memory_usage": 0.0}


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
    message_parts = " ".join(args.message) if args.message else ""
    if slurm_id and message_parts:
        message_parts = f"{slurm_id} {message_parts}"
    elif slurm_id:
        message_parts = str(slurm_id)

    if args.status:
        load = get_server_load()
        message_parts = message_parts or ""
        message = (
            f"{message_parts}\n\nCTLab status 🐝\n"
            f"CPU: {load['cpu_usage']:.2f}%\nMemory: {load['memory_usage']:.2f}%"
        )
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
