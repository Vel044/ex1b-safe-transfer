"""Assemble the recorded experiment clips; requires ffmpeg, ffprobe and Pillow.
Sources are preserved. No audio is included in the output.
"""
import argparse
import json
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'video'
WORK=SOURCE/'.edit-work-v3'
TIMELINE=[]
W,H,FPS=2560,1800,15
FONT='/System/Library/Fonts/STHeiti Light.ttc'
BOLD='/System/Library/Fonts/STHeiti Medium.ttc'
CLIPS=[
 ('AB文件架构:编译启动.mp4','1｜项目文件架构 / 编译启动','项目结构 · Docker 服务部署 · macOS 客户端','文件 / 启动','normal'),
 ('C1.mp4','2｜上传下载删除','复制粘贴上传 · 拖动下载 · Command Delete 删除','上传下载删除','normal'),
 ('C2.mp4','3｜文件完整性核对','对比源文件与下载文件的 SHA-256','文件核对','normal'),
 ('D.mp4','4｜文件断点续传','暂停 → 断开连接 → 重新连接 → 继续原任务','断点续传','normal'),
 ('E1.mp4','5｜双向证书验证','正常身份与错误证书的连接表现','证书验证','auth'),
 ('E2.mp4','6｜Alice 读写 · Bob 只读','证书确定身份，账户配置决定权限','读写权限','auth'),
 ('F并发IO.mp4','7｜GUI 多文件并发上传与下载','上传和下载任务在同一队列中交替推进','并发传输','normal'),
 ('G.mp4','8｜Bob 的带宽动态调整','调整前不限速 → 调整后 256 KiB/s','用户限速','bandwidth'),
]

def font(size,bold=False):return ImageFont.truetype(BOLD if bold else FONT,size)
def label(draw,xy,text,size=34,fill='#16243b',bold=False):
 draw.text(xy,text,font=font(size,bold),fill=fill,spacing=12)
def probe(path):
 return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))
def assets(index,total_frames,offset,frames,after=False):
 _,title,sub,short,mode=CLIPS[index]
 im=Image.new('RGB',(W,H),'#eef3f9');d=ImageDraw.Draw(im)
 d.rectangle((0,0,W,156),fill='#10213d')
 label(d,(60,42),title,74,'#ffffff',True)
 if mode=='normal':
  x,y,boxw,boxh=32,186,W-64,1450
 else:
  x,y,boxw,boxh=28,190,1840,1440
  d.rounded_rectangle((1896,260,2528,1625),radius=26,fill='#ffffff',outline='#cdd9e8',width=2)
  if mode=='auth':
   label(d,(1930,292),'四组验证对照',43,bold=True)
   label(d,(1930,350),'验证条件 / 预期结果',29,'#547092')
   rows=[('01  正常连接','正确 CA + Alice 证书','连接成功'),
         ('02  客户端验证服务器','选择错误 CA','拒绝连接'),
         ('03  服务端验证客户端','外部 CA 客户端证书','拒绝连接'),
         ('04  读写权限对比','Alice rw / Bob r','读写 / 只读')]
   for n,(head,condition,result) in enumerate(rows):
    top=416+n*258
    active=index==5 and n==3
    d.rounded_rectangle((1917,top,2507,top+234),radius=16,fill='#e7f0ff' if active else '#f3f6fa')
    label(d,(1942,top+24),head,34,'#173e74',True)
    label(d,(1942,top+83),condition,31,'#40516a')
    label(d,(1942,top+147),'预期：'+result,37,'#0d704f',True)
   label(d,(1934,1495),'第 1–3 项：身份认证\n第 4 项：账户授权',29,'#58708f')
  else:
   label(d,(1930,300),'BOB · 带宽对比',43,bold=True)
   for n,(head,value,detail) in enumerate([('调整前','不限速','bandwidth = 0'),('调整后','256 KiB/s','262144 字节 / 秒')]):
    top=426+n*397
    active=(n==1)==after
    d.rounded_rectangle((1920,top,2504,top+338),radius=22,fill='#e4efff' if active else '#f1f4f8',outline='#3874d6' if active else '#d6dfea',width=3)
    label(d,(1950,top+35),head,42,'#335786',True)
    label(d,(1950,top+112),value,64,'#095ac9' if active else '#6b7f97',True)
    label(d,(1950,top+232),detail,31,'#506888')
   label(d,(1932,1260),'服务端按账户调整上限',34,bold=True)
   label(d,(1932,1335),'同一账户共享带宽预算',30,'#506888')
   label(d,(1932,1420),'当前：'+('已设置 256 KiB/s' if after else '尚未设置带宽上限'),32,'#095ac9',True)
 # The source is fitted, not cropped; the application status bar remains visible.
 meta=probe(SOURCE/CLIPS[index][0]);stream=next(s for s in meta['streams'] if s['codec_type']=='video')
 ratio=min(boxw/stream['width'],boxh/stream['height'])
 vw=int(stream['width']*ratio)//2*2;vh=int(stream['height']*ratio)//2*2
 vx=x+(boxw-vw)//2;vy=y+(boxh-vh)//2
 d.rounded_rectangle((vx-2,vy-2,vx+vw+2,vy+vh+2),radius=14,fill='#ffffff',outline='#cdd9e8',width=2)
 # Persistent bottom chapter navigation and global playback progress.
 d.rectangle((0,1657,W,H),fill='#10213d')
 for n,clip in enumerate(CLIPS):
  item=TIMELINE[n]
  # Chapter boundaries match cumulative elapsed time, including the progress bar.
  begin=round(W*item['offset']/total_frames)
  end=round(W*(item['offset']+item['frames'])/total_frames)
  left=begin+3;right=end-3
  d.rounded_rectangle((left,1684,right,1750),radius=10,fill='#2265ca' if n==index else '#1c3353')
  text=f'{n+1} '+('校验' if n==2 else clip[3]);size=32
  while size>16 and d.textlength(text,font=font(size,n==index))>right-left-16:size-=1
  tw=d.textlength(text,font=font(size,n==index))
  label(d,(left+(right-left-tw)/2,1717-size/2),text,size,'#ffffff' if n==index else '#a9bdd6',n==index)
 d.rectangle((0,1784,W,1799),fill='#344e70')
 dest=WORK/f'panel-{index:02d}{"-after" if after else ""}.png';im.save(dest)
 return dest,(vx,vy,vw,vh)

def run_render(index,meta):
 clip=CLIPS[index];frames=meta['frames'];offset=meta['offset'];duration=frames/FPS
 panel,geometry=assets(index,meta['total_frames'],offset,frames)
 x,y,vw,vh=geometry
 dest=WORK/f'segment-{index:02d}.mp4'
 command=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(SOURCE/clip[0]),'-loop','1','-framerate',str(FPS),'-i',str(panel),'-loop','1','-framerate',str(FPS),'-i',str(WORK/'progress.png')]
 before='[1:v]format=rgba[bg];'
 if clip[4]=='bandwidth':
  after,_=assets(index,meta['total_frames'],offset,frames,True)
  command+=['-loop','1','-framerate',str(FPS),'-i',str(after)]
  before="[1:v][3:v]overlay=0:0:enable='gte(t,18)'[bg];"
 graph=(f'[0:v]setpts=(PTS-STARTPTS)/{meta["speed"]},fps={FPS},scale={vw}:{vh}:flags=lanczos,setsar=1,tpad=stop_mode=clone:stop_duration=1,trim=end_frame={frames},setpts=PTS-STARTPTS[screen];'+before+
        f'[bg][screen]overlay={x}:{y}:shortest=1[scene];'+
        f"[scene][2:v]overlay=x='-overlay_w+main_w*min(1,({offset/FPS:.9f}+t+1/{FPS})/{meta['total_frames']/FPS:.9f})':y=1784:shortest=1,format=yuv420p[out]")
 command+=['-filter_complex_threads','1','-filter_complex',graph,'-map','[out]','-an','-frames:v',str(frames),'-c:v','libx264','-preset','veryfast','-crf','19','-threads','4','-pix_fmt','yuv420p','-r',str(FPS),'-video_track_timescale','15360','-movflags','+faststart',str(dest)]
 log=WORK/f'render-{index:02d}.log'
 print(f'RENDER {index+1}/{len(CLIPS)} {clip[0]} ({duration:.1f}s)',flush=True)
 with log.open('w') as f:subprocess.run(command,check=True,stdout=f,stderr=f)
 print(f'DONE {index+1}/{len(CLIPS)} {dest.stat().st_size/1e6:.1f} MB',flush=True)
 return dest

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--preview-only',action='store_true');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
 WORK.mkdir(parents=True,exist_ok=True)
 meta=[];offset=0
 for i,clip in enumerate(CLIPS):
  info=probe(SOURCE/clip[0]);speed=1.5 if i==0 else 1.0
  frames=round(float(info['format']['duration'])*FPS/speed)
  meta.append({'file':clip[0],'frames':frames,'offset':offset,'speed':speed});offset+=frames
 for item in meta:item['total_frames']=offset
 TIMELINE.clear();TIMELINE.extend(meta)
 Image.new('RGB',(W,16),'#4cc9ff').save(WORK/'progress.png')
 for index,t in [(0,2),(4,32),(5,10),(7,26)]:
  panel,(x,y,vw,vh)=assets(index,offset,meta[index]['offset'],meta[index]['frames'],index==7)
  shot=WORK/f'preview-source-{index}.png'
  subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t*meta[index]['speed']),'-i',str(SOURCE/CLIPS[index][0]),'-frames:v','1',str(shot)],check=True)
  canvas=Image.open(panel);recording=Image.open(shot).resize((vw,vh),Image.Resampling.LANCZOS);canvas.paste(recording,(x,y))
  d=ImageDraw.Draw(canvas);progress=(meta[index]['offset']+t*FPS)/offset;d.rectangle((0,1784,int(W*progress),1799),fill='#4cc9ff')
  canvas.save(WORK/f'preview-{index}.jpg',quality=90)
 if args.preview_only:
  print('Preview assets ready',flush=True);return
 segments=[]
 for i,item in enumerate(meta):
  path=WORK/f'segment-{i:02d}.mp4'
  if args.resume and path.exists():
   try:valid=round(float(probe(path)['format']['duration'])*FPS)==item['frames']
   except Exception:valid=False
  else:valid=False
  segments.append(path if valid else run_render(i,item))
 manifest=WORK/'concat.txt';manifest.write_text(''.join("file '"+p.name+"'\n" for p in segments))
 output=SOURCE/'SFT1_实验1B_演示_v3.mp4'
 subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(manifest),'-map','0:v:0','-c','copy','-an','-movflags','+faststart',str(output)],check=True)
 data={'output':str(output),'audio':'removed','fps':FPS,'size':[W,H],'duration_seconds':offset/FPS,'clips':meta,'bandwidth_caption_switch_seconds_in_G':18,'title_style':'numeric chapters 1–8; large title only; no brand line, subtitle or counter','chapter_widths':'proportional to duration','note':'G contains the Bob bandwidth adjustment; F is concurrency. E table lists expected outcomes, not asserted passes.'}
 (SOURCE/'剪辑说明_v3.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
 result=probe(output)
 assert not any(s['codec_type']=='audio' for s in result['streams'])
 assert abs(float(result['format']['duration'])-offset/FPS)<0.15
 print('OUTPUT '+str(output),flush=True)
 print(f'DURATION {offset/FPS:.2f}s | SIZE {output.stat().st_size/1e6:.1f} MB | NO AUDIO',flush=True)

if __name__=='__main__':main()
