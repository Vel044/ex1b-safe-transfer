import hashlib
import uuid

import pytest
from peer import Peer
from ex1b.protocol import Kind, Fault
from ex1b.storage import Jail


@pytest.mark.asyncio
async def test_copy_delete_and_readonly(service, certs):
    peer = await Peer.open(service, certs)
    try:
        await peer.upload('source', b'file actions')
        await peer.call(Kind.COPY, {'source':'source','path':'copy'})
        assert await peer.download('copy') == b'file actions'
        with pytest.raises(Fault) as conflict:
            await peer.call(Kind.COPY, {'source':'source','path':'copy'})
        assert conflict.value.code == 'CONFLICT'
        assert await peer.download('copy') == b'file actions'
        service.database.update_user('alice',access='r')
        assert await peer.download('source') == b'file actions'
        for kind, meta in [
            (Kind.MKDIR,{'path':'blocked'}),
            (Kind.DELETE,{'path':'source'}),
            (Kind.COPY,{'source':'source','path':'blocked'}),
            (Kind.PUT_INIT,{'id':str(uuid.uuid4()),'path':'blocked','size':0,'sha256':hashlib.sha256(b'').hexdigest()}),
        ]:
            with pytest.raises(Fault) as error:
                await peer.call(kind,meta)
            assert error.value.code == 'PERMISSION'
        service.database.update_user('alice',access='rw')
        await peer.call(Kind.DELETE,{'path':'copy'})
        entries=(await peer.call(Kind.LIST,{"cursor":0})).meta['entries']
        assert [e['name'] for e in entries] == ['source']
        with service.database.lock:
            used=service.database.db.execute("SELECT SUM(size) FROM transfers WHERE user='alice' AND direction='upload' AND status NOT IN ('failed','cancelled')").fetchone()[0]
        assert used == len(b'file actions')
    finally:
        await peer.close()


def test_delete_stays_in_root(tmp_path):
    root=tmp_path/'root';root.mkdir()
    outside=tmp_path/'outside';outside.mkdir()
    (outside/'keep').write_text('keep')
    (root/'folder').mkdir()
    (root/'folder'/'link').symlink_to(outside,target_is_directory=True)
    jail=Jail(root)
    try:
        with pytest.raises(Fault):
            jail.delete('../outside')
        jail.delete('folder')
        assert (outside/'keep').read_text() == 'keep'
        with pytest.raises(Fault):
            jail.delete('')
    finally:
        jail.close()
