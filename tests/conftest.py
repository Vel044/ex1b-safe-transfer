import json
import shutil
from pathlib import Path

import pytest
import pytest_asyncio

from ex1b.cli import certificates,fingerprint
from ex1b.database import Database
from ex1b.server import Server


@pytest.fixture(scope="session")
def certs(tmp_path_factory):
    return certificates(tmp_path_factory.mktemp("certs"),["alice","bob","unknown"])


@pytest_asyncio.fixture
async def service(tmp_path,certs):
    config = {"host":"127.0.0.1","port":0,"data":str(tmp_path/"data"),"ca":str(certs/"ca.pem"),"certificate":str(certs/"server.pem"),"key":str(certs/"server.key")}
    server = Server(config)
    server.database.add_user("alice",fingerprint(certs/"alice.pem"),20*1024*1024,2*1024**3)
    server.database.add_user("bob",fingerprint(certs/"bob.pem"),20*1024*1024,2*1024**3)
    await server.start()
    yield server
    await server.close()
