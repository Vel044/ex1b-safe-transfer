"""Test-only reference peer. Production macOS client is entirely Swift."""
import asyncio
import hashlib
import ssl
import uuid

from ex1b.protocol import Frame,Kind,read_frame,Fault,CHUNK


class Peer:
    @classmethod
    async def open(cls,server,certs,user="alice",host="localhost",ca=None):
        context = ssl.create_default_context(cafile=str(ca or certs/"ca.pem"))
        if user:
            context.load_cert_chain(certs/f"{user}.pem",certs/f"{user}.key")
        reader,writer = await asyncio.open_connection("127.0.0.1",server.port,ssl=context,server_hostname=host)
        peer = cls()
        peer.reader,peer.writer,peer.counter = reader,writer,0
        try:
            peer.welcome = await peer.call(Kind.HELLO,{"version":1})
        except BaseException:
            await peer.close()
            raise
        return peer

    async def call(self,kind,meta=None,data=b""):
        self.counter += 1
        self.writer.write(Frame(kind,self.counter,meta or {},data).encode())
        await self.writer.drain()
        response = await read_frame(self.reader)
        assert response.request in (0,self.counter)
        if response.kind == Kind.ERROR:
            raise Fault(response.meta["code"],response.meta["message"])
        return response

    async def upload(self,path,data,transfer=None):
        transfer = transfer or str(uuid.uuid4())
        digest = hashlib.sha256(data).hexdigest()
        response = await self.call(Kind.PUT_INIT,{"id":transfer,"path":path,"size":len(data),"sha256":digest})
        if response.kind == Kind.RESULT:
            return response
        for offset in range(response.meta["offset"],len(data),CHUNK):
            await self.call(Kind.DATA,{"id":transfer,"offset":offset},data[offset:offset+CHUNK])
        return await self.call(Kind.FINISH,{"id":transfer})

    async def download(self,path):
        transfer = str(uuid.uuid4())
        response = await self.call(Kind.GET_INIT,{"id":transfer,"path":path})
        data = b""
        while len(data) < response.meta["size"]:
            chunk = await self.call(Kind.READ,{"id":transfer,"offset":len(data)})
            data += chunk.data
            await self.call(Kind.ACK,{"id":transfer,"offset":len(data)})
        digest = hashlib.sha256(data).hexdigest()
        assert digest == response.meta["sha256"]
        await self.call(Kind.FINISH,{"id":transfer,"sha256":digest})
        return data

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (OSError,ssl.SSLError):
            pass
