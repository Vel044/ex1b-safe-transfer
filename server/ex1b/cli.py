import argparse
import asyncio
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
from pathlib import Path

from .database import Database
from .protocol import Fault
from .server import serve


def fingerprint(path):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(Path(path).read_text())).hexdigest()


def certificates(out, users, extra_hosts=()):
    out = Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True,mode=0o700)
    openssl = shutil.which("openssl")
    if not openssl:
        raise Fault("SETUP", "需要安装OpenSSL")
    def run(*args):
        result = subprocess.run([openssl,*map(str,args)],capture_output=True,text=True)
        if result.returncode:
            raise Fault("CERT",result.stderr[-2000:])
    if not (out/"ca.pem").exists():
        run("req","-x509","-newkey","rsa:3072","-sha256","-nodes","-keyout",out/"ca.key","-out",out/"ca.pem","-days","365","-subj","/CN=EX1B Lab CA","-addext","basicConstraints=critical,CA:TRUE,pathlen:0","-addext","keyUsage=critical,keyCertSign,cRLSign")
    for name in ["server",*users]:
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in name):
            raise Fault("INPUT","无效证书名称")
        if not (out/f"{name}.pem").exists():
            run("req","-new","-newkey","rsa:3072","-sha256","-nodes","-keyout",out/f"{name}.key","-out",out/f"{name}.csr","-subj",f"/CN={name}")
            ext = "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage="
            ext += "serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1" if name == "server" else "clientAuth"
            if name == "server":
                import ipaddress
                for host in extra_hosts:
                    try:
                        host = str(ipaddress.ip_address(host))
                        ext += f",IP:{host}"
                    except ValueError:
                        if not all(c.isalnum() or c in ".-" for c in host):
                            raise Fault("INPUT","无效SAN主机名")
                        ext += f",DNS:{host}"
            config = out/f"{name}.ext"
            config.write_text(ext+"\n")
            run("x509","-req","-in",out/f"{name}.csr","-CA",out/"ca.pem","-CAkey",out/"ca.key","-CAcreateserial","-out",out/f"{name}.pem","-days","30","-sha256","-extfile",config)
            config.unlink()
            (out/f"{name}.csr").unlink()
        if name != "server" and not (out/f"{name}.p12").exists():
            import secrets
            password_file = out/f"{name}.password"
            password_file.write_text(secrets.token_urlsafe(18)+"\n")
            password_file.chmod(0o600)
            run("pkcs12","-export","-inkey",out/f"{name}.key","-in",out/f"{name}.pem","-certfile",out/"ca.pem","-out",out/f"{name}.p12","-name",name,"-passout",f"file:{password_file}")
    for path in out.iterdir():
        path.chmod(0o600)
    return out


def main():
    parser = argparse.ArgumentParser(description="实验1B安全文件传输服务")
    commands = parser.add_subparsers(dest="command",required=True)
    server = commands.add_parser("server")
    server.add_argument("--config",required=True)
    cert = commands.add_parser("cert")
    cert.add_argument("--out",default="runtime/certs")
    cert.add_argument("--users",nargs="+",default=["alice","bob"])
    cert.add_argument("--san",action="append",default=[])
    admin = commands.add_parser("admin")
    admin.add_argument("--data",default="runtime/data")
    operations = admin.add_subparsers(dest="operation",required=True)
    add = operations.add_parser("user-add")
    add.add_argument("name")
    add.add_argument("--certificate",required=True)
    add.add_argument("--access",choices=["r","rw"],default="rw")
    add.add_argument("--bandwidth",type=int,default=2097152)
    add.add_argument("--quota",type=int,default=2147483648)
    disable = operations.add_parser("user-disable")
    disable.add_argument("name")
    enable = operations.add_parser("user-enable")
    enable.add_argument("name")
    bandwidth = operations.add_parser("set-bandwidth")
    bandwidth.add_argument("name")
    bandwidth.add_argument("bytes_per_second",type=int,help="0表示不限速；非零值至少65536字节/秒")
    access = operations.add_parser("set-access")
    access.add_argument("name")
    access.add_argument("access",choices=["r","rw"])
    commands.add_parser("verify")
    args = parser.parse_args()
    try:
        if args.command == "server":
            asyncio.run(serve(json.loads(Path(args.config).read_text())))
        elif args.command == "cert":
            directory = certificates(args.out,args.users,args.san)
            print(f"证书已生成：{directory}；客户端P12密码在各自.password文件中")
        elif args.command == "admin":
            database = Database(args.data)
            try:
                if args.operation == "user-add":
                    database.add_user(args.name,fingerprint(args.certificate),args.bandwidth,args.quota)
                    database.update_user(args.name,access=args.access)
                elif args.operation == "set-access":
                    database.update_user(args.name,access=args.access)
                elif args.operation == "set-bandwidth":
                    database.update_user(args.name,bandwidth=args.bytes_per_second)
                else:
                    database.update_user(args.name,active=args.operation == "user-enable")
            finally:
                database.db.close()
            print("账户配置已更新")
        else:
            raise SystemExit(subprocess.call([sys.executable,"-m","pytest","-q"]))
    except KeyboardInterrupt:
        pass
    except (Fault,OSError,ValueError) as exc:
        print(f"错误：{exc}",file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
