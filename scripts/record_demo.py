"""Record actual build/deploy/test stdout with timestamps for video playback."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"output/evidence"
OUT.mkdir(parents=True,exist_ok=True)
events=[]
started=time.monotonic()
unique=datetime.now().strftime("%Y%m%d-%H%M%S")


def run(title,command):
    print(title,flush=True)
    event={"title":title,"command":command,"started":time.monotonic()-started,"lines":[]}
    process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    for line in process.stdout:
        event["lines"].append({"time":time.monotonic()-started,"text":line.rstrip()})
    event["code"]=process.wait()
    event["duration"]=time.monotonic()-started-event["started"]
    events.append(event)
    (OUT/"demo-events.json").write_text(json.dumps(events,ensure_ascii=False,indent=2))
    print(f"  exit={event['code']} duration={event['duration']:.2f}s",flush=True)
    if event["code"]:raise SystemExit("验证命令失败，请检查demo-events.json")


run("01 编译环境",["xcodebuild","-version"])
run("02 准备证书与账户",[str(ROOT/".venv/bin/python"),"scripts/bootstrap.py"])
run("03 构建原生Mac应用",["sh","scripts/build_macos.sh"])
run("04 构建与部署隔离服务",["sh","scripts/container_up.sh"])
run("05 服务端功能与安全测试",[str(ROOT/".venv/bin/python"),"-m","pytest","-q","-s","--junitxml=output/evidence/python-tests.xml"])
run("06 Swift协议及文件安全测试",["swift","test","--package-path","macos","--build-system","native","-q"])
run("07 Swift与容器互传及心跳",["macos/.build/debug/TransferProbe","--certs","runtime/certs","--root",f"runtime/video-smoke-{unique}","--idle-seconds","17"])
run("08 保存独立进程检查点",["macos/.build/debug/TransferProbe","--certs","runtime/certs","--resume-stage","start","--state",f"runtime/video-restart-{unique}"])
run("09 重启服务端",["docker","compose","restart","server"])
run("10 等待服务端就绪",["docker","compose","up","-d","--wait"])
run("11 新Swift进程恢复原任务",["macos/.build/debug/TransferProbe","--certs","runtime/certs","--resume-stage","finish","--state",f"runtime/video-restart-{unique}"])
scope="""import os,pathlib
assert os.getuid()==10001
assert not pathlib.Path('/Users/vel').exists()
assert not pathlib.Path('/certs/ca.key').exists()
try:
 pathlib.Path('/outside-test').write_text('test')
except OSError as e:
 print('UID=10001; host home absent; CA private key absent; outside write DENIED:',e)
else: raise SystemExit('Isolation failed')
"""
run("12 验证容器目录边界",["docker","compose","exec","-T","server","python","-c",scope])
print("真实构建部署测试记录已保存：output/evidence/demo-events.json",flush=True)
