import asyncio
import hashlib
import os
import socket
import time
import subprocess
import ssl
import shutil
import uuid

import pytest

from ex1b.protocol import Fault,Frame,Kind,HEADER,read_frame
from peer import Peer


async def test_shared_protocol_fixtures():
    import json
    from pathlib import Path
    for fixture in json.loads(Path("fixtures/protocol.json").read_text()):
        reader=asyncio.StreamReader();reader.feed_data(bytes.fromhex(fixture["wire_hex"]))
        packet=await read_frame(reader)
        assert packet.meta == fixture["meta"]
        assert packet.request == fixture["request"]
        assert packet.data.hex() == fixture["payload_hex"]


async def test_pre_tls_flood_does_not_block_existing_session(service,certs):
    peer=await Peer.open(service,certs)
    sockets=[]
    try:
        for _ in range(12):
            raw=socket.socket();raw.setblocking(False)
            await asyncio.get_running_loop().sock_connect(raw,("127.0.0.1",service.port))
            sockets.append(raw)
        await asyncio.sleep(.05)
        assert sum(service.ip_counts.values()) <= 8
        assert (await asyncio.wait_for(peer.call(Kind.PING),2)).kind == Kind.PONG
    finally:
        for raw in sockets:raw.close()
        await peer.close()


async def test_atomic_commit_race_and_crash_window(service,certs):
    peer=await Peer.open(service,certs)
    data=b"exact recording"
    ids=[str(uuid.uuid4()),str(uuid.uuid4())]
    for transfer in ids:
        await peer.call(Kind.PUT_INIT,{"id":transfer,"path":"race","size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
        await peer.call(Kind.DATA,{"id":transfer,"offset":0},data)
    await peer.call(Kind.FINISH,{"id":ids[0]})
    with pytest.raises(Fault) as error:await peer.call(Kind.FINISH,{"id":ids[1]})
    assert error.value.code == "CONFLICT"
    await peer.call(Kind.CANCEL,{"id":ids[1]})
    # Simulate rename completing immediately before the DB result transaction.
    service.database.update(ids[0],status="active")
    response=await peer.call(Kind.RESUME,{"id":ids[0]})
    assert response.kind == Kind.RESULT
    assert response.meta["status"] == "complete"
    await peer.close()


async def test_duplicate_chunk_and_owner_check(service,certs):
    alice=await Peer.open(service,certs)
    bob=await Peer.open(service,certs,"bob")
    transfer=str(uuid.uuid4());data=b"abc"
    await alice.call(Kind.PUT_INIT,{"id":transfer,"path":"a","size":3,"sha256":hashlib.sha256(data).hexdigest()})
    await alice.call(Kind.DATA,{"id":transfer,"offset":0},data)
    ack=await alice.call(Kind.DATA,{"id":transfer,"offset":0},data)
    assert ack.meta["offset"] == 3
    with pytest.raises(Fault) as error:await bob.call(Kind.RESUME,{"id":transfer})
    assert error.value.code == "NOT_FOUND"
    await alice.call(Kind.FINISH,{"id":transfer})
    assert await alice.download("a") == data
    await alice.close();await bob.close()


async def test_reservation_prevents_parallel_quota_bypass(service,certs):
    service.database.db.execute("UPDATE users SET quota=10 WHERE name='alice'")
    peer=await Peer.open(service,certs)
    first=str(uuid.uuid4())
    await peer.call(Kind.PUT_INIT,{"id":first,"path":"one","size":8,"sha256":hashlib.sha256(b"12345678").hexdigest()})
    with pytest.raises(Fault) as error:
        await peer.call(Kind.PUT_INIT,{"id":str(uuid.uuid4()),"path":"two","size":8,"sha256":hashlib.sha256(b"12345678").hexdigest()})
    assert error.value.code == "QUOTA"
    await peer.call(Kind.CANCEL,{"id":first})
    await peer.upload("two",b"12345678")
    await peer.close()


async def test_limit_is_shared_across_connections(service,certs):
    service.database.update_user("alice",bandwidth=524288)
    peers=await asyncio.gather(Peer.open(service,certs),Peer.open(service,certs))
    try:
        start=time.monotonic()
        await asyncio.gather(peers[0].upload("rate-a",b"x"*1048576),peers[1].upload("rate-b",b"y"*1048576))
        elapsed=time.monotonic()-start
        assert elapsed >= 3.7
        print(f"两连接共享512KiB/s：2097152字节，耗时{elapsed:.3f}秒")
    finally:await asyncio.gather(*(p.close() for p in peers))


async def test_untrusted_and_expired_certificates(service,certs,tmp_path):
    # Trusting a leaf without its issuing CA does not trust the server chain.
    with pytest.raises(ssl.SSLCertVerificationError):
        await Peer.open(service,certs,ca=certs/"unknown.pem")
    expired=tmp_path/"expired.pem"
    (tmp_path/"index").write_text("");(tmp_path/"serial").write_text("01\n")
    config=tmp_path/"ca.cnf"
    config.write_text(f"[ca]\ndefault_ca=lab\n[lab]\ndatabase={tmp_path}/index\nserial={tmp_path}/serial\nnew_certs_dir={tmp_path}\ndefault_md=sha256\npolicy=policy\n[policy]\ncommonName=supplied\n")
    csr=tmp_path/"expired.csr"
    subprocess.run([shutil.which("openssl"),"req","-new","-key",str(certs/"alice.key"),"-subj","/CN=alice","-out",str(csr)],check=True,capture_output=True)
    subprocess.run([shutil.which("openssl"),"ca","-batch","-config",str(config),"-cert",str(certs/"ca.pem"),"-keyfile",str(certs/"ca.key"),"-startdate","20200101000000Z","-enddate","20200102000000Z","-in",str(csr),"-out",str(expired)],check=True,capture_output=True)
    context=ssl.create_default_context(cafile=str(certs/"ca.pem"))
    context.load_cert_chain(expired,certs/"alice.key")
    with pytest.raises((OSError,asyncio.IncompleteReadError)):
        reader,writer=await asyncio.open_connection("127.0.0.1",service.port,ssl=context,server_hostname="localhost")
        try:
            writer.write(Frame(Kind.HELLO,1,{"version":1}).encode());await writer.drain();await read_frame(reader)
        finally:
            writer.close()
            try:await writer.wait_closed()
            except OSError:pass
