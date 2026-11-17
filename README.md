# 安传：安全文件传输使用说明

安传由 macOS 原生客户端和文件服务器组成，支持文件及文件夹上传、下载、多任务传输和断点续传。以下步骤以**同一台 Mac 运行客户端和 Docker 服务端**为例。

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

状态显示 `healthy` 表示服务已就绪。服务器在后台运行，默认地址为 `127.0.0.1`、端口为 `8443`；Docker Desktop 需要保持运行。默认端口只在本机开放。

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

确保 Xcode 可用；如果安传已经打开，先退出应用，再执行：

```sh
sh scripts/build_macos.sh
open "build/安传.app"
```

编译完成后，应用位于 `build/安传.app`。提交包的源码目录内也附有 `macOS应用/安传.app`；该预编译应用为 Apple Silicon 版本。

## 3. 客户端连接服务器

1. 打开安传，点击工具栏上的 **连接** 或窗口中的 **连接服务器…**。
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

## 4. 功能介绍与操作

### 4.1 界面和目录浏览

- **左侧本地文件**：点击 **选择目录…**，通过系统选择器授权本地目录。此目录也是本地浏览和下载的起点。
- **右侧服务器文件**：显示当前账户的远端目录。双击目录可进入，点击上箭头返回上一级；点击表头可排序。
- **下方传输队列**：显示任务、进度、大小、速度和状态。选择任务后，底部会显示详细结果或错误原因。
- **底部状态栏**：显示连接状态、账户身份和带宽上限。

两侧目录栏都有新建文件夹按钮，可在当前所在目录下新建目录。文件列表支持多选。

### 4.2 上传文件

1. 在左侧选择本地目录，进入文件所在位置。
2. 在右侧进入要保存文件的服务器目录。
3. 在左侧选中一个或多个文件，点击工具栏 **上传**。
4. 在下方队列查看进度和结果。文件传完并通过 SHA-256 校验后，状态显示 **已完成**。

文件上传到**右侧当前打开的目录**。如果远端已有同名文件，任务会失败并提示改名；现有文件不会被覆盖。

### 4.3 下载文件

1. 在左侧选择并进入要保存下载文件的本地目录。
2. 在右侧进入服务器目录，选中一个或多个文件。
3. 点击工具栏 **下载**，在传输队列查看结果。

文件保存到**左侧当前打开的目录**。本地已有同名文件时，任务会提示冲突；可以改名或选择其他目标目录后重新添加。

### 4.4 整文件夹传输

上传时在左侧选中文件夹本身，再点击 **上传**；下载时在右侧选中文件夹，再点击 **下载**。目录层级和空目录会保留。已有同名目录可以合并，同名文件仍会提示冲突。

文件夹会展开为多个目录和文件任务；某个文件失败后，其他任务仍可继续。符号链接会跳过并在界面提示。默认目录深度上限为 32 层，每组最多 10000 个条目。

### 4.5 多任务和进度

可以一次多选多个文件，也可以在已有任务执行时继续添加上传或下载任务。每个账户最多同时传输 4 个文件，其余任务在队列中等待。进度、速度和完成情况分别显示在每条任务中。

### 4.6 暂停、继续和断点续传

在队列中选中任务，点击 **暂停**；需要继续时选中该任务并点击 **继续**。对于一整组文件夹任务，可选择其中一条，再通过 **整组任务** 菜单暂停或继续整组。

网络断开时，客户端会尝试重连；重连后可手动继续未完成任务。客户端或服务端重启后，任务记录和检查点可用于继续传输。恢复前会检查文件身份和已有数据；源文件发生变化或临时文件损坏时，需要取消旧任务并重新添加。

### 4.7 取消任务和查看失败

选中任务点击 **取消**；文件夹任务也可通过 **整组任务** 菜单取消。已经完成的文件保留，未完成的临时数据会清理；离线取消会在重连后同步到服务端。

队列顶部显示完成和失败数量。勾选 **仅失败** 可以查看失败任务；选中任务后，在队列下方查看具体原因。处理原因后可继续或重新添加任务。

### 4.8 用户隔离和带宽限制

Alice 和 Bob 的服务器目录相互独立。切换身份时，断开连接，在连接窗口选择另一个用户的 P12 身份及密码。

| 默认账户 | 带宽上限 | 存储配额 |
| --- | --- | --- |
| Alice | 2 MiB/s | 2 GiB |
| Bob | 512 KiB/s | 2 GiB |

同一账户的上传、下载和所有连接共享其带宽上限；单文件默认上限为 1 GiB。管理员可在项目根目录执行以下示例，将 Bob 的上限设置为 1 MiB/s：

```sh
docker compose exec -T server ex1b admin --data /data set-bandwidth bob 1048576
```

### 4.9 完整性与安全边界

传输使用双向 TLS 验证身份和加密通信。接收方先保存临时文件，检查完整长度和 SHA-256 后才提交正式文件。服务端限制账户访问范围，并设置连接、报文、配额、超时及速率上限；这些应用层限制无法阻止网络带宽被大流量完全占满。

实验私钥、P12 密码和用户数据保存在被 Git 忽略的运行目录；公开代码或提交源码包时，应继续排除这些文件。实验 CA 未部署完整的公开证书撤销服务，客户端身份可通过禁用账户控制。应用采用本地临时签名，未进行开发者公证。

### 附：自动化验证和设计资料

```sh
.venv/bin/python -m pytest -q
swift test --package-path macos --build-system native -q
macos/.build/debug/TransferProbe --certs runtime/certs --root runtime/probe --idle-seconds 17
```

独立进程续传验证时，使用一个新的空目录作为状态目录：

```sh
macos/.build/debug/TransferProbe --certs runtime/certs --resume-stage start --state runtime/restart-proof
docker compose restart server
docker compose up -d --wait
macos/.build/debug/TransferProbe --certs runtime/certs --resume-stage finish --state runtime/restart-proof
```

协议及报头见[协议说明](docs/protocol.md)，权限与安全限制见[安全设计](docs/security.md)，核心代码阅读顺序见[学习顺序](docs/learning.md)。源码采用 MIT 许可证。
