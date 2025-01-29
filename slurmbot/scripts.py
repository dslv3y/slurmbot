import os
import sys
from importlib.resources import files

def run_bash_script(script):
  resource = files("jbatch")
  os.environ["PATH"] = f"{resource}:{os.getenv('PATH')}"
  script = files("jbatch").joinpath(script)
  os.execv(script, sys.argv)

def err():
  run_bash_script("err")

def out():
  run_bash_script("out")

def sc():
  run_bash_script("sc")

def sa():
  run_bash_script("sa")

def sq():
  run_bash_script("sq")

if __name__ == "__main__":
  err()