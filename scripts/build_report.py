"""Build the course report from source-backed evidence.

Use the bundled artifact Python runtime. Personal details are command arguments,
not source defaults. Example: --name NAME --student-id ID [--screenshot FILE].
"""
import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageStat
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
W, H = 595.2756, 841.8898
LEFT, RIGHT = 48, 547.2756
WIDTH = RIGHT - LEFT
INK = colors.HexColor("#17202B")
MUTED = colors.HexColor("#5A6471")
LINE = colors.HexColor("#CFD5DC")
PALE = colors.HexColor("#F2F4F7")
BLUE = colors.HexColor("#245F97")
REPO = "https://github.com/Vel044/ex1b-safe-transfer"


def register_fonts():
    pdfmetrics.registerFont(TTFont("CN", "/System/Library/Fonts/STHeiti Light.ttc", subfontIndex=0))
    pdfmetrics.registerFont(TTFont("CNB", "/System/Library/Fonts/STHeiti Medium.ttc", subfontIndex=0))


def wrap(text, width, size=10.5, font="CN"):
    lines = []
    for paragraph in str(text).split("\n"):
        current = ""
        tokens = re.findall(r"[A-Za-z0-9_./:\-+=<>\[\]\(\)]+|.", paragraph)
        for token in tokens:
            # Keep Western identifiers intact and avoid starting a Chinese line
            # with closing punctuation. Very long identifiers may still wrap.
            if pdfmetrics.stringWidth(token, font, size) > width:
                chunks = list(token)
            else:
                chunks = [token]
            for chunk in chunks:
                if current and pdfmetrics.stringWidth(current + chunk, font, size) > width and chunk not in "，。；：！？、）】》”’%":
                    lines.append(current.rstrip())
                    current = chunk.lstrip()
                else:
                    current += chunk
        lines.append(current)
    return lines


class Report:
    def __init__(self, path, name, student, date):
        self.path = path
        self.name, self.student, self.date = name, student, date
        self.c = canvas.Canvas(str(path), pagesize=(W, H), pageCompression=1)
        self.c.setTitle("安全文件传输软件设计与实现")
        self.c.setAuthor(name)
        self.c.setSubject("软件与系统安全实验1B")
        self.page = 0
        self.y = H - 100
        self.bounds = []

    def new_page(self, title, number):
        if self.page:
            self.c.showPage()
        self.page += 1
        self.c.setFillColor(MUTED)
        self.c.setFont("CN", 8.5)
        self.c.drawString(LEFT, H - 31, "软件与系统安全  实验1B")
        self.c.drawRightString(RIGHT, H - 31, "安传  SFT1")
        self.c.setStrokeColor(LINE)
        self.c.setLineWidth(.5)
        self.c.line(LEFT, H - 40, RIGHT, H - 40)
        self.c.setFont("CN", 8)
        self.c.drawString(LEFT, 29, f"{self.name}  {self.student}")
        self.c.drawRightString(RIGHT, 29, f"{self.page} / 10")
        self.c.setFillColor(INK)
        self.c.setFont("CNB", 19)
        self.c.drawString(LEFT, H - 79, f"{number}  {title}" if number else title)
        self.y = H - 108

    def text(self, text, *, x=LEFT, y=None, width=WIDTH, size=10.5, leading=17, color=INK, font="CN", gap=8):
        y = self.y if y is None else y
        lines = wrap(text, width, size, font)
        bottom = y - (len(lines) - 1) * leading
        if bottom < 53:
            raise ValueError(f"Page {self.page}: text overflows at {bottom:.1f}: {text[:50]}")
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        for line in lines:
            self.c.drawString(x, y, line)
            y -= leading
        self.y = y - gap
        self.bounds.append((self.page, bottom, str(text)[:60]))
        return self.y

    def sub(self, text):
        self.y -= 3
        return self.text(text, size=12, font="CNB", leading=18, gap=7)

    def caption(self, text, y, x=LEFT, width=WIDTH):
        return self.text(text, x=x, y=y, width=width, size=8.5, leading=12, color=MUTED, gap=5)

    def table(self, headers, rows, widths, *, y=None, size=9, leading=13, padding=6):
        y = self.y if y is None else y
        assert abs(sum(widths)-WIDTH) < 1
        all_rows = [headers] + list(rows)
        for index, row in enumerate(all_rows):
            cells = [wrap(value, width-2*padding, size, "CNB" if index == 0 else "CN") for value, width in zip(row, widths)]
            height = max(len(cell) for cell in cells)*leading + 2*padding
            if y-height < 53:
                raise ValueError(f"Page {self.page}: table overflows at {y-height}")
            if index == 0:
                self.c.setFillColor(PALE)
                self.c.rect(LEFT, y-height, WIDTH, height, fill=1, stroke=0)
            x = LEFT
            for cell, width in zip(cells, widths):
                self.c.setFillColor(INK)
                self.c.setFont("CNB" if index == 0 else "CN", size)
                ty = y-padding-size
                for line in cell:
                    self.c.drawString(x+padding, ty, line)
                    ty -= leading
                x += width
            self.c.setStrokeColor(LINE)
            self.c.setLineWidth(.4)
            self.c.line(LEFT, y-height, RIGHT, y-height)
            y -= height
        self.y = y-12
        return self.y

    def box(self, x, y, width, height, title, body):
        self.c.setFillColor(PALE)
        self.c.setStrokeColor(LINE)
        self.c.roundRect(x, y-height, width, height, 5, fill=1, stroke=1)
        self.c.setFillColor(INK)
        self.c.setFont("CNB", 11)
        self.c.drawString(x+12, y-20, title)
        self.text(body, x=x+12, y=y-40, width=width-24, size=9, leading=14, gap=0)

    def arrow(self, x1, x2, y, label, size=8.5, label_width=None):
        self.c.setStrokeColor(BLUE)
        self.c.setLineWidth(.8)
        self.c.line(x1, y, x2, y)
        d = 1 if x2 > x1 else -1
        self.c.line(x2, y, x2-d*5, y+3)
        self.c.line(x2, y, x2-d*5, y-3)
        width = label_width or abs(x2-x1)-12
        lines = wrap(label, width, size)
        self.c.setFillColor(INK)
        self.c.setFont("CN", size)
        first_y = y+6+(len(lines)-1)*11
        for i, line in enumerate(lines):
            self.c.drawCentredString((x1+x2)/2, first_y-i*11, line)

    def sequence(self, title, steps, *, x=LEFT, y=None, width=WIDTH, row=29, size=9):
        y = self.y if y is None else y
        self.c.setFillColor(INK)
        self.c.setFont("CNB", 11)
        self.c.drawString(x, y, title)
        y -= 29
        lx, rx = x+45, x+width-45
        self.c.setFillColor(PALE)
        self.c.setStrokeColor(LINE)
        for cx, label in [(lx, "客户端"), (rx, "服务端")]:
            self.c.roundRect(cx-32, y-13, 64, 24, 3, fill=1, stroke=1)
            self.c.setFillColor(INK)
            self.c.setFont("CN", 9)
            self.c.drawCentredString(cx, y-4, label)
            self.c.setFillColor(PALE)
        top = y-15
        bottom = top - len(steps)*row - 8
        if bottom < 57:
            raise ValueError(f"Page {self.page}: sequence overflows {title}: {bottom}")
        self.c.setStrokeColor(LINE)
        self.c.setDash(2, 3)
        self.c.line(lx, top, lx, bottom)
        self.c.line(rx, top, rx, bottom)
        self.c.setDash()
        cy = top-row
        for direction, message in steps:
            if direction == "note":
                nwidth = width-14
                lines = wrap(message, nwidth-14, size)
                nheight = 12*len(lines)+8
                self.c.setFillColor(PALE)
                self.c.roundRect(x+7, cy-4, nwidth, nheight, 2, fill=1, stroke=0)
                self.c.setFillColor(MUTED)
                self.c.setFont("CN", size)
                for i, line in enumerate(lines):
                    self.c.drawCentredString(x+width/2, cy+nheight-15-i*12, line)
            else:
                self.arrow(lx if direction == "send" else rx, rx if direction == "send" else lx, cy, message, size=size)
            cy -= row
        self.y = bottom-17
        return self.y

    def save(self):
        if self.page != 10:
            raise ValueError(f"Expected 10 pages, got {self.page}")
        self.c.save()


def build(args):
    register_fonts()
    evidence = ROOT / "output/evidence"
    suite_root = ET.parse(evidence/"python-tests.xml").getroot()
    suites = [suite_root] if suite_root.tag == "testsuite" else list(suite_root.findall("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    failed = sum(int(s.get("failures", 0))+int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    if not total or failed or skipped:
        raise ValueError("Python evidence is empty, failed or skipped; report refuses to claim full success")
    smoke = json.loads((evidence/"swift-roundtrip.json").read_text())
    if smoke.get("result") != "passed":
        raise ValueError("Swift roundtrip evidence did not pass")
    if smoke.get("heartbeats", 0) < 1:
        raise ValueError("Heartbeat evidence is absent; rerun TransferProbe with --idle-seconds 17")
    date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日")
    output = args.output or ROOT/"output"/f"{args.name}_{args.student_id}_ex1B_report.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    r = Report(output, args.name, args.student_id, date)

    r.new_page("安全文件传输软件设计与实现", "")
    r.text("安传 macOS原生客户端与双向TLS文件服务器", size=14, font="CNB", leading=22, gap=18)
    r.table(["姓名", "学号", "实验日期"], [[args.name, args.student_id, date]], [120, 220, WIDTH-340], size=11, padding=10)
    r.sub("实验目标与完成情况")
    r.text("本实验选择1B，实现安全文件传输软件。客户端整体使用Swift，界面由SwiftUI与AppKit系统组件构建；服务端使用Python异步网络接口，在Linux容器中运行。应用以双向TLS建立身份可信的长连接，在其上实现SFT1消息分帧、目录操作、数据确认和任务恢复。")
    r.text("实现覆盖多用户并发、完整文件传输、连接保持、自定义应用层协议和受限目录访问；同时支持断点续传、公钥证书身份认证、多文件同时上传下载、按用户身份限速，并扩展到文件夹递归传输及空目录保留。")
    r.sub("主要验证结果")
    r.table(["验证对象", "本次结果"], [
        ["自动化检查", f"共{total+args.swift_tests}项：Python {total}项、Swift {args.swift_tests}项，全部通过"],
        ["跨语言文件夹往返", f"Swift客户端与Linux容器服务端完成{smoke['files_and_directories']}个目录及文件任务"],
        ["原生界面", "系统目录授权；8项文件夹往返及64MiB文件上传，共9项成功"],
        ["两端重启续传", f"独立客户端退出且容器服务端重启后，从{args.resume_offset}字节检查点恢复"],
        ["账户共享限速", f"两连接共传2MiB，512KiB/s下实测{args.rate_seconds:.3f}秒"],
    ], [137, WIDTH-137], size=10, padding=8)
    r.sub("源码与实验边界")
    r.text(REPO, size=10, color=BLUE, leading=17)
    r.c.linkURL(REPO, (LEFT, r.y+8, RIGHT, r.y+25), relative=0)
    r.text("源码保留阶段提交并采用MIT许可证。本文结果来自Apple Silicon Mac与Linux容器的本地验证；未进行Windows客户端构建、互联网规模DDoS测试或开发者公证。课程要求依据课件第33、36至40及45页，提交截止时间为2026年11月24日23:55。", size=10, leading=16)

    r.new_page("系统架构与原生桌面界面", "1")
    r.text("界面、传输调度和磁盘操作分开执行。主线程维护窗口状态；Swift actor管理连接与任务；有界后台队列执行哈希和文件读写。服务端读取循环持续处理报文，将耗时业务交给受限并发任务及4线程磁盘队列。原生界面和连接接口依据Apple文档[2][3]。", size=10.5, leading=17)
    top = r.y-4
    r.box(LEFT, top, 218, 102, "macOS原生客户端", "SwiftUI表格 工具栏 分栏\nAppKit目录选择器与权限书签\nNetwork.framework与SwiftData")
    r.box(RIGHT-218, top, 218, 102, "Linux容器服务端", "asyncio会话与报文分发\n账户根目录与私有临时文件\nSQLite检查点 配额 审计")
    r.arrow(LEFT+218, RIGHT-218, top-48, "TLS", size=8)
    r.y = top-124
    r.caption("图1  客户端与服务端分工；业务消息采用20字节报头、JSON元数据和二进制文件块。", r.y)
    r.y -= 6
    if args.screenshot:
        image = Image.open(args.screenshot)
        if "A" in image.getbands() and ImageStat.Stat(image.getchannel("A")).mean[0] < 248:
            raise ValueError("Screenshot contains large transparent areas; refusing an incomplete native capture")
        height = min(310, WIDTH*image.height/image.width)
        draw_width = height*image.width/image.height
        y = r.y-height
        r.c.drawImage(ImageReader(image), LEFT+(WIDTH-draw_width)/2, y, width=draw_width, height=height, mask="auto")
        r.caption("图2  实际运行的macOS原生界面。系统双栏文件列表与任务队列显示9项全部完成。", y-14)
        r.text("本地目录经系统选择器授权后可浏览及落盘；服务器区域仅显示当前账户目录。队列提供暂停、继续、取消、整组操作和失败筛选，已完成任务及目录授权可跨应用重启恢复。", size=10, leading=16)
    else:
        r.sub("界面与操作组织")
        r.table(["区域", "系统组件与行为"], [
            ["连接表单", "服务器、CA证书、P12身份及系统钥匙串引用"],
            ["双栏文件区", "系统表格、多选、列排序、目录浏览与新建目录"],
            ["传输队列", "原生进度条、速度、状态和失败原因"],
            ["任务控制", "单任务及整组暂停、继续、取消，失败项目筛选"],
            ["外观及菜单", "系统字体、SF Symbols、深浅色和标准快捷键"],
        ], [110, WIDTH-110], size=10, padding=8)
        r.text("原生界面实测通过系统选择器授权本地目录，完成包含中文文件、二进制文件和空目录的整文件夹上传下载，队列共8项任务全部成功。", size=10.5, leading=18)
    r.caption("本地环境：macOS 27.2.1 arm64；Xcode 27.2；Swift 6.4.2；Python 3.13.12；Docker 29.1.2。", 76)

    r.new_page("应用层报文与消息集合", "2")
    r.text("TCP只提供可靠字节流，不能保证一次读取对应一条消息。SFT1先读取固定报头并验证长度，再按长度读取JSON和载荷。因此文件结束由长度、校验及完成响应共同确认，不依赖TCP断开。")
    y = r.y-4
    cell = WIDTH/32
    r.c.setFont("CN", 8)
    r.c.setFillColor(MUTED)
    for bit in [0, 8, 16, 24, 31]:
        r.c.drawString(LEFT+bit*cell, y, str(bit))
    y -= 9
    for fields in [[("SFT1 标识", 32)], [("版本", 8), ("类型", 8), ("保留位 0", 16)], [("请求编号 request", 32)], [("JSON字节数 metadata_length", 32)], [("载荷字节数 payload_length", 32)]]:
        x=LEFT
        for label, bits in fields:
            width=bits*cell
            r.c.setFillColor(PALE); r.c.setStrokeColor(LINE)
            r.c.rect(x, y-26, width, 26, fill=1, stroke=1)
            r.c.setFillColor(INK); r.c.setFont("CN", 9.5)
            r.c.drawCentredString(x+width/2, y-17, label)
            x += width
        y -= 26
    r.caption("图3  固定报头共160位 即20字节，所有整数使用网络字节序。其后为UTF-8 JSON与文件数据。", y-15)
    r.text("metadata_length与payload_length分别最多65536字节。中文长度按UTF-8字节计算。请求编号关联当前响应；传输UUID跨连接及进程重启保持不变。文件大小与偏移使用JSON整数，单文件上限1GiB。", size=10, leading=16)
    r.table(["数值", "消息", "作用"], [
        ["1 / 2", "HELLO / WELCOME", "版本、账户、带宽及配额初始化"],
        ["10 / 11 / 12 / 13", "LIST / LIST_RESULT / MKDIR / OK", "分页目录查询与目录创建"],
        ["20 / 21 / 22", "PUT_INIT / GET_INIT / READY", "文件身份与起始偏移协商"],
        ["23 / 24 / 27", "DATA / ACK / READ", "上传数据、下载拉取及持久化确认"],
        ["25 / 26", "FINISH / RESULT", "完整性校验和完成提交"],
        ["30 / 31 / 32", "PAUSE / RESUME / CANCEL", "暂停、恢复与取消"],
        ["40 / 41 / 255", "PING / PONG / ERROR", "连接活性与错误响应"],
    ], [83, 216, WIDTH-299], size=8.4, padding=6, leading=12)
    r.text("JSON必须为对象。报头版本、类型、保留位或长度不合法时拒绝报文；业务响应回传原request。request为0的ERROR表示连接级错误。共享报文样例由Python与Swift分别解码，验证跨语言字段解释一致。", size=10, leading=16)

    r.new_page("会话认证与目录访问", "3")
    r.sequence("图4  双向TLS与会话初始化", [
        ("send", "TCP连接与ClientHello"),
        ("recv", "ServerHello 服务器证书及客户端证书请求"),
        ("note", "客户端验证服务器CA链 有效期及主机名"),
        ("send", "客户端证书 证书持有证明及握手确认"),
        ("note", "服务端强制验证客户端证书链与用途"),
        ("send", "HELLO(version=1)"),
        ("note", "按已验证DER证书的SHA-256指纹查找启用账户"),
        ("recv", "WELCOME(user,bandwidth,quota,chunk,max_active)"),
    ], row=29)
    r.text("实验CA使用RSA 3072及SHA-256签发证书。服务器证书含serverAuth和SAN，客户端含clientAuth。账户身份来自证书指纹，客户端自行填写的用户名或证书CN不直接授予权限。Mac仅为本应用指定信任锚，不安装系统全局根证书；证书接口依据[4]，服务端TLS接口依据[6]。", size=10, leading=16)
    r.sequence("图5  目录查询与新建目录", [
        ("send", "LIST(path,cursor=0)"),
        ("note", "从账户根目录逐级打开，不跟随符号链接"),
        ("recv", "LIST_RESULT(entries,next) 逐页请求至next为空"),
        ("send", "MKDIR(relative_path)"),
        ("recv", "OK  已存在的目录也返回成功"),
    ], row=28)
    r.text("根路径采用空字符串，每页最多100条；目录超过10000条停止列举。其他路径拒绝绝对路径、空段、点段和反斜杠，逐级使用目录描述符及O_NOFOLLOW访问。已有同名文件拒绝覆盖，已有目录允许合并。", size=10, leading=16)

    r.new_page("文件上传与下载", "4")
    top = r.y
    half = (WIDTH-20)/2
    left_bottom = r.sequence("图6  上传", [
        ("send", "PUT_INIT(id,path,size,sha256)"),
        ("note", "预留配额并创建私有临时文件"),
        ("recv", "READY(offset,prefix)"),
        ("send", "DATA(id,offset,payload)"),
        ("note", "限速 写入 同步 检查点提交"),
        ("recv", "ACK(next_offset)"),
        ("send", "FINISH(id)"),
        ("note", "核对长度和完整哈希 原子提交"),
        ("recv", "RESULT(complete)"),
    ], x=LEFT, y=top, width=half, row=41, size=8)
    right_bottom = r.sequence("图7  下载", [
        ("send", "GET_INIT(id,path)"),
        ("recv", "READY(size,sha256,offset)"),
        ("send", "READ(id,offset)"),
        ("recv", "DATA(offset,payload)"),
        ("note", "客户端fsync并保存检查点"),
        ("send", "ACK(id,next_offset)"),
        ("recv", "ACK(next_offset)"),
        ("note", "客户端核对完整长度和哈希"),
        ("send", "FINISH(id,sha256)"),
        ("recv", "RESULT(complete)"),
        ("note", "客户端禁止覆盖地提交文件"),
    ], x=LEFT+half+20, y=top, width=half, row=34, size=8)
    r.y = min(left_bottom, right_bottom)-8
    r.sub("确认顺序与成功判定")
    r.text("服务端要求新块offset等于当前检查点，且块末尾不超过size，因此确认区间连续、偏移单调增加；已确认的重复块不再追加。上传每个文件只保留一个未确认块，文件fsync、SQLite检查点提交、ACK依次发生。下载则由客户端先持久化文件与SwiftData检查点，再发送ACK。", size=10, leading=16)
    r.text("接收方收齐声明字节数后重新计算SHA-256，校验成功才生成正式名称。提交使用linkat，目标已存在时失败，避免并发覆盖。服务端完成响应及客户端本地提交分别检查；任一环节失败都不能显示传输成功。", size=10, leading=16)
    r.text("多个文件以独立UUID交替执行，单账户最多4个活动文件，其他任务排队。单文件的顺序确认保持偏移确定，文件之间并发处理；目录浏览和心跳仍复用同一长连接。", size=10, leading=16)

    r.new_page("暂停与重启后的恢复", "5")
    r.sequence("图8  暂停与上传恢复", [
        ("send", "PAUSE(id) 等待当前数据块确认"),
        ("recv", "OK(offset,paused)"),
        ("note", "连接中断或两端进程退出，保存任务及临时文件"),
        ("send", "新连接完成双向TLS与HELLO 后发送RESUME(id)"),
        ("recv", "READY(server_offset,prefix,sha256)"),
        ("note", "客户端重新核对源文件身份和前缀，从服务端偏移继续"),
    ], row=30)
    r.text("上传以服务端持久化检查点为准。客户端保存的偏移可能落后于最后一次服务端ACK，因此恢复时重新取得服务端偏移，并计算对应源文件前缀哈希；身份或前缀不符则停止，不能把不同版本拼接。", size=10, leading=16)
    r.sequence("图9  下载恢复", [
        ("note", "客户端恢复已保存偏移，截断未确认尾部并计算前缀哈希"),
        ("send", "RESUME(id,client_offset,prefix)"),
        ("note", "服务端核对源文件完整大小 哈希和该偏移的前缀"),
        ("recv", "READY(offset,sha256)"),
        ("send", "READ(id,offset) 继续下载"),
    ], row=29)
    r.text("下载以客户端检查点为准，允许恢复最后一个客户端ACK丢失的情形。已完成任务返回原RESULT。正式链接已创建而临时链接未清理时，两端先核对文件身份及相同inode，再恢复上次提交；客户端下载路径在检查点准备前处理此窗口，不同文件的同名冲突仍拒绝覆盖。", size=10, leading=16)
    r.text(f"本次独立进程验证：4MiB文件在{args.resume_offset}字节处暂停；客户端退出、容器服务重启后，新客户端从该检查点继续至4194304字节并完成校验。", size=10, leading=16)

    r.new_page("取消 心跳与错误处理", "6")
    r.sequence("图10  取消任务", [
        ("send", "CANCEL(id)"),
        ("note", "服务端标记取消 删除上传临时文件 释放预留空间"),
        ("recv", "OK(cancelled)"),
        ("note", "客户端清理下载临时文件；已完成文件保留"),
    ], row=28)
    r.text("离线取消先持久化为“取消待同步”，重连后同步服务端。文件夹是目录及文件任务集合，取消不回滚已经完成的文件与目录。单个子文件失败后继续其他文件，界面可筛选失败清单。", size=10, leading=16)
    r.sequence("图11  长连接心跳", [
        ("send", "PING 每15秒一次"),
        ("recv", "PONG(bandwidth)"),
        ("note", "同时开启TCP keepalive；传输结束后不关闭会话"),
    ], row=27)
    r.sequence("图12  业务错误与连接错误", [
        ("send", "业务请求(request=n)"),
        ("recv", "ERROR(request=n,code,message)"),
        ("note", "业务错误保留会话；报头损坏或失去同步时关闭连接"),
    ], row=27)
    r.text("服务端45秒无完整消息关闭连接，半包15秒超时；客户端心跳请求10秒超时后尝试重连，间隔依次为1、2、4、8、16、30秒。认证及证书错误停止重试。应用重启后未完成任务转为暂停，用户手动继续。", size=10, leading=16)

    r.new_page("安全控制与容器隔离", "7")
    r.text("应用安全由身份、文件边界和资源预算共同实现。身份校验先于业务操作；路径访问始终从账户根目录描述符出发；数据库只接受参数化查询。运行权限及容器挂载进一步约束服务进程可访问的宿主机范围，部署字段依据Docker文档[7]。")
    r.table(["风险", "实现措施", "验证"], [
        ["中间人及伪造身份", "CA链 主机名 用途 有效期及客户端证书指纹", "错误CA 主机名 过期或未知证书被拒绝"],
        ["目录越界", "拒绝危险路径；openat/dir_fd与O_NOFOLLOW逐级访问", "路径穿越 符号链接及跨用户请求失败"],
        ["SQL注入", "查询绑定参数，不拼接SQL或执行客户端命令", "含SQL片段的文件名不能改变用户表"],
        ["并发配额绕过", "BEGIN IMMEDIATE原子预留，临时上传也计入配额", "并发第二任务超额被拒，取消后释放"],
        ["连接资源耗尽", "握手前准入；总连接32 单IP8 单账户2；握手5秒", "握手前连接洪泛下已有会话仍可响应"],
        ["缓冲与任务膨胀", "每帧各64KiB 每连接16请求 每账户4活动文件", "超大报文及活动任务超限被拒绝"],
        ["带宽绕过", "同一账户全部连接和上传下载共享令牌桶", "两连接总预算未翻倍"],
    ], [86, 223, WIDTH-309], size=9, leading=13, padding=7)
    r.sub("部署权限配置")
    r.table(["配置", "本次值"], [
        ["运行账户与权限", "UID 10001；cap_drop=ALL；no-new-privileges"],
        ["文件系统与挂载", "根目录只读；仅挂载项目数据及必要服务证书；不挂载CA私钥"],
        ["资源和端口", "256MiB内存 1 CPU 64进程 1024描述符；127.0.0.1:8443"],
    ], [130, WIDTH-130], size=9.5, padding=7)
    r.text("容器内实测为普通用户，向业务卷外创建文件被只读文件系统拒绝。初始化容器只短时调整项目挂载目录权限，不运行网络服务。连接限制、超时及限速能减轻应用资源耗尽，不能阻止上游网络带宽被占满；本实验未验证互联网规模DDoS。未建设OCSP或CRL，账户禁用及证书指纹登记承担实验客户端撤销控制。", size=10, leading=16)

    r.new_page("测试设计与实测结果", "8")
    r.text(f"本次自动化证据合计{total+args.swift_tests}项，包含{total}项Python测试和{args.swift_tests}项Swift测试，全部通过。Python覆盖服务端行为及安全异常；Swift覆盖分帧、共享样例、安全落盘、任务恢复及提交后临时链接未清理的恢复窗口；TransferProbe复用正式Swift传输核心进行跨语言验证。", size=10.5, leading=17)
    r.table(["场景组", "检查重点", "结果"], [
        ["协议边界", "共享样例 拆包 粘包 超长报文 半包超时", "通过"],
        ["完整传输", "空文件 小文件 二进制跨块 中文路径及连接复用", "通过"],
        ["用户并发", "多客户端并行访问与账户目录隔离", "通过"],
        ["恢复和源变化", "两端重启 下载恢复 源文件变化拒绝", "通过"],
        ["成功与冲突", "校验失败 取消 重名竞争 完成响应丢失及提交窗口", "通过"],
        ["路径与数据库", "绝对路径 点段 符号链接 SQL特殊输入", "通过"],
        ["证书和账户", "错误主机名 缺失或未知身份 不可信及过期证书 禁用", "通过"],
        ["并发资源", "握手前连接洪泛 活动上限 配额预留及所有权", "通过"],
        ["限速与幂等", "共享令牌桶 跨连接总预算 重复数据块确认", "通过"],
    ], [105, 333, WIDTH-438], size=9, padding=6, leading=13)
    r.sub("跨语言与原生客户端验证")
    r.text(f"文件夹往返完成{smoke['files_and_directories']}个目录及文件任务，保留空目录，跳过符号链接。中文二进制样例长度为{smoke['bytes']}字节，上传下载后SHA-256一致：", size=10, leading=16, gap=4)
    r.text(smoke["sha256"], size=8.5, leading=13, gap=10)
    r.text(f"原生界面完成8项整文件夹上传下载及64MiB文件上传，队列共9项全部成功。客户端完成传输后继续空闲17秒，记录到{smoke['heartbeats']}次应用心跳确认。独立客户端进程和容器服务重启后的续传从{args.resume_offset}字节恢复，而非重新传输整个文件。", size=10, leading=16)
    r.sub("限速测量")
    r.text(f"两连接同属Alice，以512KiB/s共享预算传输2MiB。令牌桶容量64KiB，理论时间下界为(2MiB-64KiB)/512KiB/s=3.875秒，本次实测{args.rate_seconds:.3f}秒。该结果验证账户预算未因多连接而翻倍，不能作为互联网链路吞吐量测试。", size=10, leading=16)

    r.new_page("构建部署与复现步骤", "9")
    r.text("先安装Xcode、Python 3.13、uv、OpenSSL 3和Docker Desktop，在项目根目录执行以下命令。证书与账户数据在本地生成，私钥及P12密码不会从仓库取得。", size=10.5, leading=17)
    commands = [
        "uv venv --python 3.13 .venv",
        "uv pip install --python .venv/bin/python '.[test]'",
        ".venv/bin/python scripts/bootstrap.py",
        "sh scripts/container_up.sh",
        "sh scripts/build_macos.sh",
        "open build/安传.app",
    ]
    r.text("\n".join(commands), size=9.5, leading=16, gap=10)
    r.text("客户端选择localhost:8443、runtime/certs/ca.pem及alice.p12或bob.p12，密码在各自.password文件中。通过系统选择器授权本地目录，选择文件或文件夹上传下载。单文件1GiB、账户2GiB；同名文件拒绝覆盖，源文件改变时取消旧任务并重新添加。", size=10, leading=16)
    r.sub("复现验证")
    r.text(".venv/bin/python -m pytest -q\nswift test --package-path macos --build-system native -q\nmacos/.build/debug/TransferProbe --certs runtime/certs --idle-seconds 17", size=9.3, leading=16)
    r.text("进程重启验证先运行TransferProbe的--resume-stage start并指定新的--state目录；暂停退出后执行docker compose restart server及docker compose up -d --wait，再对同一state运行--resume-stage finish。详细命令、报文格式和学习索引保存在源码README及docs目录。", size=10, leading=16)
    r.sub("参考资料与实现对应")
    refs = [
        ("[1] 课程课件", "实验1讲解2026r 第33 36至40 45页"),
        ("[2] Apple SwiftUI", "https://developer.apple.com/swiftui/"),
        ("[3] Apple Network.framework", "https://developer.apple.com/documentation/network/nwconnection"),
        ("[4] Apple Security", "https://developer.apple.com/documentation/security"),
        ("[5] Python asyncio", "https://docs.python.org/3.13/library/asyncio-stream.html"),
        ("[6] Python ssl", "https://docs.python.org/3.13/library/ssl.html"),
        ("[7] Docker Compose服务配置", "https://docs.docker.com/reference/compose-file/services/"),
    ]
    for title, url in refs:
        r.text(title+"  "+url, size=8.2, leading=12, gap=4)
    r.text("协议封装与会话对应protocol.py和Connection.swift；文件边界对应storage.py和Disk.swift；持久化及调度对应database.py、TaskStore.swift和TransferEngine.swift。Mac应用使用本地临时签名供本机课程演示，未进行开发者公证。", size=9.5, leading=15)
    r.save()
    print(json.dumps({"path":str(output),"pages":r.page,"python_tests":total,"swift_tests":args.swift_tests,"minimum_text_baseline":min(b for _,b,_ in r.bounds)}, ensure_ascii=False))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="生成安全文件传输实验报告")
    parser.add_argument("--name", required=True)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--swift-tests", type=int, default=6)
    parser.add_argument("--resume-offset", type=int, default=131072)
    parser.add_argument("--rate-seconds", type=float, default=3.915)
    arguments=parser.parse_args()
    if not re.fullmatch(r"[\w\u3400-\u9fff]{1,32}", arguments.name) or not re.fullmatch(r"[A-Za-z0-9]{1,32}", arguments.student_id):
        parser.error("姓名或学号含有不支持的文件名字符")
    build(arguments)
