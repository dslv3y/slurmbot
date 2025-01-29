## SlurmBot 🤖
SlurmBot is a minimalistic tool to wrap and execute `sbatch` commands from Python scripts with optional Conda environment management, useful for integrating Slurm job submissions directly into your workflows.
_Based on [jbatch](https://pypi.org/project/jbatch/)_.

Simple tool to wrap and execute `sbatch` commands from `python` scripts or `Jupyter Notebook` cells with `conda` envs and config files. Less mess, more reproducibility and security (if published to GitHub, for instance).

- ⚙️ **Config Files**: Create config files in `YAML` format and reuse them. Make a `default.yaml` in `~/.config/slurmbot/default.yaml`
- 🐍 **Python Variables**: Easily integrate Python variables into your Slurm job commands.
- 🛠️ **Conda**: Activate Conda environments with the `conda` property.

## Installation
Install `SlurmBot` via `pip`:
`pip install slurmbot`

## Example
```python
from slurmbot import SlurmBot 
sb = SlurmBot() # using default yaml from ~/.config/slurmbot/default.yaml, if exists OR specify path to config
samples = ["SRR000001", "SRR000002"]
for sample in samples:
	sb.run(f"fasterq-dump {sample}", conda="ngs", mem=4, cpus=4)
```
