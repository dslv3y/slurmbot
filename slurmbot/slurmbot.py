#!/bin/python3

import subprocess
import os
import shlex
import sys
import time
import yaml

class SlurmBot:
	def __init__(self, config_path=None, mode="slurm"):
		# Default to config file in ~/.config/slurmbot/default.yaml
		# mode: "slurm" (sbatch) or "screen" (detached screen session)
		self.config_path = config_path or os.path.expanduser("~/.config/slurmbot/default.yaml")
		self.config = self.load_config()
		self.mode = mode if mode in ("slurm", "screen") else "slurm"

	def load_config(self):
		if os.path.exists(self.config_path):
			try:
				with open(self.config_path, 'r') as file:
					return yaml.safe_load(file)
			except yaml.YAMLError:
				print("Error loading config file. Please check the format.")
			else:
				print(f"Config file not found at {self.config_path}.")

	def _send_teleslurm(self, message, chat_key=None, include_status=False):
		"""Send a message via teleslurm (telegram). chat_key=None uses default config; else BOT_TOKEN_<chat_key>, etc.
		If include_status=True, append server status (CPU/memory) to the message.
		"""
		from slurmbot.teleslurm import load_config, get_chat_config, send_telegram_message, get_server_load
		config = load_config(self.config_path) or self.config
		BOT_TOKEN, CHAT_ID, THREAD = get_chat_config(config, chat_key)
		if not BOT_TOKEN or not CHAT_ID:
			return None
		if include_status:
			load = get_server_load()
			lines = [
				message,
				"\n\n 🤖  Server status",
				f"💻 CPU: {load['cpu_usage']:.2f}%\n📝 Memory: {load['memory_usage']:.2f}%\n\n\n",
				f"🚶🚶🚶 squeue length: {load.get('squeue_len', 0)}",
			]
			# CPUs: idle/total, or allocated fallback
			if load.get("slurm_procs_total", 0) > 0:
				idle = load.get("slurm_procs_idle", 0)
				tot = load["slurm_procs_total"]
				used=tot-idle
				lines.append(f"🌚 CPUs used/total: {used} / {tot}")
			elif load.get("slurm_procs_allocated", 0) > 0:
				lines.append(f"🌚 CPUs allocated: {load['slurm_procs_allocated']}")
			# GPUs: allocated/total
			if load.get("slurm_gpus_total", 0) > 0:
				alloc_g = load.get("slurm_gpus_allocated", 0)
				tot_g = load["slurm_gpus_total"]
				lines.append(f"🚀 GPUs used/total: {alloc_g} / {tot_g}")
			elif load.get("slurm_gpus_allocated", 0) > 0:
				lines.append(f"🚀 GPUs allocated: {load['slurm_gpus_allocated']}")
			message = "\n".join(lines)
		return send_telegram_message(message, BOT_TOKEN=BOT_TOKEN, CHAT_ID=CHAT_ID, THREAD=THREAD or "0")

	def run(self, cmd, dry=False, v=0, teleslurm=False, teleslurm_chat=None, teleslurm_status=False, **kwargs):
		# Update parameters with defaults from config and provided kwargs
		params = self.config.copy() if self.config else {}

		params.update(kwargs)

		if "dependency" in params.keys() and params["dependency"]:
			if isinstance(params["dependency"], list):
				params["dependency"] = [str(d) for d in params["dependency"]]
				params["dependency"] = ",".join(params["dependency"])
			params["dependency"] = f'--dependency=afterok:{params["dependency"]}'
		else:
			params["dependency"] =""

		# Escape single quotes in cmd so the wrap script stays valid inside outer single quotes
		params["cmd"] = " " + cmd.replace("'", "'\\''")
		# Build prefix/conda in a safe way for comments/newlines: always terminate with '; ' (not '&&'),
		# so there is never a dangling '&&' before '#...' or at a line break.
		params["prefix"] = (params.get("prefix", "") + "; ") if params.get("prefix") else ""
		if params.get("conda"):
			base = params.get("conda_prefix", "")
			conda_part = (base + " " if base else "") + params["conda"]
			params["conda"] = conda_part + "; "
		else:
			params["conda"] = ""
		params["reservation"] = f'--reservation={params["reservation"]}' if params.get("reservation") else ""
		params["account"] = f'--account {params["account"]}' if params.get("account") else ""
		params["partition"] = f'--partition {params["partition"]}' if params.get("partition") else ""
		# Default logdir: screen mode uses ~/logs so logs are predictable; slurm uses config or "."
		params["logdir"] = os.path.expanduser(params.get("logdir", "~/logs" if self.mode == "screen" else "."))
		params["time"] = params.get("time", 24)
		params["cpus"] = params.get("cpus", 4)
		params["mem"] = params.get("mem", 4)
		params["name"] = params["name"] if params.get("name") else cmd.split(" ")[0]

		# Optional teleslurm: trap EXIT sends "finished" or "failed" (with first 5 lines of .err + status).
		trap_part = ""
		if teleslurm and not dry:
			logdir_esc = params["logdir"].replace("'", "'\\''")
			jobname_esc = params["name"].replace("'", "'\\''")
			export_logdir = f"export SLURMBOT_LOGDIR='{logdir_esc}'; "
			export_jobname = f"export SLURMBOT_JOB_NAME='{jobname_esc}'; "
			chat_val = (teleslurm_chat or "").strip()
			export_chat = f"export SLURMBOT_TELESLURM_CHAT='{chat_val.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'; " if chat_val else ""
			export_status = "export SLURMBOT_TELESLURM_STATUS=1; " if teleslurm_status else "export SLURMBOT_TELESLURM_STATUS=0; "
			# Trap: on failure send "{job_name} failed ({job_id})" + first 5 lines of .err + "..." + status; else "{job_name} finished ({job_id})"
			sq = "'\\''"
			# Use space instead of newline so trap body stays on one line (avoids multi-line quote parse issues in screen/bash -c)
			trap_body = (
				"ec=$?; rid=\"${SLURM_JOB_ID:-$SLURMBOT_SESSION_ID}\"; errf=\"${SLURMBOT_LOGDIR:-$HOME/logs}/${rid}.err\"; "
				"if [ $ec -ne 0 ]; then "
				"errtext=$(head -5 \"$errf\" 2>/dev/null); "
				"n=$(wc -l < \"$errf\" 2>/dev/null || echo 0); "
				"[ \"$n\" -gt 5 ] 2>/dev/null && errtext=\"$errtext\" \"...\"; "
				"printf \"%s failed (%s)\\n\\n%s\" \"$SLURMBOT_JOB_NAME\" \"$rid\" \"$errtext\" | python -m slurmbot.teleslurm -s; "
				"else sflag=\"\"; [ \"$SLURMBOT_TELESLURM_STATUS\" = \"1\" ] && sflag=\"-s\"; python -m slurmbot.teleslurm $sflag \"${SLURMBOT_JOB_NAME} finished (${rid})\"; fi"
			)
			trap_part = f"{export_logdir}{export_jobname}{export_chat}{export_status}trap {sq}{trap_body}{sq} EXIT; {sq}"
			wrap_content = f"{trap_part}{params['prefix']}{params['conda']}{params['cmd']}"
		else:
			wrap_content = f"{params['prefix']}{params['conda']}{params['cmd']}"

		wrap_script = f"/bin/bash -c '{wrap_content}'"

		if self.mode == "screen":
			return self._run_screen(wrap_script, params, dry, v, teleslurm, teleslurm_chat, teleslurm_status)

		# Slurm mode: write a real script file and submit it with sbatch instead of using --wrap.
		# This avoids very complex quoting in --wrap and makes the script identical to what screen runs.
		script_path = None
		script_contents = ""
		logdir = params["logdir"]
		os.makedirs(logdir, exist_ok=True)

		# Build script: shebang + optional teleslurm trap + prefix/conda/cmd.
		lines = ["#!/bin/bash"]
		if teleslurm and not dry:
			# Same trap semantics as for screen, but encoded directly for a script file using double quotes.
			trap_body_inner = (
				"ec=$?; rid=\"${SLURM_JOB_ID:-$SLURMBOT_SESSION_ID}\"; errf=\"${SLURMBOT_LOGDIR:-$HOME/logs}/${rid}.err\"; "
				"if [ $ec -ne 0 ]; then "
				"errtext=$(head -5 \"$errf\" 2>/dev/null); n=$(wc -l < \"$errf\" 2>/dev/null || echo 0); "
				"[ \"$n\" -gt 5 ] 2>/dev/null && errtext=\"$errtext\" \"...\"; "
				"printf \"%s failed (%s)\\n\\n%s\" \"$SLURMBOT_JOB_NAME\" \"$rid\" \"$errtext\" | python -m slurmbot.teleslurm -s; "
				"else sflag=\"\"; [ \"$SLURMBOT_TELESLURM_STATUS\" = \"1\" ] && sflag=\"-s\"; python -m slurmbot.teleslurm $sflag \"${SLURMBOT_JOB_NAME} finished (${rid})\"; fi"
			)
			jobname_dq = params["name"].replace('"', r'\"')
			chat_val = (teleslurm_chat or "").strip()
			chat_dq = chat_val.replace('"', r'\"') if chat_val else ""
			lines.append(f'SLURMBOT_LOGDIR="{logdir}"; export SLURMBOT_LOGDIR')
			lines.append(f'SLURMBOT_JOB_NAME="{jobname_dq}"; export SLURMBOT_JOB_NAME')
			if chat_dq:
				lines.append(f'SLURMBOT_TELESLURM_CHAT="{chat_dq}"; export SLURMBOT_TELESLURM_CHAT')
			status_val = "1" if teleslurm_status else "0"
			lines.append(f"SLURMBOT_TELESLURM_STATUS={status_val}; export SLURMBOT_TELESLURM_STATUS")
			# Escape inner double quotes for the double-quoted trap string
			lines.append(f'trap "{trap_body_inner.replace(chr(34), chr(92) + chr(34))}" EXIT')

		# Command line: reuse prefix/conda, but for the file use literal single quotes (undo the '\'' escaping).
		cmd_file = params["cmd"].replace("'\\''", "'")
		lines.append(f"unset SLURM_EXPORT_ENV; {params['prefix']}{params['conda']}{cmd_file}")
		script_contents = "\n".join(lines) + "\n"

		if not dry:
			# Use job-name + timestamp as script filename; logs still go to logdir/%j.{out,err}.
			import time as _time
			script_basename = f"{params['name']}_{int(_time.time())}.sh"
			script_path = os.path.join(logdir, script_basename)
			with open(script_path, "w") as f:
				f.write(script_contents)

		# Build sbatch argv to submit the script file.
		sbatch_argv = ["sbatch"]
		if params.get("account"):
			sbatch_argv.extend(params["account"].split(maxsplit=1))
		if params.get("partition"):
			sbatch_argv.extend(params["partition"].split(maxsplit=1))
		if params.get("reservation"):
			sbatch_argv.extend(params["reservation"].split(maxsplit=1))
		if params.get("dependency"):
			sbatch_argv.append(params["dependency"])
		sbatch_argv.extend([
			"-o", f"{params['logdir']}/%j.out",
			"-e", f"{params['logdir']}/%j.err",
			"--job-name", params["name"],
			"-c", str(params["cpus"]),
			"--mem", f"{params['mem']}G",
			"--time", f"{params['time']}:00:00",
			"--parsable",
		])
		if not dry and script_path:
			sbatch_argv.append(script_path)
		else:
			# For dry run, just show a placeholder path.
			sbatch_argv.append("<script_path>")

		sbatch_cmd = " ".join(shlex.quote(a) for a in sbatch_argv)

		if dry:
			print(f"\033[33mDry run: Command not submitted.\033[0m")
			print(sbatch_cmd)
			print(f"\033[33mWrap script:\033[0m\n  {wrap_script}")
			return

		try:
			if v > 1:
				print(f"Submitting job with command: {sbatch_cmd}")
			result = subprocess.run(sbatch_argv, check=True, capture_output=True, text=True)
			job_id = result.stdout.strip()
			if teleslurm and job_id:
				self._send_teleslurm(f"{params['name']} started ({job_id})", chat_key=teleslurm_chat, include_status=teleslurm_status)
			return job_id

		except subprocess.CalledProcessError as e:
			print(f"Error: {e.stderr}")

	def _run_screen(self, wrap_script, params, dry, v, teleslurm, teleslurm_chat, teleslurm_status):
		"""Run the same wrap script in a detached screen session. Returns session_id.
		Logs go to logdir/<session_id>.out and .err. Session exits when the command finishes (short commands won't show in screen -ls).
		"""
		import re
		session_id = re.sub(r"[^a-zA-Z0-9_-]", "_", params["name"]) + "_" + str(int(time.time()))
		logdir = params["logdir"]
		prefix_len = len("/bin/bash -c '")
		if wrap_script.startswith("/bin/bash -c '") and wrap_script.endswith("'"):
			body = wrap_script[prefix_len:-1]
		else:
			body = wrap_script
		if not dry:
			logdir_esc = logdir.replace("'", "'\\''")
			lead = (
				f"export SLURMBOT_SESSION_ID='{session_id}'; export SLURMBOT_LOGDIR='{logdir_esc}'; "
				f"mkdir -p \"$SLURMBOT_LOGDIR\"; exec >\"$SLURMBOT_LOGDIR/$SLURMBOT_SESSION_ID.out\" 2>\"$SLURMBOT_LOGDIR/$SLURMBOT_SESSION_ID.err\"; "
			)
			# Build script valid for a file: use double-quoted trap so no '\'' escaping issues
			if teleslurm and body.count("trap ") == 1:
				trap_body_inner = (
					"ec=$?; rid=\"${SLURM_JOB_ID:-$SLURMBOT_SESSION_ID}\"; errf=\"${SLURMBOT_LOGDIR:-$HOME/logs}/${rid}.err\"; "
					"if [ $ec -ne 0 ]; then "
					"errtext=$(head -5 \"$errf\" 2>/dev/null); n=$(wc -l < \"$errf\" 2>/dev/null || echo 0); "
					"[ \"$n\" -gt 5 ] 2>/dev/null && errtext=\"$errtext\" \"...\"; "
					"printf \"%s failed (%s)\\n\\n%s\" \"$SLURMBOT_JOB_NAME\" \"$rid\" \"$errtext\" | python -m slurmbot.teleslurm -s; "
					"else sflag=\"\"; [ \"$SLURMBOT_TELESLURM_STATUS\" = \"1\" ] && sflag=\"-s\"; python -m slurmbot.teleslurm $sflag \"${SLURMBOT_JOB_NAME} finished (${rid})\"; fi"
				)
				chat_val = (teleslurm_chat or "").strip()
				export_chat_file = f"export SLURMBOT_TELESLURM_CHAT='{chat_val.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'; " if chat_val else ""
				trap_part_file = (
					f"export SLURMBOT_LOGDIR='{logdir_esc}'; export SLURMBOT_JOB_NAME='{params['name'].replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'; "
					+ export_chat_file
					+ f"export SLURMBOT_TELESLURM_STATUS={1 if teleslurm_status else 0}; "
					f'trap "{trap_body_inner.replace(chr(34), chr(92)+chr(34))}" EXIT; '
				)
				# params["cmd"] is escaped for wrap_script ('\''); for file script use literal quotes
				cmd_file = params["cmd"].replace("'\\''", "'")
				inner = lead + trap_part_file + params["prefix"] + params["conda"] + cmd_file
			else:
				inner = lead + body
			script_path = os.path.join(logdir, f"{session_id}.sh")
			os.makedirs(logdir, exist_ok=True)
			with open(script_path, "w") as f:
				f.write(inner)
			screen_argv = ["screen", "-dmS", session_id, "/bin/bash", script_path]
		else:
			inner = body
			screen_argv = ["screen", "-dmS", session_id, "/bin/bash", "-c", inner]
		screen_cmd_str = " ".join(shlex.quote(a) for a in screen_argv)
		if dry:
			print("\033[33mDry run: Command not submitted.\033[0m")
			print(screen_cmd_str)
			print(f"\033[33mScreen session would be:\033[0m  {session_id}")
			print(f"\033[33mLogs would be:\033[0m  {logdir}/{session_id}.out, {logdir}/{session_id}.err")
			return
		try:
			os.makedirs(logdir, exist_ok=True)
			if v > 1:
				print(f"Starting screen: {screen_cmd_str}")
			result = subprocess.run(screen_argv, capture_output=True, text=True)
			if result.returncode != 0:
				print(f"Error: screen exited with {result.returncode}", file=sys.stderr)
				if result.stderr:
					print(result.stderr, file=sys.stderr)
				if result.stdout:
					print(result.stdout, file=sys.stderr)
				return None
			if teleslurm:
				self._send_teleslurm(f"{params['name']} started ({session_id})", chat_key=teleslurm_chat, include_status=teleslurm_status)
			if v:
				print(f"Screen session {session_id} started. Logs: {logdir}/{session_id}.out, {logdir}/{session_id}.err (session exits when command finishes)")
			return session_id
		except Exception as e:
			print(f"Error starting screen: {e}")
