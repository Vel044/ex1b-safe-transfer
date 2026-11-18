import asyncio
import pytest
from ex1b.server import Bucket
from ex1b.protocol import CHUNK,Kind,Fault
from peer import Peer


@pytest.mark.asyncio
async def test_zero_bypasses_bucket():
    bucket=Bucket()
    bucket.tokens=0
    await asyncio.wait_for(asyncio.gather(*(bucket.acquire(CHUNK,0) for _ in range(100))),timeout=1)
    assert bucket.tokens==0


@pytest.mark.asyncio
async def test_unlimited_account_and_validation(service,certs):
    service.database.update_user('alice',bandwidth=0)
    assert service.database.user(name='alice')['bandwidth']==0
    for rate in [-1,1,65535]:
        with pytest.raises(Fault):service.database.update_user('alice',bandwidth=rate)
    peer=await Peer.open(service,certs)
    try:
        assert peer.welcome.meta['bandwidth']==0
        assert (await peer.call(Kind.PING)).meta['bandwidth']==0
        data=b'Unlimited transfer'*16384
        await peer.upload('unlimited.bin',data)
        assert await peer.download('unlimited.bin')==data
    finally:await peer.close()
    service.database.update_user('alice',bandwidth=524288)
    assert service.database.user(name='alice')['bandwidth']==524288
