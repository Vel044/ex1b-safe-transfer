import argparse
import io
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument("--name",required=True);p.add_argument("--student-id",required=True)
a=p.parse_args()
for value in (a.name,a.student_id):
    if not value or any(c in value for c in "/\\\0\n"):raise SystemExit("无效署名")
prefix=f"{a.name}_{a.student_id}"
folder=ROOT/"output"/(prefix+"_EX1B")
folder.mkdir(exist_ok=True)
source=folder/(prefix+"_ex1B_src")
source.mkdir(exist_ok=True)
archive=subprocess.check_output(["git","archive","--format=tar","HEAD"],cwd=ROOT)
with tarfile.open(fileobj=io.BytesIO(archive)) as t:t.extractall(source,filter="data")
app=ROOT/"build/安传.app"
if not app.exists():raise SystemExit("请先构建Release应用")
shutil.copytree(app,source/"macOS应用/安传.app",dirs_exist_ok=True)
for ext,suffix in [("pdf","report"),("mp4","play")]:
    name=f"{prefix}_ex1B_{suffix}.{ext}"
    shutil.copyfile(ROOT/"output"/name,folder/name)
evidence=source/"运行证据";evidence.mkdir(exist_ok=True)
for name in ("python-tests.xml","swift-roundtrip.json","demo-events.json","native-client-final.png"):
    path=ROOT/"output/evidence"/name
    if path.exists():shutil.copyfile(path,evidence/name)
result=ROOT/"output"/(prefix+"_EX1B.zip")
with zipfile.ZipFile(result,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.name != ".DS_Store":z.write(path,path.relative_to(folder.parent))
with zipfile.ZipFile(result) as z:
    assert z.testzip() is None
    assert all(not i.flag_bits & 1 for i in z.infolist())
    forbidden=(".key",".p12",".password",".sqlite",".sqlite-shm",".sqlite-wal")
    assert not any(i.filename.endswith(forbidden) for i in z.infolist())
print(result)
