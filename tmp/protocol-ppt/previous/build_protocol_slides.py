"""Build the eight-slide protocol talk from the supplied PowerPoint template.

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
    s=SVG('09-1-协议分层')
    s.box(20,4,560,69,'SFT1  应用层协议（OSI 第 7 层）',['消息、文件操作、分块确认与断点续传'])
    s.line(300,73,300,96,True)
    s.box(20,98,560,126,'TLS  安全通道',['Transport Layer Security  传输层安全协议','位于 SFT1 与 TCP 之间','加密 + 完整性保护 + 双向身份认证'],fill='#E5F2FB')
    s.line(300,224,300,247,True)
    s.box(20,249,560,69,'TCP  传输层（OSI 第 4 层）',['可靠、有序的字节流'])
    s.line(300,318,300,341,True)
    s.box(20,343,560,69,'IP  网络层（OSI 第 3 层）',['寻址与路由'])
    s.text(300,435,'TLS 不固定对应 OSI 的某一个层。',19,GRAY,False,'middle')
    return s.save()


def header():
    s=SVG('09-1-20字节报头')
    s.text(12,4,'字节偏移',16,GRAY)
    for x,txt in [(90,'0'),(210,'8'),(330,'16'),(450,'24'),(568,'31 位')]:s.text(x,4,txt,16,GRAY)
    fields=[(0,'magic = "SFT1"  (32 bit)'),(8,'request  (32 bit)'),(12,'metadata_length  (32 bit)'),(16,'payload_length  (32 bit)')]
    for idx,(off,t) in enumerate(fields):
        row=0 if idx==0 else idx+1;y=34+row*48
        s.text(32,y+14,str(off),18,GRAY)
        s.rect(90,y,488,48);s.text(334,y+13,t,22,BLUE,True,'middle')
    s.text(32,96,'4',18,GRAY)
    for x,w,t in [(90,122,'version: 8'),(212,122,'kind: 8'),(334,244,'flags: 16')]:
        s.rect(x,82,w,48);s.text(x+w/2,97,t,19,BLUE,True,'middle')
    s.text(32,291,'20',18,GRAY)
    s.rect(90,274,488,60,'#F9FBFD');s.text(334,284,'UTF-8 JSON 元数据',22,BLUE,True,'middle');s.text(334,311,'metadata_length 字节',18,GRAY,False,'middle')
    s.rect(90,334,488,60,'#F9FBFD');s.text(334,344,'二进制数据载荷',22,BLUE,True,'middle');s.text(334,371,'payload_length 字节，可为 0',18,GRAY,False,'middle')
    s.text(90,414,'固定报头 20 B / 大端序 / 两段正文各 ≤ 64 KiB',19,INK)
    s.text(90,443,'request 关联请求；JSON 中 id 标识持久任务。',18,GRAY)
    return s.save()


def parser_flow():
    s=SVG('09-2-消息解析流程')
    steps=[('读满 20 字节报头','不足则等待；超时结束连接'),('校验格式与长度','magic、version、flags、kind、长度上限'),('按长度读取 JSON 与载荷','JSON 必须是对象；长度按字节计算'),('按 kind 分派，按 request 对应响应','处理完继续读取下一条消息')]
    for i,(a,b) in enumerate(steps):
        y=8+i*106;s.box(15,y,510,76,a,[b],sz=22)
        if i<3:s.line(270,y+76,270,y+102,True)
    s.route([(525,364),(570,364),(570,46),(525,46)])
    s.text(300,444,'格式失效：ERROR / 关闭连接，避免继续误读。',20,RED,False,'middle')
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
    s=SVG('10-1-主动断开连接')
    steps=[('用户点击“断开”','停止心跳与自动重连'),('取消底层 NWConnection','未完成请求返回连接错误'),('客户端保存任务状态','保留任务记录和已有检查点'),('服务端感知连接结束','释放会话、活动槽和目录描述符')]
    for i,(a,b) in enumerate(steps):
        y=i*93;s.box(20,y,560,70,a,[b],sz=22)
        if i<3:s.line(300,y+70,300,y+90,True)
    s.text(300,385,'没有单独的 SFT1 BYE 消息。',22,ORANGE,True,'middle')
    s.text(300,418,'断开 ≠ 取消任务；重连后可继续。',21,INK,False,'middle')
    s.text(300,448,'意外断线：退避重连；手动断开：不自动重连。',18,GRAY,False,'middle')
    return s.save()


def copyflow():
    s=SVG('10-2-COPY处理流程')
    s.text(300,0,'COPY(source, path)',25,BLUE,True,'middle')
    labels=[('账户与路径','检查 rw、源路径和目标路径'),('任务与配额','计算源身份，预留目标空间'),('复制到临时文件','逐块复制，flush + fsync'),('校验并提交','核对 SHA-256，禁止覆盖地提交'),('保存 complete，返回 OK','失败则清理临时文件，返回 ERROR')]
    for i,(a,b) in enumerate(labels):
        y=44+i*82;s.box(35,y,530,63,a,(),sz=22);s.text(300,y+38,b,19,INK,False,'middle')
        if i<4:s.line(300,y+63,300,y+79,True)
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


def signing():
    s=SVG('12-CA证书签发')
    s.box(40,0,520,69,'实验 CA：密钥对 + 自签根证书',['ca.key 用于签名，ca.pem 是信任锚'])
    s.box(15,118,270,92,'服务器生成密钥和 CSR',['公钥 + 申请身份','私钥留在本地'],sz=21)
    s.box(315,118,270,92,'客户端生成密钥和 CSR',['公钥 + 申请身份','私钥留在本地'],sz=21)
    s.route([(150,118),(150,93),(250,93),(250,69)])
    s.route([(450,118),(450,93),(350,93),(350,69)])
    s.text(38,84,'提交 CSR',18,GRAY);s.text(458,84,'提交 CSR',18,GRAY)
    s.line(300,69,300,246,True)
    s.box(40,250,520,66,'CA 用私钥签署证书内容',['将主体身份与公钥绑定'])
    s.route([(300,316),(300,337),(150,337),(150,352)])
    s.route([(300,316),(300,337),(450,337),(450,352)])
    s.box(15,356,270,92,'服务器证书',['serverAuth + SAN'],sz=22)
    s.box(315,356,270,92,'客户端证书',['clientAuth','证书 + 私钥封装为 P12'],sz=22)
    return s.save()


def mutual():
    s=SVG('12-双向TLS认证')
    for x,label in [(100,'客户端'),(500,'服务器')]:
        s.box(x-75,0,150,48,label,sz=24);s.line(x,48,x,365,color='#9BB9D3',dash=True)
    s.line(500,96,100,96,True);s.text(300,66,'服务器证书 + 私钥持有证明',21,BLUE,True,'middle')
    s.rect(25,118,550,66);s.text(300,129,'客户端验证：可信 CA、有效期、用途',21,INK,False,'middle');s.text(300,156,'并核对连接目标的主机名 / IP',21,INK,False,'middle')
    s.line(100,240,500,240,True);s.text(300,211,'客户端证书 + 私钥持有证明',21,BLUE,True,'middle')
    s.rect(25,263,550,66);s.text(300,274,'服务器验证：可信 CA、有效期、用途',21,INK,False,'middle');s.text(300,301,'再通过证书指纹定位 Alice / Bob',21,INK,False,'middle')
    s.rect(25,365,550,62,'#E8F5EF','#5D9F88');s.text(300,377,'协商会话密钥，保护后续 SFT1 数据',22,GREEN,True,'middle');s.text(300,405,'r / rw 与带宽由账户配置决定',19,INK,False,'middle')
    s.text(300,448,'图为职责示意，未展开 TLS 内部消息。',18,GRAY,False,'middle')
    return s.save()


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
    textbox(s,.54,1.16,5.95,.36,left_title,20,BLUE,True)
    textbox(s,6.88,1.16,5.88,.36,right_title,20,BLUE,True)
    s.notes_slide.notes_text_frame.text=notes
    titles.append(title)
    return s


s=new_slide(9,'SFT1 协议分层与报头','左：各层负责什么','右：固定 20 字节报头',
    '口播：SFT1 是自定义应用层协议，位于 TLS 保护的 TCP 长连接之上。TLS 建立加密、完整性保护和双向身份认证的通道。TCP 属于传输层，提供可靠有序字节流；IP 负责寻址与路由。TLS 不是严格的 OSI 某一层。\n报头由 magic、version、kind、flags、request 和两段长度组成。JSON 和二进制载荷长度都是字节数。request 关联单次响应，任务 UUID 跨连接保持。\n来源：server/ex1b/protocol.py；macos/Sources/SafeTransferCore/Protocol.swift；TLS https://www.rfc-editor.org/rfc/rfc8446.html#section-1')
diagram(s,layers(),.54,1.67,5.95,4.66)
diagram(s,header(),6.88,1.67,5.88,4.66)

s=new_slide(9,'按长度解析 SFT1 消息','左：接收与解析流程','右：Python 实现节选',
    '口播：TCP 是字节流，一次读取可能只有半条消息，也可能包含多条消息。先读满报头并验证，再按声明长度读取正文。服务端用 readexactly，Swift 端用缓存循环解析。输入上限和超时限制资源消耗。\n来源：server/ex1b/protocol.py read_frame。代码为原文连续片段，省略了错误处理和类型检查；左侧流程含这些检查。')
diagram(s,parser_flow(),.54,1.67,5.95,4.66)
code(s,6.88,1.68,5.88,2.27,'protocol.py / read_frame（节选）',
    'first = await asyncio.wait_for(\n    reader.readexactly(1), idle_timeout)\nasync with asyncio.timeout(partial_timeout):\n    raw = first + await reader.readexactly(\n        HEADER.size - 1)',12.8)
textbox(s,7.05,4.22,5.55,.43,'再校验报头，并按 mlen / dlen 读取正文',18,BLUE,True)
textbox(s,7.05,4.84,5.5,1.18,'JSON 与载荷分别限制为 64 KiB\nSwift 端缓存半包，循环提取完整消息\n业务错误携带原 request，连接可继续',18)

s=new_slide(10,'会话初始化与断开连接','左：建立身份与会话','右：主动断开连接',
    '口播：先建立 TCP 和双向 TLS，再发送 HELLO。服务端用证书指纹找到用户，返回 WELCOME，后续复用连接并维护心跳。\n用户点击断开时，客户端取消心跳和重连任务，关闭底层 NWConnection，终止等待中的请求并保存任务状态。服务端感知连接结束后释放会话资源，保留可恢复的数据。SFT1 没有单独的 BYE 消息，也不能把取消本地执行 Task 说成发出 CANCEL 协议消息。PAUSE 保留任务和连接；CANCEL 结束指定传输并清理临时数据。意外断线会按 1、2、4、8、16、30 秒退避重连，手动断开不自动重连。\n来源：TransferEngine.swift disconnect / execute / lost；Connection.swift disconnect / fail；server.py Session.run / Server.accepted。')
diagram(s,initialize(),.54,1.67,5.95,4.66)
diagram(s,disconnect(),6.88,1.67,5.88,4.66)

s=new_slide(10,'COPY 与文件管理操作','左：以 COPY 为例','右：其他操作复用同一处理框架',
    '口播：这一页以服务端内部的 COPY 展示请求处理框架：检查身份权限和路径，执行操作，返回响应。COPY 会预留配额，写入临时文件，校验并禁止覆盖地提交。DELETE、MKDIR、LIST 也通过相同分派框架处理，但有各自的权限和结果。\nCOPY 不承载跨端上传下载。本地与远端之间的复制粘贴由客户端转为 PUT_INIT / GET_INIT 等文件传输消息。此页按演示节奏压缩模块，完整逐模块时序图仍见 docs/protocol-demo-script.md。\n来源：server/ex1b/server.py Session.dispatch；server/ex1b/storage.py；SafeTransferApp/FileActions.swift。')
diagram(s,copyflow(),.54,1.67,5.95,4.66)
for y,a,b in [(1.77,'DELETE  删除','检查 rw 与任务占用，安全删除后返回 OK'),(2.85,'MKDIR  创建目录','检查 rw，逐级创建目录后返回 OK'),(3.93,'LIST  查询目录','检查路径，分页返回 LIST_RESULT')]:
    textbox(s,6.98,y,5.65,.36,a,22,BLUE,True)
    textbox(s,6.98,y+.46,5.6,.55,b,18)
rect(s,6.88,5.17,5.88,1.08)
textbox(s,7.04,5.3,5.54,.32,'共同逻辑：校验 → 执行 → 响应 / ERROR',18,BLUE,True)
textbox(s,7.04,5.78,5.5,.32,'COPY 是远端复制；跨端粘贴走上传 / 下载。',16,ORANGE)

s=new_slide(11,'重点模块：多文件并发','左：任务在同一连接中交错','右：调度、隔离与带宽控制',
    '口播：最多四个文件任务并发，目录依赖先完成。每个文件只等待一个未确认块，不同文件的请求交错进入一个 TLS/TCP 连接。客户端串行发送，服务端发送锁保持报文完整，request 关联响应。上传使用 DATA/ACK，下载使用 READ/DATA/ACK。服务端按账户共享令牌桶，上传下载和多个连接共用预算。bandwidth=0 表示不限速。\n来源：TransferEngine.swift schedule / upload / download；Connection.swift request；server.py Session.send / claim / Bucket.acquire。代码省略了目录依赖检查，用中文注释标示。')
diagram(s,concurrency(),.54,1.67,5.95,4.66)
code(s,6.88,1.68,5.88,1.85,'TransferEngine.swift / schedule（节选）',
    'for task in eligible where !task.directory {\n    if running.count >= 4 { break }\n    // 目录依赖检查后，launch(task)\n}',12.8)
textbox(s,7.02,3.81,5.6,.35,'并发的三个边界',21,BLUE,True)
textbox(s,7.02,4.26,5.55,1.25,'每文件：块按偏移确认，避免乱序追加\n每连接：request 匹配响应，报文完整发送\n每账户：最多 4 个活动传输，共享带宽',18)
textbox(s,7.02,5.76,5.55,.42,'0 = 不限速；262144 B/s = 256 KiB/s',18,GREEN,True)

s=new_slide(11,'重点模块：断点续传','左：确认必须晚于持久化','右：恢复前核对文件身份',
    '口播：上传先写盘并 fsync，再保存数据库检查点，然后返回 ACK。断开之后，以接收端持久化位置恢复。上传以服务端偏移为准，客户端核对完整源文件和前缀；下载以客户端偏移为准，先截断未确认尾部，再请服务端核对源文件和前缀。相同 UUID 定位同一任务，身份不匹配就拒绝，防止拼接不同版本。传完还要完整长度与 SHA-256 校验，通过后才发布正式文件。\n来源：server.py DATA / RESUME / FINISH；storage.py write_chunk / partial_identity；TransferEngine.swift upload / download；Disk.swift prepare / commit。')
diagram(s,checkpoint(),.54,1.67,5.95,4.66)
diagram(s,resume(),6.88,1.67,5.88,4.66)

s=new_slide(12,'CA 签名与双向身份验证','左：证书如何签发','右：握手中怎样验证双方',
    '口播：实验 CA 自签根证书。服务器和客户端各自生成私钥和 CSR，CSR 携带公钥及申请身份，不携带私钥。CA 用自己的私钥签署证书，将主体身份和公钥绑定。服务器证书含 serverAuth 与 SAN，客户端证书含 clientAuth。P12 包含客户端证书和私钥。\n客户端验证服务器证书链、有效期、用途和主机身份。服务端也验证客户端证书，再把指纹映射到账户。握手还要求证明持有对应私钥。两端协商密钥，后续用对称密钥保护 SFT1 数据。CA 签名不是加密证书。r/rw 是账户配置，不写死在证书里。图只展示职责，不逐条展开 TLS 1.2/1.3 握手顺序。\n来源：server/ex1b/cli.py certificates；server.py Server.tls；Connection.swift parameters；RFC 8446 https://www.rfc-editor.org/rfc/rfc8446.html#section-1。')
diagram(s,signing(),.54,1.67,5.95,4.66)
diagram(s,mutual(),6.88,1.67,5.88,4.66)

report=json.loads((ROOT/'formal/results/summary.json').read_text())
count=next(r['distinct'] for r in report['results'] if r['case']=='upload_concurrent')
s=new_slide(13,'TLA+ 与 TLC 形式化验证','左：把规则写成可检查的模型','右：正确模型与故意修改后的反例',
    '口播：TLA+ 是描述状态及其变化规则的规范语言，TLC 是有限状态模型检查器。我们建立上传、下载和恢复模型，将文件抽象成数据块，探索交错及有界故障。关键不变量是 ack 不超过 cp，cp 不超过 disk，正式文件必须完整。\n已有 14 个配置结果全部符合预期，其中 6 个正确配置无错误，5 个故意修改模型的反例，1 个去掉公平性的活性反例，2 个完成可达性见证。双任务上传 8464 个不同状态。提前 ACK 的反例 disk=1、cp=0、ack=1 违反 AckDurable。\n这是有限参数模型检查，不是整个源码的完整正确性证明。模型没有涵盖 TLS、目录管理、令牌桶和新增权限配置，未完成模型到代码精化证明。活性需要有界故障和弱公平等假设，CHECK_DEADLOCK FALSE 不能宣称无死锁。\n来源：formal/SFT1Upload.tla；formal/SFT1Download.tla；formal/upload_concurrent.cfg；formal/results/summary.json；formal/results/upload_mutant_early_ack.log。')
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
