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
				exit(1)
		else:
			print(f"Config file not found at {self.config_path}.")
			exit(1)

	def run(self, cmd, dry=False, v=0, **kwargs):
		# Update parameters with defaults from config and provided kwargs
		params = self.config.copy()
		params.update(kwargs)  # kwargs override config defaults

		# Build sbatch command
		sbatch_cmd = f"sbatch --account {params['account']} --partition {params['partition']} \
--reservation {params['reservation']} --cpus-per-task {params['cpus']} --mem {params['mem']}G \
--time {params['time']} --job-name {params['name']} -o {params['logdir']}/%j.out -e {params['logdir']}/%j.err \
--wrap 'source {params['conda_prefix']} {params['conda']} && {cmd}'"

		if dry:
			print(f"\033[33mDry run: Command not submitted. Full sbatch command:\033[0m\n{sbatch_cmd}")
			return

		# Execute the command if not dry run
		try:
			result = subprocess.run(sbatch_cmd, shell=True, check=True, capture_output=True, text=True)
			job_id = result.stdout.strip()
			if v == 1:
				print(job_id)
			elif v > 1:
				print(f"{job_id}, {cmd}")
		except subprocess.CalledProcessError as e:
			print(f"Error: {e.stderr}")
