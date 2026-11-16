import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"server"))
from ex1b.database import Database
from ex1b.cli import fingerprint
from ex1b.protocol import Fault

certs = ROOT/"runtime/certs"
out = ROOT/"runtime/container-bootstrap"
out.mkdir(parents=True,exist_ok=True)
for name in ("ca.pem","server.pem","server.key","alice.pem","bob.pem"):
    shutil.copyfile(certs/name,out/name)
    (out/name).chmod(0o600)
for name in ("container-data","server-certs"):
    (ROOT/"runtime"/name).mkdir(exist_ok=True)
print("容器目录已准备。随后由隔离的初始化容器设置UID 10001权限。")
