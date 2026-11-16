import asyncio
import hashlib
import os
import ssl
import struct
import time
import uuid

import pytest

from ex1b.protocol import CHUNK,HEADER,Fault,Frame,Kind,read_frame
from ex1b.server import Bucket,Server
from ex1b.storage import Jail,parts
from peer import Peer


@pytest.mark.parametrize("data",[b"",b"hello\x00world",bytes(range(256))*300])
async def test_roundtrip_and_connection_reuse(service,certs,data):
    peer = await Peer.open(service,certs)
    try:
        for name in ["中文.bin","second.bin"]:
            await peer.upload(name,data)
            assert await peer.download(name) == data
        assert (await peer.call(Kind.PING)).kind == Kind.PONG
        assert len(service.connections) == 1
    finally:
        await peer.close()


async def test_users_parallel_and_isolation(service,certs):
    peers = await asyncio.gather(Peer.open(service,certs),Peer.open(service,certs),Peer.open(service,certs,"bob"))
    try:
        await asyncio.gather(*(p.upload(f"{i}.bin",os.urandom(250000)) for i,p in enumerate(peers)))
        listing = await peers[2].call(Kind.LIST,{"path":"","cursor":0})
        assert [entry["name"] for entry in listing.meta["entries"]] == ["2.bin"]
        with pytest.raises(Fault):
            await peers[0].download("../bob/2.bin")
    finally:
        await asyncio.gather(*(p.close() for p in peers))


async def test_resume_after_both_restart(service,certs):
    data = os.urandom(CHUNK*3+13)
    transfer = str(uuid.uuid4())
    peer = await Peer.open(service,certs)
    await peer.call(Kind.PUT_INIT,{"id":transfer,"path":"resume.bin","size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    await peer.call(Kind.DATA,{"id":transfer,"offset":0},data[:CHUNK])
    await peer.close()
    await service.close()
    # Restart the same service object on a new port with its on-disk database.
    replacement = Server(service.config)
    await replacement.start()
    try:
        peer = await Peer.open(replacement,certs)
        ready = await peer.call(Kind.RESUME,{"id":transfer})
        assert ready.meta["offset"] == CHUNK
        assert ready.meta["prefix"] == hashlib.sha256(data[:CHUNK]).hexdigest()
        for offset in range(CHUNK,len(data),CHUNK):
            await peer.call(Kind.DATA,{"id":transfer,"offset":offset},data[offset:offset+CHUNK])
        await peer.call(Kind.FINISH,{"id":transfer})
        # Lost completion response is recoverable and idempotent.
        assert (await peer.call(Kind.FINISH,{"id":transfer})).meta["status"] == "complete"
        assert await peer.download("resume.bin") == data
        await peer.close()
    finally:
        await replacement.close()
        # The fixture owns service; close() must be idempotent.


async def test_download_resume_and_changed_source(service,certs):
    data = os.urandom(CHUNK*2+5)
    peer = await Peer.open(service,certs)
    await peer.upload("source.bin",data)
    transfer = str(uuid.uuid4())
    await peer.call(Kind.GET_INIT,{"id":transfer,"path":"source.bin"})
    chunk = await peer.call(Kind.READ,{"id":transfer,"offset":0})
    assert chunk.data == data[:CHUNK]
    await peer.call(Kind.PAUSE,{"id":transfer})
    ready = await peer.call(Kind.RESUME,{"id":transfer,"offset":CHUNK,"prefix":hashlib.sha256(chunk.data).hexdigest()})
    assert ready.meta["offset"] == CHUNK
    await peer.call(Kind.PAUSE,{"id":transfer})
    (service.data/"users/alice/source.bin").write_bytes(b"changed")
    with pytest.raises(Fault,match="变化"):
        await peer.call(Kind.RESUME,{"id":transfer,"offset":CHUNK,"prefix":hashlib.sha256(chunk.data).hexdigest()})
    await peer.close()


async def test_integrity_conflict_cancel_quota(service,certs):
    peer = await Peer.open(service,certs)
    await peer.upload("existing",b"original")
    with pytest.raises(Fault) as error:
        await peer.upload("existing",b"overwrite")
    assert error.value.code == "CONFLICT"
    transfer = str(uuid.uuid4())
    await peer.call(Kind.PUT_INIT,{"id":transfer,"path":"bad","size":3,"sha256":hashlib.sha256(b"abc").hexdigest()})
    with pytest.raises(Fault):
        await peer.call(Kind.DATA,{"id":transfer,"offset":1},b"a")
    await peer.call(Kind.DATA,{"id":transfer,"offset":0},b"xxx")
    with pytest.raises(Fault) as error:
        await peer.call(Kind.FINISH,{"id":transfer})
    assert error.value.code == "INTEGRITY"
    assert not (service.data/"users/alice/bad").exists()
    service.database.db.execute("UPDATE users SET quota=8 WHERE name='alice'")
    with pytest.raises(Fault) as error:
        await peer.upload("too-big",b"123456789")
    assert error.value.code == "QUOTA"
    transfer = str(uuid.uuid4())
    await peer.call(Kind.PUT_INIT,{"id":transfer,"path":"cancel","size":0,"sha256":hashlib.sha256(b"").hexdigest()})
    await peer.call(Kind.CANCEL,{"id":transfer})
    assert not service.data.joinpath("private",transfer+".part").exists()
    await peer.close()


async def test_paths_links_and_sql(service,certs,tmp_path):
    peer = await Peer.open(service,certs)
    for path in ["../bob", "/etc/passwd", "a/../b", "a//b", "a\\b"]:
        with pytest.raises(Fault):
            await peer.call(Kind.MKDIR,{"path":path})
    (service.data/"users/alice/escape").symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(Fault):
        await peer.call(Kind.MKDIR,{"path":"escape/hack"})
    unusual = "x'; DROP TABLE users;--"
    await peer.upload(unusual,b"safe")
    assert await peer.download(unusual) == b"safe"
    assert service.database.user(name="alice")["active"]
    await peer.close()


async def test_certificate_failures(service,certs):
    with pytest.raises(ssl.SSLCertVerificationError):
        await Peer.open(service,certs,host="wrong.example")
    with pytest.raises((OSError,asyncio.IncompleteReadError,Fault)):
        await Peer.open(service,certs,user=None)
    with pytest.raises(Fault) as error:
        await Peer.open(service,certs,user="unknown")
    assert error.value.code == "AUTH"


async def test_disable_and_active_limit(service,certs):
    peer = await Peer.open(service,certs)
    for i in range(4):
        await peer.call(Kind.PUT_INIT,{"id":str(uuid.uuid4()),"path":f"{i}","size":0,"sha256":hashlib.sha256(b"").hexdigest()})
    with pytest.raises(Fault) as error:
        await peer.call(Kind.PUT_INIT,{"id":str(uuid.uuid4()),"path":"fifth","size":0,"sha256":hashlib.sha256(b"").hexdigest()})
    assert error.value.code == "LIMIT"
    service.database.update_user("alice",active=False)
    with pytest.raises(Fault) as error:
        await peer.call(Kind.PING)
    assert error.value.code == "AUTH"
    await peer.close()


async def test_framing_split_combined_and_oversize():
    reader = asyncio.StreamReader()
    raw = Frame(Kind.PING,1).encode()+Frame(Kind.PING,2).encode()
    async def feed():
        for byte in raw:
            reader.feed_data(bytes([byte]))
            await asyncio.sleep(0)
    feeding = asyncio.create_task(feed())
    assert (await read_frame(reader)).request == 1
    assert (await read_frame(reader)).request == 2
    await feeding
    reader = asyncio.StreamReader()
    reader.feed_data(HEADER.pack(b"SFT1",1,40,0,1,65537,0))
    with pytest.raises(Fault):
        await read_frame(reader)
    reader = asyncio.StreamReader()
    reader.feed_data(b"S")
    with pytest.raises(TimeoutError):
        await read_frame(reader,partial_timeout=0.01)


async def test_bucket_shared_budget():
    bucket = Bucket()
    start = time.monotonic()
    await asyncio.gather(*(bucket.acquire(CHUNK,CHUNK*4) for _ in range(5)))
    assert time.monotonic()-start >= .95
