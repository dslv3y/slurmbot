from slurmbot import SlurmBot

sb = SlurmBot(mode = "screen")
sb.run("sleep 5; echo 'test1'>test_screen.txt", 
        v=2, teleslurm=True)


sb = SlurmBot(mode = "slurm")
sb.run("sleep 5; echo 'test2'>test_slurm.txt", 
        mem=4, cpus=4, v=2, time=48, teleslurm=True)