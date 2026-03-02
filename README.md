## SlurmBot 🤖
Simple tool to wrap and execute `sbatch` commands from `python` scripts or `Jupyter Notebooks` with `conda` envs and config files. Less mess, more reproducibility and security (if published to GitHub, for instance).
_Based on [jbatch](https://pypi.org/project/jbatch/)_.

- ⚙️ **Config Files**: Create config files in `YAML` format and reuse them. Make a `default.yaml` in `~/.config/slurmbot/default.yaml`
- 🐍 **Python Variables**: Easily integrate Python variables into your Slurm job commands.
- 🛠️ **Conda**: Activate Conda environments with the `conda` property and use _conda\_prefix_ like "conda activate &&" in the config yaml – see [example config file](./default.yaml). Also can use _prefix_ to run smth before executing each job.
- 📱 **Telegram (teleslurm)**: Optional notifications to Telegram when jobs start/finish. Uses `BOT_TOKEN`, `CHAT_ID`, `THREAD` (and per-chat keys like `BOT_TOKEN_chat1`, `CHAT_ID_chat1`, `THREAD_chat1`) in the config.

## Installation
`pip install slurmbot`

## Example
```python
from slurmbot.slurmbot import SlurmBot 
sb = SlurmBot() # using default yaml from ~/.config/slurmbot/default.yaml, if exists OR specify path to config
samples = ["SRR000001", "SRR000002"]
for sample in samples:
	sb.run(f"fasterq-dump {sample}", conda="ngs", mem=4, cpus=4, dry=True, v=2, time=48) # 🚨 time in hours!
```

With Telegram (teleslurm) — message "started" / "finished" to a chat:
```python
from slurmbot.slurmbot import SlurmBot
sb = SlurmBot()
sb.run(f"ls -la", dry=False, mem=4, cpus=4, v=2, time=48, teleslurm=True) # will sent messages upon the start, finish and errors
```

CLI: 
```bash
python -m slurmbot.teleslurm -s -c chat1 "MESSAGE" # 🚨 do not forget to specify chat1 settings in config if use -c
```

## Config (YAML)

Minimal example: [default.yaml](./default.yaml). Put your config in `~/.config/slurmbot/default.yaml`.

## Options

- **SlurmBot(config_path=None)**: Create a bot bound to a YAML config file. If `config_path` is omitted, SlurmBot tries to use `~/.config/slurmbot/default.yaml` when it exists.
- **Config keys (YAML, also used as defaults for `sb.run`)**:
  - **account / partition / reservation**: Passed through to `sbatch` (`--account`, `--partition`, `--reservation`).
  - **cpus / mem / time**: Default CPU cores, memory (GB), and walltime (hours) for jobs.
  - **logdir**: Directory for `sbatch` logs (`logdir/%j.out`, `logdir/%j.err`).
  - **name**: Default Slurm job name (falls back to the first token of `cmd` if empty).
  - **prefix**: Shell snippet run before each job (e.g. `unset SLURM_EXPORT_ENV`).
  - **conda_prefix / conda**: Activate a Conda env before running the command.
- **`sb.run(cmd, **kwargs)` main options**:
  - **cmd**: Shell command to execute via `sbatch` (wrapped in `/bin/bash -c`).
  - **cpus, mem, time, logdir, account, partition, reservation, name**: Override the corresponding config keys per-call.
  - **dependency**: Slurm dependency; can be a single job id or a list, turned into `--dependency=afterok:<ids>`.
  - **dry**: If `True`, print the `sbatch` command without submitting.
  - **v**: Verbosity; `v > 1` prints the full `sbatch` command before submitting.
  - **conda / prefix**: Per-call overrides for environment/command prefix (merged with config values).
  - **teleslurm**: If `True`, send Telegram messages when the job starts, finishes, and on errors.
  - **teleslurm_status**: If `True`, attach CPU/memory and Slurm queue/CPU/GPU stats to Telegram messages.
  - **teleslurm_chat**: Optional chat key (e.g. `"Chat1"`), using `BOT_TOKEN_Chat1`, `CHAT_ID_Chat1`, `THREAD_Chat1` from config.
  - Any other `kwargs` matching config keys are merged into the config for that call and passed through to `sbatch`.

## Future (maybe)
- Adding history with job_ids
- Adding dependencies