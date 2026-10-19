"""Hash-bound local read transport, built using the already installed NDK."""
import hashlib
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent
from portable_config import host_compiler_command


def ensure_reader(adb):
    source=ROOT/'readonly_memory_reader.cpp'
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    directory=ROOT/'build-readonly-memory'/source_hash[:16]
    binary=directory/'cr_readonly_mem'
    if not binary.exists():
        directory.mkdir(parents=True,exist_ok=True)
        subprocess.run(host_compiler_command()+['-std=c++17','-O2','-Wall','-Wextra','-Werror','-static-libstdc++',
                        str(source),'-o',str(binary)],check=True,timeout=30)
    if binary.is_symlink() or not binary.is_file():raise ValueError('invalid local read transport')
    expected=hashlib.sha256(binary.read_bytes()).hexdigest()
    remote='/data/local/tmp/cr_readonly_mem_'+source_hash[:16]
    def observed():
        check=subprocess.run(adb+['shell','sha256sum '+remote],capture_output=True,text=True,timeout=10)
        return check.stdout.split()[0] if check.returncode==0 and check.stdout.split() else None
    found=observed()
    if found is None:
        subprocess.run(adb+['push',str(binary),remote],check=True,capture_output=True,timeout=15)
        subprocess.run(adb+['shell','chmod 700 '+remote],check=True,capture_output=True,timeout=10)
        found=observed()
    if found!=expected:raise ValueError('local read transport hash differs; do not overwrite')
    return remote
