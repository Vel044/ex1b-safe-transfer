# SFT1 Transfer 安装与启动

SFT1 Transfer 由 macOS 原生客户端和文件服务器组成。本文依次说明服务端准备与启动、客户端编译与启动、首次连接。以下步骤以**同一台 Mac 运行客户端和 Docker 服务端**为例。

准备好 macOS 14 或更高版本、支持 Swift 6 的 Xcode、Python 3.13、uv、OpenSSL 3 和 Docker Desktop。已在 Apple Silicon Mac 和 Linux 容器上验证。

先在终端进入项目根目录：本机项目路径为 `/Users/vel/Desktop/学习/软件与系统安全/实验1B`；若使用提交包，则进入解压后的 `姓名_学号_ex1B_src` 目录。该目录下应能看到 `pyproject.toml`、`compose.yaml` 和 `macos` 文件夹。下面的终端命令均在这个目录执行。

## 1. 启动服务端

### 1.1 首次准备

打开 Docker Desktop，等待它启动完成。然后在终端依次执行：

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python '.[test]'
.venv/bin/python scripts/bootstrap.py
```

这些命令创建运行环境，并在 `runtime/certs` 下生成实验 CA、服务器证书和 Alice、Bob 的客户端身份。每个客户端身份的 `.p12` 文件都有对应的 `.password` 密码文件。脚本不会静默覆盖已有证书；已有账户与证书不匹配时会停止并提示。

### 1.2 启动容器服务

```sh
sh scripts/container_up.sh
```

首次运行需要构建镜像，请等待命令结束。检查服务状态：

```sh
docker compose ps
docker compose logs --tail 20 server
```

状态显示 `healthy` 表示服务已就绪。服务器在后台运行，默认地址为 `127.0.0.1`、端口为 `8443`；Docker Desktop 需要保持运行。SFT1 的 8443 和 SSH 的 2222 端口都只在本机开放；默认启动已包含 SSH。

以后启动可再次执行 `sh scripts/container_up.sh`。停止服务使用：

```sh
docker compose stop server
```

停止后数据保留。重新启动已有容器可执行 `docker compose up -d --wait`。

### 1.3 本机调试服务端（可选）

如需直接在 Mac 上调试 Python 服务端，先停止占用 8443 端口的容器，再执行：

```sh
PYTHONPATH=server .venv/bin/python -m ex1b.cli server --config runtime/server.json
```

按 `Control-C` 停止。本机服务使用 `runtime/data`，容器服务使用 `runtime/container-data`，两者的数据目录分别保存。

## 2. 编译并启动客户端

确保 Xcode 可用；如果 SFT1 Transfer 已经打开，先退出应用，再执行：

```sh
sh scripts/build_macos.sh
open "build/SFT1 Transfer.app"
```

编译完成后，应用位于 `build/SFT1 Transfer.app`。提交包的源码目录内也附有 `macOS应用/SFT1 Transfer.app`；该预编译应用为 Apple Silicon 版本。

## 3. 客户端连接服务器

1. 打开 SFT1 Transfer，点击工具栏上的 **连接** 或窗口中的 **连接服务器…**。
2. 按下表填写地址并选择证书。以下示例使用 Alice：

   | 界面字段 | 填写或选择 |
   | --- | --- |
   | 服务器 | `127.0.0.1` |
   | 端口 | `8443` |
   | CA证书 | `runtime/certs/ca.pem` |
   | 客户端身份 | `runtime/certs/alice.p12` |
   | P12密码 | `runtime/certs/alice.password` 中的内容 |

   服务器一栏只填地址，端口单独填写。可在终端查看 Alice 的导入密码：

   ```sh
   cat runtime/certs/alice.password
   ```

   使用 Bob 时，选择 `bob.p12`，并读取 `bob.password`。服务端根据证书识别账户，界面不需要另填用户名。
3. macOS 15 及以上默认只在本次连接中加载身份，也可勾选 **将身份保存到系统钥匙串**；macOS 14 使用钥匙串导入。实验 CA 只用于本应用的证书验证。
4. 点击 **连接**。成功后，右侧显示该账户的服务器目录，底部状态栏显示账户名、双向 TLS 和带宽上限。首次连接时远端目录可以为空。

如果连接失败，先检查 Docker Desktop、`docker compose ps` 的服务状态和地址端口，再确认选用的是同一套实验环境生成的 `ca.pem`、对应用户的 `.p12` 及其密码。证书验证失败时应更正证书或地址。


连接成功后，按照[使用说明](usage.md)进行文件传输和任务管理。项目文件结构见[README](../README.md)。

## 4. Docker SSH 调试与 VS Code

默认配置同时运行 SFT1 服务（8443）和 OpenSSH（本机 2222），共用原有数据。前面的 `container_up.sh` 已开启 SSH；原 SSH 启动脚本保留为兼容入口：

```sh
sh scripts/ssh_up.sh
```

首次启动在没有已登记公钥时默认使用 `~/.ssh/id_rsa.pub`，也可把其他公钥路径作为第一个参数。已有授权公钥会保留。SSH 仅允许公钥登录，禁止密码与 root 登录，端口绑定 `127.0.0.1`。默认配置允许 VS Code 写入其安装目录；需要无 SSH、只读根文件系统的隔离测试时，使用 `compose.hardened.yaml`。

当前电脑已添加 SSH 别名 **SFT1Docker**，可直接验证：

```sh
ssh SFT1Docker
```

当前别名使用 `transfer@127.0.0.1:2222`，公钥来自本机 `id_rsa.pub`；私钥留在 Mac。主机公钥直接从容器读取并保存在 `runtime/ssh/known_hosts`，启用严格主机密钥验证。

在 VS Code 中安装 **Remote - SSH** 扩展，然后打开命令面板，选择 **Remote-SSH: Connect to Host… → SFT1Docker**，远端系统选择 **Linux**。连接后打开：

| 路径 | 用途 |
| --- | --- |
| `/app` | 可编辑的服务端代码副本；服务进程通过 PYTHONPATH 使用 `/app/server` |
| `/data/users/alice` | Alice 的真实服务端文件 |
| `/data/users/bob` | Bob 的真实服务端文件 |
| `/workspace` | 本机项目的只读挂载，用于检查原项目、文档和测试 |

`/app` 中的修改属于容器副本，重建容器会重置；需要保留的改动应同步回本机源码。SSH 主机密钥、数据和 VS Code 安装目录会保留。

容器内可执行功能测试，测试使用独立临时数据，不操作现有账户文件：

```sh
cd /workspace
python -m pytest /workspace/tests -o pythonpath=/app/server -o cache_dir=/tmp/sft1-pytest-cache -q
```

默认启动、重启、停止和查看均使用同一配置：

```sh
docker compose ps
docker compose logs --tail 30 server
docker compose stop server
```

可选：切换强化隔离模式并关闭 SSH（这一步会使 VS Code 断开）：

```sh
docker compose -f compose.hardened.yaml up -d --build --force-recreate --wait
```


从强化隔离模式返回默认 SSH 模式：

```sh
sh scripts/container_up.sh
```

平时重启使用 `docker compose restart server`，或重新执行 `sh scripts/container_up.sh`，均会保留 SSH。
