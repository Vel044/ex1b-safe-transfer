"""Local speech transcription and captions for the narrated demo.

Use --transcribe first, proofread video/.title-fix/captions.json, then --render.
Requires mlx-whisper (transcription), Pillow, ffmpeg and ffprobe.
The original MOV is never overwritten, and its AAC stream is copied unchanged.
"""
import argparse
import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / 'video'
WORK = VIDEO / '.title-fix'
SOURCE = VIDEO / 'SFT1_实验1B_演示_含音频.mov'
OUTPUT = VIDEO / 'SFT1_实验1B_演示_字幕版.mp4'
CAPTIONS = WORK / 'captions.json'
SRT = VIDEO / 'SFT1_实验1B_演示_字幕.srt'
FONT = '/System/Library/Fonts/STHeiti Medium.ttc'


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def transcribe():
    import mlx_whisper
    from opencc import OpenCC
    model = next((Path.home() / '.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo/snapshots').iterdir())
    audio = WORK / 'voice.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(SOURCE), '-vn', '-ac', '1', '-ar', '16000', str(audio)], check=True)
    print('Transcribing locally with cached MLX Whisper model', flush=True)
    result = mlx_whisper.transcribe(str(audio), path_or_hf_repo=str(model), language='zh',
        word_timestamps=True, verbose=True, temperature=0,
        initial_prompt='以下是软件与系统安全实验的中文讲解。术语：SFT1 Transfer，macOS，SwiftUI，AppKit，SafeTransferApp，SafeTransferCore，Python，Docker，TLS，TCP，CA，P12，Alice，Bob，SHA-256，KiB/s。',
        hallucination_silence_threshold=2.0)
    (WORK / 'transcript-raw.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    converter = OpenCC('t2s')
    rows = []
    for segment in result['segments']:
        words = segment.get('words') or [dict(start=segment['start'],end=segment['end'],word=segment['text'])]
        group = []
        for word in words:
            text = converter.convert(word['word'])
            # Keep captions within a comfortable single-line reading length.
            if group and (len(''.join(w['word'] for w in group)) + len(text) > 34
                          or word['start'] - group[0]['start'] > 5.5):
                rows.append(dict(start=group[0]['start'], end=group[-1]['end'], text=''.join(w['word'] for w in group).strip()))
                group = []
            group.append(dict(start=word['start'],end=word['end'],word=text))
            if re.search('[。！？；]$', text) and word['end'] - group[0]['start'] >= 1:
                rows.append(dict(start=group[0]['start'], end=group[-1]['end'], text=''.join(w['word'] for w in group).strip()))
                group = []
        if group:
            rows.append(dict(start=group[0]['start'], end=group[-1]['end'], text=''.join(w['word'] for w in group).strip()))
    CAPTIONS.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f'Wrote {len(rows)} draft captions to {CAPTIONS}', flush=True)


def timestamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def render(preview_only=False):
    timeline = json.loads((VIDEO / '剪辑说明_v3.json').read_text())
    clips = timeline['clips']
    fps = timeline['fps']
    rows = json.loads(CAPTIONS.read_text())
    info = probe(SOURCE)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    assert (video['width'],video['height']) == (1920,1080), 'Patch geometry requires the supplied 1920×1080 Resolve export'
    duration = float(video['duration'])
    for i, row in enumerate(rows):
        assert 0 <= row['start'] < row['end'] <= duration + 0.1, row
        if i:
            assert row['start'] >= rows[i-1]['end'] - 0.001, (rows[i-1], row)
    SRT.write_text('\n'.join(f'{i+1}\n{timestamp(row["start"])} --> {timestamp(row["end"])}\n{row["text"]}\n' for i,row in enumerate(rows)), encoding='utf-8')
    layers = []
    for i, title in enumerate(['1｜项目文件架构 / 编译启动', '2｜上传下载删除']):
        # The 2560×1800 original was fitted to 1536×1080 with x=192.
        im = Image.new('RGBA', (1536,94), '#10213d')
        ImageDraw.Draw(im).text((36,25), title, font=ImageFont.truetype(FONT,44), fill='white')
        path = WORK / f'title-{i}.png'; im.save(path)
        start = clips[i]['offset']/fps; end = (clips[i]['offset']+clips[i]['frames'])/fps
        layers.append((path,192,0,start,end))
    # Replace only the two changed navigation labels; all other UI is untouched.
    for phase in range(3):
        im = Image.new('RGBA',(512,44),(0,0,0,0)); draw=ImageDraw.Draw(im)
        for i, text in enumerate(['1 文件 / 启动', '2 上传下载删除']):
            left=round(1536*clips[i]['offset']/timeline['clips'][0]['total_frames'])+7
            right=round(1536*(clips[i]['offset']+clips[i]['frames'])/timeline['clips'][0]['total_frames'])-7
            draw.rectangle((left,5,right,37), fill='#2265ca' if phase==i else '#1c3353')
            size=19
            while draw.textlength(text,font=ImageFont.truetype(FONT,size)) > right-left-6:size-=1
            draw.text(((left+right-draw.textlength(text,font=ImageFont.truetype(FONT,size)))/2,22-size/2),text,font=ImageFont.truetype(FONT,size),fill='white' if phase==i else '#a9bdd6')
        path=WORK/f'nav-{phase}.png';im.save(path)
        start=0 if phase==0 else (clips[1]['offset']/fps if phase==1 else clips[2]['offset']/fps)
        end=clips[phase+1]['offset']/fps if phase<2 else duration+0.1
        layers.append((path,192,1008,start,end))
    # Pillow-rendered transparent caption cards work with ffmpeg builds without libass.
    caption_layers=[]
    for i,row in enumerate(rows):
        text=row['text'];size=34;font=ImageFont.truetype(FONT,size)
        while font.getlength(text)>1450:
            size-=1;font=ImageFont.truetype(FONT,size)
        width=round(font.getlength(text))+48
        im=Image.new('RGBA',(width,58),(0,0,0,0));draw=ImageDraw.Draw(im)
        draw.rounded_rectangle((0,0,width-1,57),radius=10,fill=(0,0,0,205))
        draw.text((width/2,28),text,font=font,anchor='mm',fill='white',stroke_width=1,stroke_fill='black')
        path=WORK/f'caption-{i:03d}.png';im.save(path)
        caption_layers.append((path,(1920-width)//2,908,row['start'],row['end']))
    layers+=caption_layers
    if preview_only:
        for t in [5,80,151,285]:
            path=WORK/f'preview-{t}.png'
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(SOURCE),'-frames:v','1',str(path)],check=True)
            canvas=Image.open(path).convert('RGBA')
            for layer,x,y,start,end in layers:
                if start<=t<end:canvas.alpha_composite(Image.open(layer),(x,y))
            canvas.convert('RGB').save(path)
        print(f'Wrote previews, {len(rows)} captions, and {SRT}',flush=True)
        return
    # A transparent animation encodes title, navigation and subtitle patches together.
    # One raw RGBA pipe avoids opening hundreds of ffmpeg inputs.
    command=['ffmpeg','-v','error','-y','-i',str(SOURCE),'-f','rawvideo','-pixel_format','rgba','-video_size','1920x1080','-framerate',video['avg_frame_rate'],'-i','pipe:0',
        '-filter_complex_threads','1','-filter_complex','[0:v][1:v]overlay=0:0:shortest=1,format=yuv420p[out]',
        '-map','[out]','-map','0:a:0','-c:v','libx264','-preset','veryfast','-crf','18','-threads','4','-c:a','copy','-movflags','+faststart',str(OUTPUT)]
    rate=float(Fraction(video['avg_frame_rate']))
    frames=int(video['nb_frames'])
    loaded=[(Image.open(p).convert('RGBA'),x,y,start,end) for p,x,y,start,end in layers]
    previous=None;pixels=None
    with (WORK/'render.log').open('w') as log:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for n in range(frames):
                t=n/rate
                active=tuple(i for i,(_,_,_,start,end) in enumerate(loaded) if start<=t<end)
                if active!=previous:
                    frame=Image.new('RGBA',(1920,1080),(0,0,0,0))
                    for i in active:
                        im,x,y,_,_=loaded[i];frame.alpha_composite(im,(x,y))
                    pixels=frame.tobytes();previous=active
                process.stdin.write(pixels)
                if n%720==0:print(f'RENDER {t:.1f}/{duration:.1f}s',flush=True)
        finally:
            process.stdin.close()
        if process.wait():raise RuntimeError((WORK/'render.log').read_text())
    def audio_hash(path):
        return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','hash','-hash','sha256','-']).decode().strip()
    original_hash=audio_hash(SOURCE);output_hash=audio_hash(OUTPUT)
    assert original_hash==output_hash,'Audio packet data changed'
    output=probe(OUTPUT)
    assert next(s['nb_frames'] for s in output['streams'] if s['codec_type']=='video')==str(frames)
    (VIDEO/'字幕版剪辑说明.json').write_text(json.dumps(dict(source=str(SOURCE),output=str(OUTPUT),captions=str(SRT),caption_count=len(rows),audio='AAC stream copied; packet SHA-256 verified identical',audio_hash=output_hash,duration=duration,frames=frames,changes=['1｜项目文件架构 / 编译启动','2｜上传下载删除']),ensure_ascii=False,indent=2))
    print(f'OUTPUT {OUTPUT}\nAUDIO VERIFIED {output_hash}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--transcribe',action='store_true')
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--preview-only',action='store_true')
    args=parser.parse_args();WORK.mkdir(exist_ok=True,parents=True)
    if args.transcribe:transcribe()
    if args.render or args.preview_only:render(args.preview_only)
