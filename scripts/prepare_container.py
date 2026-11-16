import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"server"))
from ex1b.database import Database
from ex1b.cli import fingerprint
from ex1b.protocol import Fault

certs = ROOT/"runtime/certs"
out = ROOT/"runtime/server-certs"
out.mkdir(parents=True,exist_ok=True)
for name in ("ca.pem","server.pem","server.key"):
    shutil.copyfile(certs/name,out/name)
    (out/name).chmod(0o644 if name != "server.key" else 0o640)
database = Database(ROOT/"runtime/container-data")
for name,rate in [("alice",2097152),("bob",524288)]:
    try:
        database.user(name=name)
    except Fault:
        database.add_user(name,fingerprint(certs/f"{name}.pem"),rate,2147483648)
database.db.close()
print("容器目录已准备。随后由隔离的初始化容器设置UID 10001权限。")
