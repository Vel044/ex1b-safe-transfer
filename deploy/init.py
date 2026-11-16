"""Runs in a disposable initializer, never in the network-facing service."""
import shutil
from pathlib import Path
from ex1b.database import Database
from ex1b.cli import fingerprint

for name in ("ca.pem","server.pem","server.key"):
    shutil.copyfile(Path("/bootstrap")/name,Path("/certs")/name)
db=Database("/data")
for name,rate in [("alice",2097152),("bob",524288)]:
    existing=db.db.execute("SELECT fingerprint FROM users WHERE name=?",(name,)).fetchone()
    value=fingerprint(Path("/bootstrap")/(name+".pem"))
    if existing:
        if existing[0] != value:raise RuntimeError("现有账户证书不同，拒绝覆盖")
    else:db.add_user(name,value,rate,2147483648)
db.db.close()
