import asyncio
import concurrent.futures
import hashlib
import json
import logging
import logging.handlers
import os
import re
import socket
import signal
import ssl
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from weakref import WeakValueDictionary

from .database import Database
from .protocol import CHUNK, Fault, Frame, Kind, integer, read_frame, string
from .storage import Jail, file_fault, partial_identity, parts, write_chunk


class Bucket:
    """One shared budget for both directions and every connection of a user."""
    def __init__(self):
        self.lock = asyncio.Lock()
        self.tokens = CHUNK
        self.updated = time.monotonic()

    async def acquire(self, count, rate):
        if rate == 0:
            return  # Zero explicitly disables application-level bandwidth throttling.
        async with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(CHUNK, self.tokens + (now-self.updated)*rate)
                self.updated = now
                if self.tokens >= count:
                    self.tokens -= count
                    return
                await asyncio.sleep((count-self.tokens)/rate)


class Server:
    def __init__(self, config):
        self.config = config
        self.data = Path(config["data"]).resolve()
        self.database = Database(self.data)
        self.ip_counts = Counter()
        self.user_counts = Counter()
        self.active = defaultdict(dict)
        self.locks = WeakValueDictionary()
        self.buckets = defaultdict(Bucket)
        self.connections = set()
        self.tasks = set()
        self.socket = None
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="sft-disk")
        self.log = logging.getLogger(f"sft.{id(self)}")
        self.log.setLevel(logging.INFO)
        handler = logging.handlers.RotatingFileHandler(self.data / "private/server.log", maxBytes=1024*1024, backupCount=3)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.log.addHandler(handler)

    async def work(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self.pool, fn, *args)

    def tls(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(self.config["certificate"], self.config["key"])
        context.load_verify_locations(self.config["ca"])
        return context

    async def start(self):
        self.context = self.tls()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setblocking(False)
        self.socket.bind((self.config.get("host", "127.0.0.1"), self.config.get("port",8443)))
        self.socket.listen(64)
        self.port = self.socket.getsockname()[1]
        self.accept_task = asyncio.create_task(self.accept())
        self.log.info("ready port=%s", self.port)

    async def accept(self):
        loop = asyncio.get_running_loop()
        while True:
            raw, address = await loop.sock_accept(self.socket)
            ip = address[0]
            # Admission is before TLS, including unauthenticated sockets.
            if sum(self.ip_counts.values()) >= self.config.get("max_connections",32) or self.ip_counts[ip] >= self.config.get("per_ip",8):
                raw.close()
                continue
            self.ip_counts[ip] += 1
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            task = asyncio.create_task(self.accepted(raw, ip))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def accepted(self, raw, ip):
        writer = None
        try:
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader(limit=2*CHUNK+20)
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await loop.connect_accepted_socket(lambda: protocol, raw, ssl=self.context, ssl_handshake_timeout=5, ssl_shutdown_timeout=2)
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            session = Session(self, reader, writer, ip)
            self.connections.add(session)
            try:
                await session.run()
            finally:
                self.connections.discard(session)
        except (ssl.SSLError, OSError, TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:
            self.log.exception("connection failure")
        finally:
            if writer:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 3)
                except (Exception, asyncio.CancelledError):
                    pass
            else:
                raw.close()
            self.ip_counts[ip] -= 1
            if not self.ip_counts[ip]:
                del self.ip_counts[ip]

    async def close(self):
        if getattr(self, "closed", False):
            return
        self.closed = True
        self.accept_task.cancel()
        self.socket.close()
        await asyncio.gather(self.accept_task, return_exceptions=True)
        for session in tuple(self.connections):
            session.writer.close()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.pool.shutdown(wait=True)
        self.database.db.close()
        for handler in list(self.log.handlers):
            handler.close()
            self.log.removeHandler(handler)


class Session:
    def __init__(self, server, reader, writer, ip):
        self.server, self.reader, self.writer, self.ip = server, reader, writer, ip
        self.user = None
        self.jail = None
        self.send_lock = asyncio.Lock()
        self.pending = set()
        self.ids = set()
        self.control_times = []
        self.transfers = set()
        self.owned_locks = {}

    async def send(self, frame):
        async with self.send_lock:
            self.writer.write(frame.encode())
            await asyncio.wait_for(self.writer.drain(), 15)

    async def run(self):
        try:
            hello = await read_frame(self.reader, idle_timeout=10)
            if hello.kind != Kind.HELLO or hello.data:
                raise Fault("PROTOCOL", "首个消息必须是HELLO")
            der = self.writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
            self.user = await self.server.work(self.server.database.user, hashlib.sha256(der).hexdigest())
            if self.server.user_counts[self.user["name"]] >= 2:
                raise Fault("LIMIT", "同一账户最多两个连接")
            self.server.user_counts[self.user["name"]] += 1
            self.jail = await self.server.work(Jail, self.server.data / "users" / self.user["name"])
            await self.send(Frame(Kind.WELCOME, hello.request, {"user":self.user["name"],"bandwidth":self.user["bandwidth"],"quota":self.user["quota"],"chunk":CHUNK,"max_active":4,"version":1,"access":self.user["access"]}))
            while True:
                frame = await read_frame(self.reader)
                if not frame.request or frame.request in self.ids or len(self.pending) >= 16:
                    raise Fault("PROTOCOL", "重复请求编号或并发请求过多")
                self.ids.add(frame.request)
                task = asyncio.create_task(self.handle(frame))
                self.pending.add(task)
                task.add_done_callback(self.pending.discard)
        except Fault as fault:
            try:
                await self.send(Frame(Kind.ERROR, 0, {"code":fault.code,"message":fault.message}))
            except (OSError, TimeoutError):
                pass
        finally:
            if self.pending:
                await asyncio.gather(*self.pending, return_exceptions=True)
            if self.jail:
                for transfer in self.transfers:
                    self.server.active[self.user["name"]].pop(transfer, None)
                self.owned_locks.clear()
                if not self.server.active[self.user["name"]]:
                    self.server.active.pop(self.user["name"], None)
                self.server.user_counts[self.user["name"]] -= 1
                if not self.server.user_counts[self.user["name"]]:
                    self.server.user_counts.pop(self.user["name"], None)
                self.jail.close()

    async def handle(self, frame):
        try:
            if frame.kind not in (Kind.DATA,Kind.ACK,Kind.READ,Kind.PING):
                now = time.monotonic()
                self.control_times = [t for t in self.control_times if now-t < 1]
                if len(self.control_times) >= 30:
                    raise Fault("RATE", "操作过于频繁，请稍后重试")
                self.control_times.append(now)
            self.user = await self.server.work(self.server.database.user, None, self.user["name"])
            if frame.data and frame.kind != Kind.DATA:
                raise Fault("PROTOCOL", "该消息不允许数据载荷")
            result = await self.dispatch(frame)
            await self.send(result)
            if frame.kind not in (Kind.PING,Kind.DATA,Kind.READ,Kind.ACK):
                await self.server.work(self.server.database.audit, self.user["name"], frame.kind.name, {"ip":self.ip,"request":frame.request})
        except Fault as fault:
            await self.send(Frame(Kind.ERROR, frame.request, {"code":fault.code,"message":fault.message}))
            if fault.code == "AUTH":
                self.writer.close()
        except OSError as exc:
            fault = file_fault(exc)
            await self.send(Frame(Kind.ERROR, frame.request, {"code":fault.code,"message":fault.message}))
        except (ConnectionError,TimeoutError):
            self.writer.close()
        except Exception:
            self.server.log.exception("request failure user=%s kind=%s", self.user["name"], frame.kind.name)
            try:
                await self.send(Frame(Kind.ERROR,frame.request,{"code":"INTERNAL","message":"服务器操作失败，请检查服务端日志"}))
            except (OSError,TimeoutError):
                pass
        finally:
            self.ids.discard(frame.request)

    def claim(self, transfer):
        active = self.server.active[self.user["name"]]
        if transfer in active and active[transfer] is not self:
            raise Fault("BUSY", "任务正在另一连接上执行")
        if transfer not in active and len(active) >= 4:
            raise Fault("LIMIT", "账户同时传输上限为4")
        active[transfer] = self
        self.transfers.add(transfer)
        lock = self.server.locks.setdefault(transfer, asyncio.Lock())
        self.owned_locks[transfer] = lock

    def release(self, transfer):
        self.server.active[self.user["name"]].pop(transfer, None)
        self.transfers.discard(transfer)
        self.owned_locks.pop(transfer, None)
        # Lock remains until connection teardown; waiters may still own it.

    def transfer_id(self, meta):
        value = string(meta,"id",36)
        try:
            if str(uuid.UUID(value)) != value:
                raise ValueError()
        except ValueError as exc:
            raise Fault("INPUT", "无效传输编号") from exc
        return value

    def partial(self, transfer):
        return self.server.data / "private" / f"{transfer}.part"

    async def record(self, transfer):
        return await self.server.work(self.server.database.get, transfer, self.user["name"])

    async def ready(self, record):
        if record["direction"] == "upload" and record["status"] not in ("complete","cancelled","failed") and not self.partial(record["id"]).exists():
            if await self.server.work(self.jail.exists, record["path"]):
                size,digest = await self.server.work(self.jail.identity, record["path"])
                if (size,digest) == (record["size"],record["sha256"]):
                    await self.server.work(self.server.database.update, record["id"], size, "complete")
                    record["offset"] = size
                    record["status"] = "complete"
        meta = {k:record[k] for k in ("id","direction","path","size","sha256","offset","status")}
        if record["status"] == "complete":
            return Kind.RESULT, meta
        if record["status"] in ("cancelled","failed"):
            raise Fault("STATE", "该任务已经取消或失败，请创建新任务")
        if record["direction"] == "upload":
            meta["prefix"] = await self.server.work(partial_identity,self.partial(record["id"]),record["offset"])
        return Kind.READY, meta

    async def dispatch(self, frame):
        kind, meta, rid = frame.kind, frame.meta, frame.request
        if self.user["access"] != "rw":
            if kind in (Kind.MKDIR,Kind.DELETE,Kind.COPY,Kind.PUT_INIT,Kind.DATA):
                raise Fault("PERMISSION","此证书绑定账户只有读取权限")
            if kind in (Kind.RESUME,Kind.FINISH):
                record = self.server.database.get(self.transfer_id(meta),self.user["name"])
                if record["direction"] == "upload":
                    raise Fault("PERMISSION","此证书绑定账户只有读取权限")
        if kind == Kind.PING:
            return Frame(Kind.PONG,rid,{"bandwidth":self.user["bandwidth"],"access":self.user["access"]})
        if kind == Kind.LIST:
            path = meta.get("path","")
            parts(path,True)
            return Frame(Kind.LIST_RESULT,rid,await self.server.work(self.jail.listing,path,integer(meta,"cursor",0,10000)))
        if kind == Kind.DELETE:
            path = string(meta,"path")
            parts(path)
            def delete():
                database = self.server.database
                with database.lock:
                    records = database.db.execute("SELECT * FROM transfers WHERE user=?", (self.user["name"],)).fetchall()
                    affected = [r for r in records if r["path"] == path or r["path"].startswith(path+"/")]
                    if any(r["status"] in ("active","paused") for r in affected):
                        raise Fault("STATE", "请先完成或取消该路径的传输任务")
                    self.jail.delete(path)
                    for r in affected:
                        if r["direction"] == "upload" and r["status"] == "complete":
                            database.update(r["id"], status="failed")
            await self.server.work(delete)
            return Frame(Kind.OK,rid)
        if kind == Kind.COPY:
            source, target = string(meta,"source"), string(meta,"path")
            parts(source); parts(target)
            transfer = str(uuid.uuid4())
            temporary = self.partial(transfer)
            record = None
            try:
                size, digest = await self.server.work(self.jail.identity, source)
                record = await self.server.work(self.server.database.create,transfer,self.user["name"],"upload",target,size,digest)
                def copy():
                    with self.jail.file(source) as fd:
                        with open(temporary,"xb") as out:
                            offset = 0
                            while offset < size:
                                block = os.pread(fd,min(CHUNK,size-offset),offset)
                                if not block:
                                    raise Fault("CHANGED","源文件发生变化")
                                out.write(block); offset += len(block)
                            out.flush(); os.fsync(out.fileno())
                    if self.jail.identity(source) != (size,digest):
                        raise Fault("CHANGED","源文件发生变化")
                    from .storage import digest_fd
                    with open(temporary,"rb") as check:
                        if digest_fd(check.fileno()) != digest:
                            raise Fault("INTEGRITY","复制校验失败")
                    self.jail.commit(temporary,target)
                await self.server.work(copy)
                await self.server.work(self.server.database.update,transfer,size,"complete")
            except BaseException:
                if record:
                    await self.server.work(self.server.database.update,transfer,None,"failed")
                raise
            finally:
                temporary.unlink(missing_ok=True)
            return Frame(Kind.OK,rid)
        if kind == Kind.MKDIR:
            await self.server.work(self.jail.mkdir,string(meta,"path"))
            return Frame(Kind.OK,rid)
        if kind in (Kind.PUT_INIT,Kind.GET_INIT):
            transfer = self.transfer_id(meta)
            path = string(meta,"path")
            parts(path)
            if kind == Kind.PUT_INIT:
                size = integer(meta,"size",0,self.server.config.get("max_file",1024**3))
                sha = string(meta,"sha256",64)
                if not re.fullmatch("[0-9a-f]{64}",sha):
                    raise Fault("INPUT", "SHA-256格式错误")
                try:
                    old = await self.record(transfer)
                except Fault as exc:
                    if exc.code != "NOT_FOUND":
                        raise
                    old = None
                if not old and await self.server.work(self.jail.exists,path):
                    raise Fault("CONFLICT", "已有同名文件，请改名后重试")
                direction = "upload"
            else:
                size, sha = await self.server.work(self.jail.identity,path)
                if size > self.server.config.get("max_file",1024**3):
                    raise Fault("LIMIT", "文件超过大小上限")
                direction = "download"
            self.claim(transfer)
            try:
                record = await self.server.work(self.server.database.create, transfer,self.user["name"],direction,path,size,sha)
                if direction == "upload" and record["status"] != "complete" and not self.partial(transfer).exists():
                    if record["offset"]:
                        raise Fault("INTEGRITY", "续传临时文件丢失")
                    fd = os.open(self.partial(transfer),os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
                    os.fsync(fd)
                    os.close(fd)
                response, body = await self.ready(record)
                if response == Kind.RESULT:
                    self.release(transfer)
                return Frame(response,rid,body)
            except BaseException:
                self.release(transfer)
                raise
        transfer = self.transfer_id(meta)
        record = await self.record(transfer)
        if kind == Kind.RESUME:
            self.claim(transfer)
            try:
                async with self.server.locks[transfer]:
                    if record["direction"] == "download" and record["status"] != "complete":
                        size,sha = await self.server.work(self.jail.identity,record["path"])
                        if (size,sha) != (record["size"],record["sha256"]):
                            raise Fault("CHANGED", "服务器源文件发生变化")
                        offset = integer(meta,"offset",0,size)
                        _,prefix = await self.server.work(self.jail.identity,record["path"],offset)
                        if prefix != string(meta,"prefix",64):
                            raise Fault("INTEGRITY", "续传前缀校验失败")
                        await self.server.work(self.server.database.update,transfer,offset,"active")
                        record["offset"] = offset
                    response,body = await self.ready(record)
                    if response != Kind.RESULT:
                        await self.server.work(self.server.database.update,transfer,None,"active")
                    else:
                        self.release(transfer)
                    return Frame(response,rid,body)
            except BaseException:
                self.release(transfer)
                raise
        if kind == Kind.CANCEL and transfer not in self.server.active[self.user["name"]]:
            self.claim(transfer)
        if self.server.active[self.user["name"]].get(transfer) is not self:
            if kind == Kind.FINISH and record["status"] == "complete":
                return Frame(Kind.RESULT,rid,{"id":transfer,"status":"complete","sha256":record["sha256"],"size":record["size"]})
            raise Fault("STATE", "请先恢复该任务")
        async with self.server.locks[transfer]:
            record = await self.record(transfer)
            if kind in (Kind.PAUSE,Kind.CANCEL):
                if record["status"] == "complete":
                    self.release(transfer)
                    return Frame(Kind.RESULT,rid,{"id":transfer,"status":"complete"})
                status = "paused" if kind == Kind.PAUSE else "cancelled"
                await self.server.work(self.server.database.update,transfer,None,status)
                if kind == Kind.CANCEL and record["direction"] == "upload":
                    self.partial(transfer).unlink(missing_ok=True)
                self.release(transfer)
                return Frame(Kind.OK,rid,{"offset":record["offset"],"status":status})
            if record["status"] != "active":
                raise Fault("STATE", "任务未处于传输状态")
            if kind == Kind.DATA:
                if record["direction"] != "upload" or not frame.data:
                    raise Fault("PROTOCOL", "无效上传数据")
                offset = integer(meta,"offset",0,record["size"])
                if offset+len(frame.data) <= record["offset"]:
                    return Frame(Kind.ACK,rid,{"offset":record["offset"]})
                if offset != record["offset"] or offset+len(frame.data) > record["size"]:
                    raise Fault("OFFSET", "数据偏移或长度错误")
                await self.server.buckets[self.user["name"]].acquire(len(frame.data),self.user["bandwidth"])
                await self.server.work(write_chunk,self.partial(transfer),offset,frame.data)
                await self.server.work(self.server.database.update,transfer,offset+len(frame.data))
                return Frame(Kind.ACK,rid,{"offset":offset+len(frame.data)})
            if kind == Kind.READ:
                offset = integer(meta,"offset",0,record["size"])
                if record["direction"] != "download" or offset != record["offset"]:
                    raise Fault("OFFSET", "下载偏移错误")
                data = await self.server.work(self.jail.read,record["path"],offset,min(CHUNK,record["size"]-offset))
                if not data and offset < record["size"]:
                    raise Fault("CHANGED", "源文件长度发生变化")
                await self.server.buckets[self.user["name"]].acquire(len(data),self.user["bandwidth"])
                return Frame(Kind.DATA,rid,{"offset":offset},data)
            if kind == Kind.ACK:
                offset = integer(meta,"offset",record["offset"],min(record["size"],record["offset"]+CHUNK))
                if record["direction"] != "download":
                    raise Fault("STATE", "该方向不接收下载确认")
                await self.server.work(self.server.database.update,transfer,offset)
                return Frame(Kind.ACK,rid,{"offset":offset})
            if kind == Kind.FINISH:
                if record["offset"] != record["size"]:
                    raise Fault("INTEGRITY", "文件尚未完整传输")
                if record["direction"] == "upload":
                    if not self.partial(transfer).exists() and await self.server.work(self.jail.exists,record["path"]):
                        size,digest = await self.server.work(self.jail.identity,record["path"])
                    else:
                        digest = await self.server.work(partial_identity,self.partial(transfer),record["size"])
                        size = record["size"]
                    if (size,digest) != (record["size"],record["sha256"]):
                        await self.server.work(self.server.database.update,transfer,None,"failed")
                        self.partial(transfer).unlink(missing_ok=True)
                        self.release(transfer)
                        raise Fault("INTEGRITY", "文件完整性校验失败")
                    if self.partial(transfer).exists():
                        await self.server.work(self.jail.commit,self.partial(transfer),record["path"])
                else:
                    size,digest = await self.server.work(self.jail.identity,record["path"])
                    if (size,digest) != (record["size"],record["sha256"]) or meta.get("sha256") != digest:
                        raise Fault("INTEGRITY", "下载完整性校验失败")
                await self.server.work(self.server.database.update,transfer,None,"complete")
                self.release(transfer)
                return Frame(Kind.RESULT,rid,{"id":transfer,"status":"complete","size":record["size"],"sha256":record["sha256"]})
            raise Fault("PROTOCOL", "不支持的消息")


async def serve(config):
    server = Server(config)
    await server.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(name, stop.set)
    print(f"安全文件服务器已启动 {config.get('host','127.0.0.1')}:{server.port}",flush=True)
    try:
        await stop.wait()
    finally:
        await server.close()
