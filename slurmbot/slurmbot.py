#!/bin/python3

import subprocess
import os
import shlex
import yaml

class SlurmBot:
	def __init__(self, config_path=None):
		# Default to config file in ~/.config/slurmbot/default.yaml
		self.config_path = config_path or os.path.expanduser("~/.config/slurmbot/default.yaml")
		self.config = self.load_config()

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

		params["cmd"] = " " + cmd
		params["prefix"] = params.get("prefix", "") + " && " if params.get("prefix") else ""
		params["conda"] = params.get("conda_prefix", "") + " " + params.get("conda", "") + " && " if params.get("conda") else ""
		params["reservation"] = f'--reservation={params["reservation"]}' if params.get("reservation") else ""
		params["account"] = f'--account {params["account"]}' if params.get("account") else ""
		params["partition"] = f'--partition {params["partition"]}' if params.get("partition") else ""
		params["logdir"] = os.path.expanduser(params.get("logdir", "."))
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
			trap_body = (
				"ec=$?; errf=\"${SLURMBOT_LOGDIR:-$HOME/logs}/${SLURM_JOB_ID}.err\"; "
				"if [ $ec -ne 0 ]; then "
				"errtext=$(head -5 \"$errf\" 2>/dev/null); "
				"n=$(wc -l < \"$errf\" 2>/dev/null || echo 0); "
				"[ \"$n\" -gt 5 ] 2>/dev/null && errtext=\"$errtext\"$'\\n'\"...\"; "
				"printf \"%s failed (%s)\\n\\n%s\" \"$SLURMBOT_JOB_NAME\" \"$SLURM_JOB_ID\" \"$errtext\" | python -m slurmbot.teleslurm -s; "
				"else sflag=\"\"; [ \"$SLURMBOT_TELESLURM_STATUS\" = \"1\" ] && sflag=\"-s\"; python -m slurmbot.teleslurm $sflag \"${SLURMBOT_JOB_NAME} finished (${SLURM_JOB_ID})\"; fi"
			)
			trap_part = f"{export_logdir}{export_jobname}{export_chat}{export_status}trap {sq}{trap_body}{sq} EXIT; "

		wrap_script = f"/bin/bash -c '{trap_part}{params["prefix"]}{params["conda"]}{params["cmd"]}'"

		# Build sbatch argv so --wrap gets one argument (avoids shell quoting issues)
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
			"--wrap", wrap_script,
		])
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
