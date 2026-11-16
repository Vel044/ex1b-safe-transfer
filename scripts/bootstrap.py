"""Generate local secrets and accounts. Never downloads or installs a global CA."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"server"))
from ex1b.cli import certificates, fingerprint
from ex1b.database import Database
from ex1b.protocol import Fault

runtime = ROOT/"runtime"
certs = certificates(runtime/"certs",["alice","bob"])
database = Database(runtime/"data")
for name,rate in [("alice",2097152),("bob",524288)]:
    try:
        current = database.user(name=name)
        if current["fingerprint"] != fingerprint(certs/f"{name}.pem"):
            raise RuntimeError("现有账户与证书不同，请明确迁移或使用新的运行目录")
    except Fault as error:
        if error.code != "AUTH":
            raise
        database.add_user(name,fingerprint(certs/f"{name}.pem"),rate,2147483648)
database.db.close()
config = {"host":"127.0.0.1","port":8443,"data":str(runtime/"data"),"certificate":str(certs/"server.pem"),"key":str(certs/"server.key"),"ca":str(certs/"ca.pem")}
(runtime/"server.json").write_text(json.dumps(config,indent=2))
(runtime/"server.json").chmod(0o600)
print("实验环境已准备；服务端配置：runtime/server.json；客户端证书：runtime/certs/*.p12")
