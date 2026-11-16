# 安传 实验1B安全文件传输

Swift编写的macOS原生客户端，配套Python异步文件服务器。支持双向TLS、长连接、文件与文件夹上传下载、四文件并发、断线及进程重启后的续传、按账户共享限速和独立目录。

## 环境

客户端要求macOS 14以上及支持Swift 6的Xcode；服务端要求Python 3.13以上。容器演示需要Docker Desktop。证书脚本使用OpenSSL 3。已在Apple Silicon Mac与Linux容器中验证。

## 准备和运行

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python '.[test]'
.venv/bin/python scripts/bootstrap.py
sh scripts/container_up.sh
sh scripts/build_macos.sh
open build/安传.app
```

也可本机调试服务端：先停止占用8443端口的容器，再运行`.venv/bin/ex1b server --config runtime/server.json`。修改服务端源码后重新安装，或使用`PYTHONPATH=server .venv/bin/python -m ex1b.cli ...`。

客户端选择`localhost:8443`、`runtime/certs/ca.pem`及`alice.p12`或`bob.p12`，输入相应`.password`文件内的P12密码。通过系统选择器授权本地目录，多选文件或目录后上传、下载。可将身份保存到系统钥匙串；配置只存身份引用。实验CA不会安装为系统全局根证书。

Alice默认2MiB/s，Bob默认512KiB/s，上传和下载共用该账户全部连接的带宽预算。单文件上限1GiB、账户配额2GiB、四文件并发。同名文件拒绝覆盖，需改名后重新添加。远端同名目录可合并。符号链接不参与传输。

## 验证

```sh
.venv/bin/python -m pytest -q
swift test --package-path macos --build-system native -q
macos/.build/debug/TransferProbe --certs runtime/certs --root runtime/probe --idle-seconds 17
```

`TransferProbe`复用正式Swift通信及传输核心，测试文件夹、空目录、中文文件、空文件和并发往返。测试用Python参考对端仅位于`tests`。

独立进程续传验证：

```sh
macos/.build/debug/TransferProbe --certs runtime/certs --resume-stage start --state runtime/restart-proof
docker compose restart server
docker compose up -d --wait
macos/.build/debug/TransferProbe --certs runtime/certs --resume-stage finish --state runtime/restart-proof
```

首次运行`start`后记录检查点并退出；第二次运行从SwiftData任务数据库恢复，继续原传输。验证路径每次使用新的空目录。

## 管理

```sh
docker compose exec -T server ex1b admin --data /data set-bandwidth bob 1048576
docker compose exec -T server ex1b admin --data /data user-disable bob
docker compose exec -T server ex1b admin --data /data user-enable bob
```

证书更换需重新登记指纹。生成时可用`ex1b cert --san <IP或DNS名称>`加入额外服务器身份；已有证书不会被脚本静默覆盖。容器初始化保留现有账户状态，证书指纹不匹配时停止。

## 设计和边界

详见[协议说明](docs/protocol.md)、[安全设计](docs/security.md)和[学习顺序](docs/learning.md)。

临时文件不作为完整文件展示。ACK确认已持久化检查点，恢复时核对前缀和源文件身份，完成后核对SHA-256并原子提交。客户端只在用户授权目录落盘；服务器通过目录描述符逐级访问，不跟随符号链接。容器非root运行，只读根目录，不挂载宿主机个人目录或CA私钥。

应用层连接上限、报文上限、超时、并发、配额和限速用于抑制资源耗尽，无法阻止网络带宽被大流量占满。实验CA没有搭建完整的公开PKI撤销服务，应用以账户禁用和指纹登记控制客户端身份。Mac构建使用本地临时签名，适用于课程本机演示；没有进行开发者公证或Windows客户端打包。

源码采用MIT许可证。所有实验私钥、P12密码、账户数据及提交材料均保存在被Git忽略的目录，克隆后应自行生成证书。
