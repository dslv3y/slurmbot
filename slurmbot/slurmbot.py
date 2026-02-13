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
			if load.get("slurm_procs_total", 0) > 0:
				avail = load.get("slurm_procs_available", 0)
				tot = load["slurm_procs_total"]
				lines.append(f"🌚 Avial. procs: {avail} / {tot}")
			elif load.get("slurm_procs", 0) > 0:
				lines.append(f"🌚 Avial. procs: {load['slurm_procs']} allocated")
			if load.get("slurm_gpus_total", 0) > 0:
				avail = load.get("slurm_gpus_available", 0)
				tot = load["slurm_gpus_total"]
				lines.append(f"🚀 Avial. GPUs: {avail} / {tot} (available / total)")
			elif load.get("slurm_gpus", 0) > 0:
				lines.append(f"🚀 Avial. GPUs: {load['slurm_gpus']} allocated")
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

		# Optional teleslurm: notify when job finishes. Use trap EXIT so "finished" is sent even on failure/kill.
		# (%j is only for sbatch -o/-e; inside the wrap we use SLURM_JOB_ID.)
		# teleslurm.py will auto-prepend SLURM_JOB_ID from env, so we just send "finished".
		trap_part = ""
		if teleslurm and not dry:
			sq = "'\\''"  # single-quote escape for outer -c '...'
			status_flag = " -s" if teleslurm_status else ""
			if teleslurm_chat not in (None, ""):
				esc = (teleslurm_chat or "").replace("'", "'\\''")
				trap_cmd = f"python -m slurmbot.teleslurm -c '{esc}'{status_flag} finished"
			else:
				trap_cmd = f"python -m slurmbot.teleslurm{status_flag} finished"
			trap_part = f"trap {sq}{trap_cmd}{sq} EXIT; "

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
				self._send_teleslurm(f"{job_id} started", chat_key=teleslurm_chat, include_status=teleslurm_status)
			return job_id

		except subprocess.CalledProcessError as e:
			print(f"Error: {e.stderr}")
