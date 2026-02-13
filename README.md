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
sb.run(f"ls -la", dry=False, mem=4, cpus=4, v=2, time=48, teleslurm=True)
```

CLI: 
```bash
`python -m slurmbot.teleslurm -c chat1 "MESSAGE"` # 🚨 do not forget to specify chat1 settings in config if use -c
```

## Config (YAML)

Minimal example: [default.yaml](./default.yaml). Put your config in `~/.config/slurmbot/default.yaml`.

## Future (maybe)
- Adding history with job_ids
- Adding dependencies