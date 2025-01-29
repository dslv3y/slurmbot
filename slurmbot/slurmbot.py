#!/bin/python3

import subprocess
import os
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

	def run(self, cmd, dry=False, v=0, **kwargs):
		# Update parameters with defaults from config and provided kwargs
		params = self.config.copy()

		params.update(kwargs)  # kwargs override config defaults

		params["cmd"] = " " + cmd
		params["prefix"] = params["prefix"] + " && " if "prefix" in params.keys() and params["prefix"] else "" 
		params["conda"] = params["conda_prefix"] + " " + params["conda"] + " && " if "conda" in params.keys() and params["conda"] else "" 
		# params["dependency"] = f'--dependency=afterok:{params["dependency"]}' if params["dependency"] else ""
		# TODO add support for multiple dependencies
		params["reservation"] = f'--reservation={params["reservation"]}' if params["reservation"] else ""
		params["account"] = f'--account {params["account"]}' if params["account"] else ""
		params["partition"] = f'--partition {params["partition"]}' if params["partition"] else ""
		# TODO don't require logdir to be set in config
		# TODO don't require name to be set in config
		# TODO don't require mem and cpus to be set in config

		# Build sbatch command
		sbatch_cmd = f'''sbatch {params["account"]} {params["partition"]} {params["reservation"]} \
-o '{params["logdir"]}/%j.out' -e '{params["logdir"]}/%j.err' --job-name={params["name"]} \
-c {params["cpus"]} --mem={params["mem"]}G --time={params["time"]}:00:00 \
--parsable --wrap "/bin/bash -c '{params["prefix"]}{params["conda"]}{params["cmd"]}'"'''

		if dry:
			print(f"\033[33mDry run: Command not submitted. Full sbatch command:\033[0m\n{sbatch_cmd}")
			return

		# Execute the command if not dry run
		try:
			if v > 1:
				print(f"Submitting job with command: {sbatch_cmd}")
			result = subprocess.run(sbatch_cmd, shell=True, check=True, capture_output=True, text=True)
			job_id = result.stdout.strip()
			if v >= 1:
				print(job_id)

		except subprocess.CalledProcessError as e:
			print(f"Error: {e.stderr}")
