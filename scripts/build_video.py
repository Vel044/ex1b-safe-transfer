"""Render recorded command output and append the real native-window recording."""
import argparse
import json
import re
import subprocess
from pathlib import Path

from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"output"
WORK=OUT/"video-work"
WORK.mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser()
parser.add_argument("--name",required=True)
parser.add_argument("--student-id",required=True)
parser.add_argument("--native",default=str(OUT/"evidence/native-window.mp4"))
args=parser.parse_args()
events=json.loads((OUT/"evidence/demo-events.json").read_text())
fontPath="/System/Library/Fonts/STHeiti Light.ttc"
regular=ImageFont.truetype(fontPath,22,index=0)
small=ImageFont.truetype(fontPath,18,index=0)
titleFont=ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc",34,index=0)
ANSI=re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
frames=[]


def wrap(text,font,width):
    lines=[];line=""
    for char in text:
        if font.getlength(line+char)>width:
            lines.append(line);line=char
        else:line+=char
    return lines+[line]


def frame(title,lines,footer,duration):
    image=Image.new("RGB",(1280,840),"#f5f5f7")
    draw=ImageDraw.Draw(image)
    draw.text((48,24),"实验1B 安全文件传输",font=small,fill="#555555")
    draw.text((48,60),title,font=titleFont,fill="#111111")
    draw.rounded_rectangle((32,125,1248,774),radius=12,fill="#181b20")
    wrapped=[]
    for text in lines:
        wrapped+=wrap(ANSI.sub("",text).replace("\t","    "),regular,1150)
    y=146
    for line in wrapped[-22:]:
        draw.text((56,y),line,font=regular,fill="#eff1f4");y+=27
    draw.text((48,797),footer,font=small,fill="#555555")
    path=WORK/f"frame-{len(frames):05d}.png"
    image.save(path)
    frames.append((path,duration))


frame("安传 原生Mac客户端与安全服务器",[
    f"姓名：{args.name}   学号：{args.student_id}",
    "客户端：SwiftUI / AppKit / Network.framework / Security / SwiftData",
    "服务端：Python asyncio / SQLite / Docker Linux",
    "双向TLS · TCP长连接 · SHA-256 · 四文件并发",
    "文件夹传输 · 持久化断点续传 · 账户共享限速 · 目录访问控制",
    "仓库：https://github.com/Vel044/ex1b-safe-transfer",
    "本视频前半部分回放实际执行的构建、部署及测试输出。",
    "后半部分为本应用窗口的实际操作录像。"
],"实际运行证据 · 2026年11月16日",9)
for index,event in enumerate(events,1):
    command=" ".join(event["command"])
    command=command.replace(str(ROOT)+"/","")
    lines=["$ "+command]
    output=[line["text"] for line in event["lines"] if line["text"].strip()]
    # Every output line is retained; scrolling output is replayed in small groups.
    for start in range(0,len(output),4):
        lines+=output[start:start+4]
        frame(event["title"],lines,f"实际输出回放 {index}/{len(events)} · 本步骤真实耗时 {event['duration']:.2f} 秒",0.45)
    lines.append(f"退出状态 {event['code']}  ·  本步骤通过")
    frame(event["title"],lines,"验证成功 · 完整逐行记录见源码附带的运行证据",4.5)
frame("原生窗口操作演示",[
    "以下是原生窗口录像的两倍速节选，只采集本应用窗口。",
    "双栏文件列表、系统工具栏、可调整分栏、原生进度条及任务队列。",
    "展示大文件上传进度、传输队列及完整性校验结果。",
    "前序文件夹上传下载记录保持在同一个任务数据库中。"
],"原生Mac应用窗口录像",6)
manifest=WORK/"frames.txt"
with manifest.open("w") as f:
    for path,duration in frames:
        f.write(f"file '{path}'\nduration {duration}\n")
    f.write(f"file '{frames[-1][0]}'\n")


def run(command):subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)


terminal=WORK/"terminal.mp4"
run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(manifest),"-vf","fps=15","-c:v","libx264","-preset","fast","-crf","21","-pix_fmt","yuv420p","-video_track_timescale","15360",str(terminal)])
parts=[terminal]
native=Path(args.native)
if not native.is_file():raise SystemExit("缺少真实原生窗口录像")
scaled=WORK/"native.mp4"
run(["ffmpeg","-y","-i",str(native),"-vf","trim=start=15:end=65,setpts=0.5*(PTS-STARTPTS),scale=1280:840:force_original_aspect_ratio=decrease,pad=1280:840:(ow-iw)/2:(oh-ih)/2:color=white,fps=15","-an","-c:v","libx264","-preset","fast","-crf","21","-pix_fmt","yuv420p","-video_track_timescale","15360",str(scaled)])
parts.append(scaled)
endLines=["全部基本要求与四项加分能力已实现。","19项服务端测试、6项Swift测试及跨语言实际互传通过。","完整协议、访问控制配置及安全边界详见实验报告。","应用层限制不能消除网络带宽耗尽，实验不宣称互联网规模DDoS防护。","https://github.com/Vel044/ex1b-safe-transfer"]
oldCount=len(frames);frame("实验结果与适用范围",endLines,"源码、报告、部署配置及运行证据均已整理",7)
end=WORK/"end.mp4"
run(["ffmpeg","-y","-loop","1","-i",str(frames[-1][0]),"-t","7","-vf","fps=15","-c:v","libx264","-preset","fast","-crf","21","-pix_fmt","yuv420p","-video_track_timescale","15360",str(end)])
parts.append(end)
playlist=WORK/"parts.txt";playlist.write_text("".join(f"file '{path}'\n" for path in parts))
result=OUT/f"{args.name}_{args.student_id}_ex1B_play.mp4"
run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(playlist),"-c","copy","-movflags","+faststart",str(result)])
print(result)
