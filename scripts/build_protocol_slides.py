"""Build the protocol talk from the supplied PowerPoint template.

Run with DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib /opt/anaconda3/bin/python
scripts/build_protocol_slides.py. Uses python-pptx, fontTools and CairoSVG.
SVG diagrams are embedded with PNG fallbacks; text and code remain editable.
"""
from copy import deepcopy
from pathlib import Path
from html import escape
import json
import re
import cairosvg
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.opc.package import Part
from pptx.opc.packuri import PackURI
from pptx.oxml import parse_xml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path('/Users/vel/Desktop/LiteEth驱动移植.pptx')
OUT = ROOT / 'docs/SFT1_协议设计与重点模块.pptx'
ASSETS = ROOT / 'docs/assets/protocol-slides'
BUILD = ROOT / 'tmp/protocol-ppt'
ASSETS.mkdir(parents=True, exist_ok=True)
BUILD.mkdir(parents=True, exist_ok=True)
BLUE = '#075AA6'
INK = '#182C40'
PALE = '#EEF4FB'
CYAN = '#0096D6'
GRAY = '#5D6C7B'
GREEN = '#167456'
ORANGE = '#A66313'
RED = '#AF4040'
FONT_PATH = Path('/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts')
FONTS = {False: TTFont(FONT_PATH/'Deng.ttf'), True: TTFont(FONT_PATH/'Dengb.ttf')}


class SVG:
    """Vector text uses glyph outlines so the diagram is font-independent."""
    def __init__(self, name, w=600, h=470):
        self.name,self.w,self.h=name,w,h
        self.e=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            f'<title>{escape(name)}</title>',
            '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#075AA6"/></marker></defs>']

    def rect(self,x,y,w,h,fill=PALE,stroke=BLUE,r=0):
        self.e.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')

    def line(self,x1,y1,x2,y2,arrow=False,color=BLUE,dash=False):
        self.e.append(f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{color}" stroke-width="1.8" fill="none"'+(' marker-end="url(#arr)"' if arrow else '')+(' stroke-dasharray="5 5"' if dash else '')+'/>')

    def route(self,points,arrow=True,color=BLUE,dash=False):
        self.e.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="1.8"'+(' marker-end="url(#arr)"' if arrow else '')+(' stroke-dasharray="5 5"' if dash else '')+'/>')

    def diamond(self,cx,cy,w,h,label):
        self.e.append(f'<polygon points="{cx},{cy-h/2} {cx+w/2},{cy} {cx},{cy+h/2} {cx-w/2},{cy}" fill="#F3F8FC" stroke="{BLUE}" stroke-width="1.5"/>')
        self.text(cx,cy-12,label,23,BLUE,True,'middle')

    def text(self,x,y,text,size=22,color=INK,bold=False,anchor='start'):
        # y denotes the top of the text's em box.
        f=FONTS[bold];glyphs=f.getGlyphSet(); cmap=f.getBestCmap(); scale=size/f['head'].unitsPerEm
        names=[cmap.get(ord(c),'.notdef') for c in text]
        width=sum(f['hmtx'][n][0] for n in names)*scale
        if anchor=='middle':x-=width/2
        if anchor=='end':x-=width
        self.e.append(f'<g aria-label="{escape(text,quote=True)}" fill="{color}"><title>{escape(text)}</title>')
        baseline=y+size*.84
        for n in names:
            pen=SVGPathPen(glyphs);glyphs[n].draw(pen)
            self.e.append(f'<path transform="translate({x:.3f},{baseline:.3f}) scale({scale:.6f},{-scale:.6f})" d="{pen.getCommands()}"/>')
            x+=f['hmtx'][n][0]*scale
        self.e.append('</g>')
        return width

    def box(self,x,y,w,h,title,body=(),fill=PALE,sz=23):
        self.rect(x,y,w,h,fill)
        self.text(x+w/2,y+12,title,sz,BLUE,True,'middle')
        for i,t in enumerate(body):self.text(x+w/2,y+42+i*25,t,20,INK,False,'middle')

    def save(self):
        path=ASSETS/(self.name+'.svg')
        path.write_text(''.join(self.e)+'</svg>')
        png=BUILD/(self.name+'.png')
        cairosvg.svg2png(url=str(path),write_to=str(png),output_width=self.w*3,output_height=self.h*3)
        return path,png


def layers():
    s = SVG('09-1-协议分层')
    s.rect(15, 8, 570, 251, '#F3F8FC', '#8AAFCB', 6)
    s.text(36, 22, '应用层及其安全支持', 24, BLUE, True)
    s.rect(44, 62, 512, 54, '#FFFFFF', '#9BB9D3')
    s.text(300, 75, 'SFT1　文件传输应用层协议', 27, INK, True, 'middle')
    s.line(300, 116, 300, 138, True)
    s.rect(44, 142, 512, 102, '#FFFFFF', '#9BB9D3')
    s.text(300, 152, 'TLS　传输层安全协议', 26, INK, True, 'middle')
    s.text(300, 185, '客户端用苹果的 Network.framework 建立 TLS 连接', 21, INK, False, 'middle')
    s.text(300, 214, 'Python 服务端通过 ssl 模块调用 OpenSSL', 21, INK, False, 'middle')
    s.line(300, 259, 300, 273, True)
    s.rect(44, 277, 512, 64, '#FFFFFF', '#8AAFCB')
    s.text(300, 295, 'TCP　传输层（第 4 层）', 26, INK, True, 'middle')
    s.line(300, 341, 300, 373, True)
    s.rect(44, 377, 512, 64, '#FFFFFF', '#8AAFCB')
    s.text(300, 395, 'IP　网络层（第 3 层）', 26, INK, True, 'middle')
    return s.save()


def header():
    s = SVG('09-1-20字节报头')
    s.text(18, 12, '偏移 / B', 20, GRAY)
    for bit, x in [(0, 99), (8, 219), (16, 339), (24, 459), (31, 577)]:
        s.text(x, 12, str(bit), 19, GRAY, False, 'middle')
    rows = ['magic = "SFT1"', None, 'request', 'metadata_length  =  m', 'payload_length  =  n']
    for row, field in enumerate(rows):
        y = 47 + row * 51
        s.text(68, y + 14, str(row * 4), 23, GRAY, False, 'end')
        if field:
            s.rect(98, y, 480, 51, '#EEF4FB')
            s.text(338, y + 12, field, 25, BLUE, True, 'middle')
        else:
            for x, width, name in [(98, 120, 'version'), (218, 120, 'kind'), (338, 240, 'flags')]:
                s.rect(x, y, width, 51)
                s.text(x + width/2, y + 13, name, 24, BLUE, True, 'middle')
    s.text(98, 326, '可变长度正文（从偏移 20 开始）', 23, INK)
    for y, field, count in [(366, 'JSON 元数据', 'm 字节'), (414, '二进制载荷', 'n 字节')]:
        s.rect(98, y, 480, 47, '#F4FAF7', '#8DB7A6')
        s.text(117, y + 10, field, 24, GREEN, True)
        s.text(558, y + 10, count, 24, GREEN, False, 'end')
    return s.save()


def parser_flow():
    s=SVG('09-2-消息解析流程',720,500)
    s.rect(172,0,216,34,'#FFFFFF',BLUE,17)
    s.text(280,6,'开始接收消息',22,BLUE,True,'middle')
    s.line(280,34,280,56,True)
    s.rect(110,60,340,50,'#FFFFFF')
    s.text(280,74,'读满 20 字节报头',23,INK,False,'middle')
    s.line(280,110,280,135,True)
    s.diamond(280,179,290,80,'报头与长度合法？')
    s.line(280,219,280,246,True)
    s.text(294,225,'是',18,GREEN)
    s.rect(110,250,340,50,'#FFFFFF')
    s.text(280,264,'按长度读取 JSON 与载荷',22,INK,False,'middle')
    s.line(280,300,280,324,True)
    s.diamond(280,368,290,80,'JSON 是合法对象？')
    s.line(280,408,280,437,True)
    s.text(294,415,'是',18,GREEN)
    s.rect(110,441,340,48,'#FFFFFF')
    s.text(280,454,'分派处理，返回对应响应',22,INK,False,'middle')
    s.route([(110,465),(40,465),(40,85),(110,85)])
    s.text(44,345,'下一条',18,GRAY)
    s.route([(425,179),(620,179),(620,247)])
    s.text(446,153,'否',18,RED)
    s.route([(425,368),(620,368),(620,315)])
    s.text(446,341,'否',18,RED)
    s.rect(525,251,190,60,'#FFF5F3',RED,22)
    s.text(620,260,'拒绝报文',22,RED,True,'middle')
    s.text(620,286,'结束连接',21,RED,False,'middle')
    return s.save()


def initialize():
    s=SVG('10-1-会话初始化')
    for x,label in [(95,'客户端'),(495,'服务端')]:
        s.box(x-70,0,140,46,label,sz=23);s.line(x,46,x,415,color='#9BB9D3',dash=True)
    messages=[(90,95,495,'TCP 连接'),(145,95,495,'双向 TLS 握手'),(220,95,495,'HELLO'),(335,495,95,'WELCOME')]
    for y,x1,x2,t in messages:
        s.line(x1,y,x2,y,True);s.text(295,y-26,t,22,BLUE,True,'middle')
    s.rect(140,157,310,32,'#F9FBFD','#B1C9DE');s.text(295,164,'证书链、用途、主机身份检查',19,INK,False,'middle')
    s.rect(210,242,350,57);s.text(385,250,'证书指纹查询账户',21,BLUE,True,'middle');s.text(385,277,'user / access / bandwidth / quota',18,INK,False,'middle')
    s.text(295,352,'携带账户信息与协议限制',19,GRAY,False,'middle')
    s.rect(25,410,550,48,'#E8F5EF','#5D9F88');s.text(300,424,'之后复用长连接，后台 PING / PONG 保活',21,GREEN,True,'middle')
    return s.save()


def disconnect():
    s = SVG('10-1-主动断开连接')
    steps = ['用户点击“断开”，停止心跳和重连',
             '关闭 TLS 通道和底层 TCP 连接',
             '客户端保留任务和续传位置',
             '服务端释放会话资源']
    for i, step in enumerate(steps):
        y = i * 76 + 4
        s.rect(16, y, 568, 54)
        s.text(300, y + 13, step, 25, INK, False, 'middle')
        if i < len(steps) - 1:
            s.line(300, y + 54, 300, y + 73, True)
    s.line(16, 316, 584, 316, color='#C9D5DF')
    s.text(16, 341, '网络中断', 28, BLUE, True)
    s.text(174, 344, '1 秒后重试，间隔翻倍至 30 秒', 25, INK)
    s.text(16, 412, '认证失败', 28, BLUE, True)
    s.text(174, 415, '停止重试，检查证书和身份', 25, INK)
    return s.save()


def concurrency():
    s=SVG('11-1-多任务共享连接',600,470)
    for i,label in enumerate(['上传 A','上传 B','下载 C','下载 D']):
        x=10+i*150;s.box(x,10,130,55,label,sz=23);s.line(x+65,65,x+65,106);s.line(x+65,106,300,106)
    s.line(300,106,300,136,True)
    s.box(45,140,510,76,'最多 4 个文件任务并发',['单个文件每次只等待一个块的确认'])
    s.line(300,216,300,246,True)
    for i,(label,color) in enumerate([('DATA A','#E9F0FA'),('READ C','#DDEEF8'),('DATA B','#E9F0FA'),('READ D','#DDEEF8')]):
        s.rect(12+i*148,251,140,49,color);s.text(82+i*148,266,label,21,BLUE,True,'middle')
    s.text(300,314,'一个 TLS/TCP 连接，request 关联各自响应',20,INK,False,'middle')
    s.line(300,340,300,363,True)
    s.box(45,367,510,77,'服务端按账户共享令牌桶',['上传 + 下载 + 多连接共用同一带宽预算'])
    return s.save()


def checkpoint():
    s=SVG('11-2-持久化检查点',600,470)
    steps=[('DATA(id, offset, payload)','接收一个文件块'),('pwrite + fsync','先把数据写完并同步'),('数据库保存检查点 cp','再持久化可恢复的偏移'),('ACK(next_offset)','最后向发送方确认')]
    for i,(a,b) in enumerate(steps):
        y=i*92;s.box(20,y,560,68,a,[b],sz=22)
        if i<3:s.line(300,y+68,300,y+90,True)
    s.rect(20,382,560,70,'#E8F5EF','#5D9F88')
    s.text(300,396,'已确认偏移 ≤ 检查点 ≤ 已落盘长度',23,GREEN,True,'middle')
    s.text(300,426,'正式发布前，还要验证完整长度与 SHA-256。',19,INK,False,'middle')
    return s.save()


def resume():
    s=SVG('11-2-恢复上传与下载')
    s.box(20,0,560,67,'同一账户 + 同一任务 UUID',['重新建立 TLS，完成 HELLO / WELCOME'])
    for x in [155,445]:s.route([(300,67),(300,88),(x,88),(x,112)])
    s.box(15,116,275,68,'恢复上传',['RESUME(id)'])
    s.box(310,116,275,68,'恢复下载',['RESUME(id, offset, prefix)'],sz=23)
    for x in [155,445]:s.line(x,184,x,213,True)
    s.box(15,217,275,122,'服务端偏移为准',['READY 返回 offset','客户端核对源文件','及已传前缀'],sz=22)
    s.box(310,217,275,122,'客户端偏移为准',['先截断未确认尾部','服务端核对源文件','及客户端前缀'],sz=22)
    for x in [155,445]:s.route([(x,339),(x,356),(300,356)],arrow=False)
    s.line(300,356,300,380,True)
    s.box(20,384,560,66,'校验通过后从检查点继续',['身份不匹配则拒绝恢复，防止拼接不同文件'])
    return s.save()


class Sequence:
    """Three-party sequence diagrams: roles across, time downwards."""
    def __init__(self,name,actors,w=1200,h=540,positions=None):
        self.s=SVG(name,w,h)
        self.x=positions or [180,600,1020]
        self.h=h
        self.lifelines=[]
        self.label_bounds=[]
        for x,actor in zip(self.x,actors):
            self.lifelines.append((x,len(self.s.e)))
            self.s.line(x,50,x,h-8,color='#A7B8C7',dash=True)
            self.s.rect(x-150,0,300,48,'#F1F5FA','#7399B9',5)
            self.s.text(x,12,actor,25,BLUE,True,'middle')

    def label(self,x,y,t,size=23,color=INK,anchor='middle'):
        f=FONTS[False];cmap=f.getBestCmap()
        width=sum(f['hmtx'][cmap.get(ord(c),'.notdef')][0] for c in t)*size/f['head'].unitsPerEm
        left=x-width/2 if anchor=='middle' else (x-width if anchor=='end' else x)
        self.label_bounds.append((left-5,left+width+5,y-2,y+size+3))
        self.s.text(x,y,t,size,color,False,anchor)

    def msg(self,src,dst,y,label,reply=False,size=23):
        a,b=self.x[src],self.x[dst]
        self.s.line(a,y,b,y,True,color=BLUE,dash=reply)
        self.label((a+b)/2,y-28,label,size)

    def self_message(self,actor,y,label,left=False,size=23):
        x=self.x[actor];dx=-48 if left else 48
        self.s.route([(x,y),(x+dx,y),(x+dx,y+18),(x,y+18)])
        self.label(x-12 if left else x+12,y-28,label,size,anchor='end' if left else 'start')

    def loop(self,y,bottom,label):
        self.s.rect(95,y,1010,bottom-y,'none','#A9BACC')
        self.s.rect(95,y,68,28,'#F1F5FA','#A9BACC')
        self.s.text(129,y+4,'loop',19,BLUE,True,'middle')
        self.label(1090,y+4,label,19,GRAY,anchor='end')

    def note(self,x,y,w,text,color=GRAY,size=22):
        self.s.rect(x,y,w,36,'#F7F9FB','#CAD5DF')
        self.s.text(x+w/2,y+7,text,size,color,False,'middle')

    def save(self):
        # Leave small gaps in lifelines behind labels instead of adding text boxes.
        for x,index in self.lifelines:
            cuts=sorted((top,bottom) for left,right,top,bottom in self.label_bounds if left<=x<=right)
            y=50;pieces=[]
            for top,bottom in cuts:
                if top>y:pieces.append(f'M{x},{y} L{x},{min(top,self.h-8)}')
                y=max(y,bottom)
            if y<self.h-8:pieces.append(f'M{x},{y} L{x},{self.h-8}')
            self.s.e[index]=f'<path d="{" ".join(pieces)}" fill="none" stroke="#A7B8C7" stroke-width="1.8" stroke-dasharray="5 5"/>'
        return self.s.save()


def upload_sequence():
    q=Sequence('10-2-上传时序',['客户端','服务端','临时文件与任务库'])
    q.loop(204,344,'还有数据，每块最多 64 KiB')
    q.msg(0,1,98,'PUT_INIT(id, path, size, sha256)',size=22)
    q.msg(1,2,140,'检查权限、目标与配额，建立任务',size=22)
    q.msg(1,0,182,'READY(offset, prefix)',reply=True)
    q.msg(0,1,247,'DATA(id, offset, payload)')
    q.msg(1,2,287,'写盘并 fsync，再保存检查点',size=22)
    q.msg(1,0,327,'ACK(offset)',reply=True)
    q.msg(0,1,389,'FINISH(id)')
    q.msg(1,2,432,'校验并提交文件，记录 complete',size=22)
    q.msg(1,0,475,'RESULT(complete, size, sha256)',reply=True,size=22)
    q.label(600,502,'ACK 确认已持久化的偏移；RESULT 确认整个文件完成。',21,GREEN)
    return q.save()


def download_sequence():
    q=Sequence('10-3-下载时序',['客户端','本地临时文件与任务库','服务端'])
    q.loop(146,344,'还有数据，逐块读取并确认')
    q.msg(0,2,93,'GET_INIT(id, path)')
    q.msg(2,0,132,'READY(size, sha256, offset)',reply=True)
    q.msg(0,2,186,'READ(id, offset)')
    q.msg(2,0,223,'DATA(offset, payload)',reply=True)
    q.msg(0,1,260,'写盘并 fsync，保存本地检查点',size=22)
    q.msg(0,2,297,'ACK(id, offset)')
    q.msg(2,0,334,'ACK(offset)',reply=True)
    q.msg(0,1,382,'校验完整长度与 SHA-256')
    q.msg(0,2,424,'FINISH(id, sha256)')
    q.msg(2,0,466,'复核源文件后返回 RESULT(complete)',reply=True)
    q.msg(0,1,508,'提交正式文件，保存完成状态',size=22)
    return q.save()


def ca_sequence():
    q=Sequence('12-1-CA签发时序',['实验 CA','服务器身份','客户端身份'])
    q.self_message(0,98,'生成 CA 密钥与自签根证书',size=22)
    q.self_message(1,147,'生成私钥与 CSR',size=22)
    q.msg(1,0,193,'提交 CSR（公钥、申请身份）',size=22)
    q.self_message(0,237,'设置 serverAuth / SAN，用 CA 私钥签名',size=21)
    q.msg(0,1,294,'签发服务器证书 server.pem',reply=True,size=22)
    q.self_message(2,336,'生成私钥与 CSR',left=True,size=22)
    q.msg(2,0,381,'提交客户端 CSR',size=23)
    q.self_message(0,425,'设置 clientAuth，用 CA 私钥签名',size=22)
    q.msg(0,2,480,'签发客户端证书 alice.pem / bob.pem',reply=True,size=23)
    q.label(600,506,'CSR 不携带私钥；客户端把自己的证书与私钥封装为 P12。',20,GRAY)
    return q.save()


def mutual_sequence():
    q=Sequence('12-2-双向验证时序',['客户端','服务器','账户数据库'])
    q.msg(1,0,100,'服务器证书 + 私钥持有证明',size=22)
    q.self_message(0,153,'验证 CA、有效期、用途与主机名',size=22)
    q.msg(0,1,218,'客户端证书 + 私钥持有证明',size=22)
    q.self_message(1,270,'验证 CA、有效期与证书用途',size=22)
    q.note(54,318,682,'双向 TLS 建立，后续 SFT1 消息受加密与完整性保护',size=21)
    q.msg(0,1,393,'HELLO')
    q.msg(1,2,433,'用客户端证书指纹查询账户',size=22)
    q.msg(2,1,473,'user、r / rw、bandwidth、quota',reply=True,size=22)
    q.msg(1,0,513,'WELCOME(账户信息与限制)',reply=True,size=22)
    return q.save()


def formal():
    s=SVG('13-TLA与TLC模型检查')
    steps=[('选定上传、下载与恢复规则','抽象成块、检查点、确认和状态'),('TLA+ 描述 Init 与 Next','定义状态变量与每一步允许的动作'),('TLC 枚举有限可达状态','包括任务交错及有界故障'),('检查不变量与条件活性','违反性质时，输出具体反例路径')]
    for i,(a,b) in enumerate(steps):
        y=i*99;s.box(20,y,560,74,a,[b],sz=23)
        if i<3:s.line(300,y+74,300,y+96,True)
    s.text(300,413,'ack ≤ cp ≤ disk ≤ Blocks',27,BLUE,True,'middle')
    s.text(300,448,'确认不能超前于持久化检查点。',19,GRAY,False,'middle')
    return s.save()


def rgb(s):return RGBColor.from_string(s.lstrip('#'))
def textbox(slide,x,y,w,h,text,size=20,color=INK,bold=False,font='等线',align=PP_ALIGN.LEFT):
    sh=slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))
    tf=sh.text_frame;tf.clear();tf.word_wrap=True
    tf.margin_left=tf.margin_right=0;tf.margin_top=tf.margin_bottom=0
    for i,line in enumerate(text.split('\n')):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph();p.alignment=align;p.space_after=Pt(7)
        p.font.name=font;p.font.size=Pt(size);p.font.bold=bold;p.font.color.rgb=rgb(color)
        r=p.add_run();r.text=line;r.font.name=font;r.font.size=Pt(size);r.font.bold=bold;r.font.color.rgb=rgb(color)
        pr=r._r.get_or_add_rPr()
        pr.append(parse_xml(f'<a:ea xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" typeface="{font}"/>'))
    return sh


def rect(slide,x,y,w,h,fill=PALE,line='#CADCED'):
    sh=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,Inches(x),Inches(y),Inches(w),Inches(h))
    sh.fill.solid();sh.fill.fore_color.rgb=rgb(fill);sh.line.color.rgb=rgb(line);sh.line.width=Pt(.7)
    return sh


def code(slide,x,y,w,h,title,lines,size=14):
    rect(slide,x,y,w,h)
    textbox(slide,x+.17,y+.12,w-.34,.3,title,14,BLUE,True)
    textbox(slide,x+.17,y+.55,w-.34,h-.62,lines,size,INK,font='Menlo')


image_counter=0
def diagram(slide,asset,x,y,w,h):
    global image_counter
    svg,png=asset;sh=slide.shapes.add_picture(str(png),Inches(x),Inches(y),Inches(w),Inches(h))
    image_counter+=1
    part=Part(PackURI(f'/ppt/media/sft1-diagram-{image_counter}.svg'),'image/svg+xml',slide.part.package,svg.read_bytes())
    rid=slide.part.relate_to(part,'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image')
    ext=parse_xml(f'<a:extLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:ext uri="{{96DAC541-7B7A-43D3-8B79-37D633B846F1}}"><asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{rid}"/></a:ext></a:extLst>')
    sh._element.blipFill.blip.append(ext)
    sh.name=svg.stem
    sh._element.nvPicPr.cNvPr.set('descr',svg.stem)


prs=Presentation(str(TEMPLATE))
layout=prs.slides[1].slide_layout
# Preserve all original masters, layout relationships and assets in this copy.
for entry in list(prs.slides._sldIdLst):
    prs.part.drop_rel(entry.rId);prs.slides._sldIdLst.remove(entry)
titles=[]


def new_slide(chapter,title,left_title,right_title,notes):
    s=prs.slides.add_slide(layout)
    for sh in list(s.shapes):s.shapes._spTree.remove(sh._element)
    textbox(s,.39,.24,1.06,.65,str(chapter),36,'#FFFFFF',True,align=PP_ALIGN.CENTER)
    textbox(s,1.85,.43,7.55,.47,title,27,'#000000',True)
    if left_title:
        textbox(s,.54,1.16,5.95,.36,left_title,20,BLUE,True)
    if right_title:
        textbox(s,6.88,1.16,5.88,.36,right_title,20,BLUE,True)
    s.notes_slide.notes_text_frame.text=notes
    titles.append(title)
    return s


s=new_slide(9,'SFT1 协议分层与报头','协议栈','固定报头 20 B',
    '前面演示的上传和下载，用的都是我们自己设计的应用层协议 SFT1。它规定客户端和服务器要说什么。下面的 TLS 负责加密、校验数据和验证双方身份，TCP 负责把字节按顺序送到。Mac 上用苹果的 Network.framework 建立 TLS 连接，Python 服务端用 ssl 模块调用 OpenSSL。\n再看右边。每条消息开头固定占 20 个字节，后面可以跟不同长度的 JSON 和文件数据。接收方读完报头，就知道后面两段各要读多少字节。比如发一次心跳，JSON 里只有一对花括号，占 2 个字节，也没有文件数据，所以整条消息一共 22 个字节。')
diagram(s,layers(),.54,1.67,5.95,4.66)
diagram(s,header(),6.88,1.67,5.88,4.66)

s=new_slide(9,'按长度解析 SFT1 消息','','',
    '假设客户端连续发了两条消息。服务器第一次读，可能连第一条都没收全，也可能两条一起到了。那怎么知道第一条在哪里结束？这就要用到刚才报头里的两个长度。\n顺着流程图往下看。服务器先等够 20 个字节，检查消息类型和长度，再按报头写的字节数读出 JSON 和文件数据。这样就能刚好取出一条消息，剩下的字节留给下一条。两段数据各自最多 64 KiB。如果报头给的长度超了，服务器就关闭连接。')
diagram(s,parser_flow(),.45,1.35,7.4,5.14)
textbox(s,8.14,1.34,4.65,.4,'Python 接收代码',20,BLUE,True)
code(s,8.14,1.95,4.65,2.12,'protocol.py / read_frame（节选）',
    'async with asyncio.timeout(\n    partial_timeout):\n    raw = first + await reader.readexactly(\n        HEADER.size - 1)',11.4)
textbox(s,8.14,4.37,4.65,.4,'为什么能划分消息边界',20,BLUE,True)
textbox(s,8.14,4.91,4.65,1.18,'readexactly(n) 等待读满 n 字节\n两段正文分别限制为 64 KiB\n读取超时或连接结束则退出',17)

s=new_slide(10,'会话初始化与断开连接','建立身份与会话','主动断开连接',
    '点“连接”以后，客户端先连上 TCP，再和服务器互相验证证书。验证通过，客户端发 HELLO，服务器回 WELCOME，告诉客户端这次登录的是谁、有什么权限。后面浏览目录、上传和下载，都用这条连接。\n如果我自己点“断开”，客户端会停掉心跳和自动重连，关闭底层的 TCP 连接。已经传到哪里会保留下来，下次连上还能继续。\n如果是传到一半突然断网，客户端会自己再连。第一次等 1 秒，失败就等 2 秒，再等 4 秒，每次翻倍，最长等 30 秒。这就是退避重连。连上后重新验证身份，我可以选中原来的任务点“继续”。如果是证书或身份验证出了问题，客户端就停下来，等我改好再连。')
diagram(s,initialize(),.54,1.67,5.95,4.66)
diagram(s,disconnect(),6.88,1.67,5.88,4.66)

s=new_slide(10,'文件上传：分块写入与确认','','',
    '把本地文件复制到服务器目录时，客户端先告诉服务器三件事：文件放在哪儿、有多大、算出来的哈希值是多少。服务器检查这个账户能不能写、空间够不够，回一个 READY，客户端就开始分块上传。\n看图里的 ACK。服务器每收到一块，先把数据写到磁盘，再记下已经存到哪个位置，最后才回 ACK。这样客户端就知道下一块该从哪里发。等整个文件传完，服务器还要核对文件大小和 SHA-256 哈希值。都对得上，才把临时文件存为正式文件，回复上传完成。')
diagram(s,upload_sequence(),.62,1.17,12.05,5.4225)

s=new_slide(10,'文件下载：拉取、落盘与完成确认','','',
    '把服务器上的文件拖到本地时，客户端会先问文件有多大、哈希值是多少。接下来由客户端一块一块地要数据。比如发一个 READ，告诉服务器从哪个位置开始读，服务器就把那一块发回来。\n这次数据存在 Mac 上，所以要等 Mac 把这一块写进临时文件、记好进度，再发确认。等所有块收齐，Mac 会算一遍整个文件的哈希，和下载前拿到的值对照。大小和哈希都一致，再等服务器确认源文件没变，这次下载才算完成。')
diagram(s,download_sequence(),.62,1.17,12.05,5.4225)

s=new_slide(11,'重点模块：多文件并发','任务在同一连接中交错','调度、隔离与带宽控制',
    '比如我一边上传文件 A，一边下载文件 B。A 发完一块，还在等服务器确认，这时 B 就可以发请求去取下一块。两个文件的消息在同一条连接上交替传，每个请求都有编号，收到回复就知道它对应哪一个请求。客户端最多可以同时传四个文件。\n限速是按账户算的。前面给 Bob 设了每秒 256 KiB，如果他同时上传和下载，这些任务一起分这份带宽。把限速设成零，就恢复不限速。')
diagram(s,concurrency(),.54,1.67,5.95,4.66)
code(s,6.88,1.68,5.88,1.85,'TransferEngine.swift / schedule（节选）',
    'for task in eligible where !task.directory {\n    if running.count >= 4 { break }\n    // 目录依赖检查后，launch(task)\n}',12.8)
textbox(s,7.02,3.81,5.6,.35,'并发的三个边界',21,BLUE,True)
textbox(s,7.02,4.26,5.55,1.25,'每文件：块按偏移确认，避免乱序追加\n每连接：request 匹配响应，报文完整发送\n每账户：最多 4 个活动传输，共享带宽',18)
textbox(s,7.02,5.76,5.55,.42,'0 = 不限速；262144 B/s = 256 KiB/s',18,GREEN,True)

s=new_slide(11,'重点模块：断点续传','确认必须晚于持久化','恢复前核对文件身份',
    '刚才演示里，一个文件传到一半，我点了暂停，断开再连，进度还能接得上。它怎么知道从哪儿继续？靠的是接收方上次写到磁盘、也记进任务记录的那个位置。上传时看服务器的记录，下载时看 Mac 本地的记录。\n点“继续”以后，双方用原来的任务编号找到这次传输，再核对源文件和已经传过的那一段。都对得上，才从记下的位置往后传。如果中途换过文件，哪怕名字一样，哈希也会暴露这个变化，程序就会停下来。')
diagram(s,checkpoint(),.54,1.67,5.95,4.66)
diagram(s,resume(),6.88,1.67,5.88,4.66)

s=new_slide(12,'CA 签名：申请与签发证书','','',
    '前面连接时，我们选过一个 CA 证书和一个 P12 文件。这两样是怎么来的？我们先在本地建一个实验 CA，给它生成密钥，再用它自己的私钥签出根证书。\n服务器和客户端也各自生成一对密钥，把自己的公钥和申请的身份放进证书请求，交给 CA。私钥留在自己手里。CA 用自己的私钥签发证书，说明这个公钥属于谁。服务器证书里还写了它能用在哪些主机名或 IP 地址上。客户端则把签好的证书和自己的私钥打包，得到连接时选的 P12。')
diagram(s,ca_sequence(),.62,1.17,12.05,5.4225)

s=new_slide(12,'双向验证：证书、身份与账户','','',
    '现在拿这些证书连一次。Mac 先检查服务器证书是不是由它信任的 CA 签发、有没有过期，还要看证书上的名字和我们填的服务器地址能不能对上。服务器也会检查客户端的证书。握手过程中，双方都要证明自己持有证书对应的私钥。这就是双向验证。\n回想刚才的演示，Mac 选错 CA，它就不信任服务器。换成服务器不信任的客户端证书，拒绝连接的就是服务器。两边都通过以后，服务器再用客户端证书的指纹查账户，所以 Alice 登录后可以读写，Bob 用只读账户登录就只能下载和浏览。')
diagram(s,mutual_sequence(),.62,1.17,12.05,5.4225)

report=json.loads((ROOT/'formal/results/summary.json').read_text())
count=next(r['distinct'] for r in report['results'] if r['case']=='upload_concurrent')
s=new_slide(13,'TLA+ 与 TLC 形式化验证','把规则写成可检查的模型','正确模型与故意修改后的反例',
    '刚才一直在说，收到一块数据，要先存好进度，再发确认。要是把这两步换个顺序，会发生什么？我们用 TLA+ 写下传输、断线和恢复的规则，再让 TLC 在设定的块数和故障次数内，把可能的执行顺序逐个检查一遍。光是两个任务同时上传，它就检查了 8464 个不同的状态。\n再看右边这个故意改错的版本。第一块已经写进磁盘，进度记录还停在零，客户端却已经收到了第一块的确认。要是恰好在这时候断线，两边记住的进度就对不上。TLC 找到了这条出错路径，也就说明了为什么协议要求先记进度，再回 ACK。')
diagram(s,formal(),.54,1.67,5.95,4.66)
textbox(s,6.98,1.77,5.65,.42,f'正确双任务上传：{count:,} 个不同状态',22,BLUE,True)
textbox(s,6.98,2.35,5.55,.68,'6 个正确配置检查无错误\n14 个配置的实际结果均符合预期',18)
rect(s,6.88,3.35,5.88,1.48)
textbox(s,7.05,3.49,5.54,.35,'故意提前 ACK：TLC 找到反例',20,RED,True)
textbox(s,7.05,4.01,5.5,.36,'disk = 1    cp = 0    ack = 1',19,INK,font='Menlo')
textbox(s,7.05,4.45,5.5,.29,'违反 AckDurable：已确认数据尚未保存检查点',16,RED)
textbox(s,6.98,5.18,5.6,.42,'验证范围',20,BLUE,True)
textbox(s,6.98,5.69,5.6,.58,'有限块数与故障次数的状态机检查\n结论不等于整个源码的完整正确性证明',17)

prs.core_properties.title='SFT1 协议设计与重点模块'
prs.core_properties.author='俞乐楠'
prs.core_properties.subject='软件与系统安全实验 1B；第 9–13 部分'
prs.save(OUT)
(BUILD/'manifest.json').write_text(json.dumps({'output':str(OUT),'source_template':str(TEMPLATE),'slide_count':len(prs.slides),'titles':titles,'diagrams':image_counter,'fonts':['等线','Menlo'],'slide_size_emu':[prs.slide_width,prs.slide_height]},ensure_ascii=False,indent=2))
print(OUT)
print(f'{len(prs.slides)} slides; {image_counter} embedded SVG diagrams; template layout retained')
