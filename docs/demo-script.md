# SFT1 Transfer 演示与功能验收脚本

适用版本：macOS 原生客户端、SFT1 双向 TLS 服务端，包含文件管理、r/rw 和 Docker SSH 调试功能。

现有成片的前两段标题为“1｜项目文件架构 / 编译启动”“2｜上传下载删除”。后续协议设计、重点模块实现、CA 签名及形式化验证，单独使用[协议与重点模块讲解脚本](protocol-demo-script.md)，接在功能演示之后录制。

本文是录制操作清单，**不是已经完成的测试记录**。逐段实际执行后填写结果；遇到错误先记录并修复，再重新录制该段。正常情况的预期不能作为实际运行结果。

## 一、录制安排

建议按片段分别录制，最后剪成约 10–15 分钟。下载依赖、编译、大文件传输和重启等待可以加速，画面注明“加速”；保留真实命令、退出结果和操作前后状态。第一次 VS Code 远端组件安装提前完成，不占正式镜头。

| 片段      | 内容                                     | 成片参考时长 |
| --------- | ---------------------------------------- | ------------ |
| A         | 展示代码架构                             | 45–60 秒     |
| B1 / B2   | 启动服务端；编译并打开客户端             | 75–105 秒    |
| C         | 基本界面、粘贴上传、拖动下载、核对与删除 | 90–120 秒    |
| D         | 加分一：暂停、断开、重连后续传           | 30–45 秒     |
| E         | 加分二：公钥身份认证 / 双向证书验证      | 60 秒        |
| F         | 加分三：GUI 多文件同时上传下载           | 60–90 秒     |
| G         | 加分四：根据用户身份控制带宽             | 45–60 秒     |
| H（选拍） | 其他入口、同侧复制与异常操作             | 30–60 秒     |
| I         | SSH 查看真实文件                         | 30 秒        |
| J         | 自动化测试、模型检查与强化隔离           | 90–150 秒    |

录屏中关闭通知，放大终端字号。证书选择和导入可以展示，密码输入、密码文件内容、私钥、连接令牌需避开或打码。可以展示公开证书的签发者、用途和 SAN。

## 二、录制前准备（不改动现有资料）

### 2.1 统一终端与部署模式

在 **Mac 本机终端**进入项目根目录。本文的 Docker、Swift、Python 命令默认在本机执行；只有明确标注“容器内”的命令才在 SSH 中运行。

```sh
cd "/Users/vel/Desktop/学习/软件与系统安全/实验1B"
```

主流程统一使用 **默认模式（已包含 SSH）**。定义快捷函数，之后所有容器管理都用 `dc`：

```sh
dc() { docker compose "$@"; }
```

每开一个新的本机终端都重新定义一次。`docker compose up` 和 `scripts/container_up.sh` 均使用包含 SSH 的默认配置。仅在 J5 段切换 `compose.hardened.yaml` 展示强化隔离。

### 2.2 生成本次专用素材

执行以下命令会创建新的 `runtime/demo-时间戳`，不覆盖旧文件，也不会修改服务器数据。总素材约 180 MiB。不要把整个演示根目录一口气上传；按镜头选择文件。

```sh
export DEMO_ROOT="$PWD/runtime/demo-$(date +%Y%m%d-%H%M%S)"
.venv/bin/python - <<'PY'
import os
from pathlib import Path
root = Path(os.environ['DEMO_ROOT'])
root.mkdir(parents=True, exist_ok=False)
for name in ['本地源', '下载-按钮', '下载-拖放', '下载-粘贴', '本地副本', '日志']:
    (root / name).mkdir()
source = root / '本地源'
(source / '单文件.txt').write_text('SFT1 安全传输演示\n', encoding='utf-8')
(source / '空文件.txt').write_bytes(b'')
folder = source / '资料夹'
(folder / '子目录').mkdir(parents=True)
(folder / '空目录').mkdir()
(folder / '中文说明.txt').write_text('目录层级、中文名称与空目录。\n', encoding='utf-8')
(folder / '子目录' / '内容.txt').write_text('nested file\n', encoding='utf-8')
chunk = bytes(range(256)) * 4096
for name, mib in [('并发A.bin', 8), ('并发B.bin', 8), ('并发C.bin', 8),
                  ('并发D.bin', 8), ('并发E.bin', 8), ('并发F.bin', 8),
                  ('续传演示.bin', 128), ('取消演示.bin', 8)]:
    with (source / name).open('xb') as stream:
        for _ in range(mib):
            stream.write(chunk)
links = source / '含链接资料夹'
links.mkdir()
(links / '真实文件.txt').write_text('real file\n', encoding='utf-8')
(links / '跳过的链接').symlink_to(source / '单文件.txt')
print('本地目录：', root)
print('远端根目录建议名：', root.name)
PY
```

记下终端输出的完整本地目录和 `demo-时间戳` 名称。重新打开终端时用实际路径重新设置 `DEMO_ROOT`，不要再次运行生成脚本覆盖本次变量。

客户端左侧选择**整个 `$DEMO_ROOT`** 作为授权目录，随后进入“本地源”。这样可以用上一级切换到各个下载目录和本地副本目录。

右侧用 Alice 新建一个与本次 `demo-时间戳` 同名的目录，下面的镜头只在这个目录内操作。可以预先新建 `01-按钮`、`02-拖放`、`03-粘贴`、`04-远端副本`、`05-并发`、`06-续传`、`07-取消`、`08-断网`、`09-重启`。

### 2.3 确认账户条件

先记录 Alice、Bob 当前的权限和带宽，演示结束恢复原值。默认是 Alice 2 MiB/s、Bob 512 KiB/s，已有账户权限默认 rw；若之前改过，以实际值为准。

```sh
dc exec -T server python - <<'PY'
import sqlite3
with sqlite3.connect('/data/private/state.sqlite') as db:
    for row in db.execute('SELECT name, access, active, bandwidth, quota FROM users ORDER BY name'):
        print(row)
PY
```

若只需要使用默认演示条件，可明确设置（会改变这两个实验账户的配置）：

```sh
dc exec -T server ex1b admin --data /data set-access alice rw
dc exec -T server ex1b admin --data /data set-access bob rw
dc exec -T server ex1b admin --data /data set-bandwidth alice 2097152
dc exec -T server ex1b admin --data /data set-bandwidth bob 524288
```

## 三、逐镜头操作

### A｜开场：展示代码架构

**画面标题**：SFT1 Transfer · 代码架构

**操作与画面**：在 VS Code 中打开项目，展示 README 的文件架构；按解说顺序展开 `macos/Sources`、`server/ex1b`、`deploy`、`tests` 和 `formal`。这一段先展示各模块的位置与职责，协议报头和时序图留到后面的协议验证部分讲解。

**解说文本（可直接照读）**：

> 本次实验完成的是 SFT1 Transfer 安全文件传输软件，我自定义了SFT1文件传输协议。由 macOS 原生客户端和 Python 文件服务器组成。下面先介绍代码架构。
> macos 目录是客户端工程。其中 SafeTransferApp 负责界面，包括左右文件列表和传输队列；SafeTransferCore 负责协议编解码、TLS 连接、文件传输和任务持久化。界面使用 SwiftUI 和 AppKit 的系统组件。
> server 目录是服务端。protocol.py 定义 SFT1 消息格式，server.py 处理会话和文件传输，storage.py 限制文件访问范围，database.py 保存账户、权限和续传检查点。
> deploy 和 compose.yaml 用于 Docker 部署，scripts 保存环境准备和构建脚本。接下来启动服务端，再编译并打开客户端。

### B1｜启动 Docker 与文件服务端

```sh
.venv/bin/python --version
.venv/bin/python scripts/bootstrap.py
sh scripts/container_up.sh
docker compose ps
```

**解说文本（可直接照读）**：

> 首先启动 Docker Desktop，等待容器引擎就绪。
> 然后运行环境准备脚本，生成或检查实验所需的 CA、服务器证书以及 Alice、Bob 的客户端身份，并准备账户配置。
> 接着执行服务端启动脚本。脚本构建镜像、准备数据目录并启动容器。文件服务监听本机的 8443 端口，SSH 监听本机的 2222 端口，方便后续查看服务器中的实际文件。
> 现在容器状态显示 healthy，说明文件服务和 SSH 端口的健康检查已经通过。接下来编译客户端。

### B2｜编译、打开客户端并连接

```sh
xcodebuild -version
sh scripts/build_macos.sh
open "build/SFT1 Transfer.app"
```

> 接下来编译客户端。Xcode 编译 Swift 代码，生成应用包，并完成本地签名。
> 编译完成后，打开 SFT1 Transfer，点击连接服务器。服务器地址填写 127.0.0.1，端口填写 8443，再选择实验 CA 证书和 Alice 的客户端身份。
> 连接使用双向 TLS：客户端验证服务器证书和主机身份，服务器也验证客户端证书，并根据证书指纹识别账户。身份验证通过后，双方通过 SFT1 协议交换后续请求。
> 现在连接窗口已经关闭，状态栏显示 Alice、读写权限和带宽上限，右侧可以浏览服务器文件，说明连接建立成功。下面开始展示文件操作和传输功能。

### C｜基本功能：复制粘贴上传文件、拖动下载文件夹、SHA-256 核对

**画面标题**：03 · 文件上传与文件夹下载

本段使用新的独立样例，旧样例不删除。目标流程是：**单个文件粘贴到远端文件夹 → 整个远端文件夹拖到本地 → 比较其中的文件哈希**。后续 D–H 的大文件、并发素材仍使用第二部分准备的 `$DEMO_ROOT`，不要与本段变量混用。

#### C2. 复制粘贴上传文件到远端文件夹

1. 左侧选中“完整性样例.bin”，按 **⌘C**。
2. 右侧双击进入 `$REMOTE_DEMO_DIR`，点击右侧文件表格，再按 **⌘V**。
3. 等任务显示“已完成”，确认右侧文件夹内出现该文件，大小约 8.4 MB（8 MiB）。

**解说文本**：

> 这里使用一个 8 MiB 的二进制文件。我先在服务器中新建一个文件夹，再把本地文件通过复制粘贴上传到这个文件夹中。下方队列显示传输进度，完成后可以看到服务端文件。

#### C3. 拖动下载整个文件夹

1. 左侧点击上一级，进入“下载结果”，确认当前列表为空。
2. 右侧点击上一级，返回能看到 `$REMOTE_DEMO_DIR` 文件夹的目录。
3. 选中这个**文件夹本身**，从右侧拖到左侧表格，松手。
4. 等目录和文件任务全部完成。左侧应出现同名文件夹，双击进去，看到“完整性样例.bin”。

**解说文本**：

> 下载时，我选中服务器上的整个文件夹，将它拖到左侧的空目录中。客户端会展开目录中的文件任务，完成后保留文件夹名称和内部文件。

**预期路径**：`$FOLDER_DEMO_ROOT/下载结果/$REMOTE_DEMO_DIR/完整性样例.bin`。不是直接保存到“下载结果”根目录，也不要拖到“上传源”，否则会混淆源文件和下载结果。

#### C4. 核对源文件与下载文件 SHA-256

在同一个本机终端执行；若换了终端，先重新载入环境文件：

```sh
. runtime/folder-demo.env
shasum -a 256 "$FOLDER_DEMO_ROOT/上传源/完整性样例.bin" "$FOLDER_DEMO_ROOT/下载结果/$REMOTE_DEMO_DIR/完整性样例.bin"
```

**预期**：两行 64 位十六进制摘要完全相同，并与“样例说明.txt”中记录的源哈希一致。两个路径必须不同。如果下载文件不存在、隐藏或队列失败，先修复，不用原文件与自身比较来替代。

**解说文本**：

> 最后分别计算原文件和下载文件的 SHA-256。两份文件位于不同目录，摘要完全一致，也与上传前记录的摘要一致，说明本次上传和文件夹下载后，文件内容保持一致。

**剪辑点**：远端新建空文件夹 → ⌘C / ⌘V → 上传完成 → 右侧返回上一级并拖动整个文件夹 → 下载完成并进入目录 → 两行哈希相同。哈希结果停留 3 秒。

#### C5. 删除（核对后选拍）

保留哈希画面后，可在左侧选中下载副本按 **⌘Delete**，确认移到废纸篓；远端文件或文件夹也可用相同快捷键确认永久删除。源目录“上传源”保持不动。后面的 SSH 核对优先使用尚未删除的远端演示目录。

**解说文本**：

> 文件核对结束后，可以通过 Command 加 Delete 删除所选项目。本地副本进入废纸篓，远端删除会再次确认。

### D｜加分功能一：断开重连后继续传输

本段采用已经录制的操作流程，只展示一次断点续传，不额外录制服务端重启或哈希核对。

**操作**：

1. 上传 10 MiB 的“续传演示.bin”，进度非零时，在队列选中该任务，点击“暂停”。
2. 等状态显示“已暂停”，记录当前进度，然后点击工具栏“断开”。
3. 重新连接同一服务器，使用同一个 Alice 身份。
4. 在队列选中**原任务**，点击“继续”，展示从原进度继续增长，直到“已完成”。

**解说文本（可直接照读）**：

> 第一项加分功能是断点续传。这里在文件上传到一半时暂停，并断开连接。重新连接后，继续原来的任务，可以看到进度从已确认的位置恢复，最终完成传输。

**剪辑点**：非零进度 → 已暂停 → 断开 → 重新连接 → 原任务继续 → 已完成。保留恢复前后的进度变化即可，不把这个操作描述为双端重启测试。

如果录制前临时降低了 Alice 带宽，可在本机项目根目录恢复默认值，为后面的演示做准备：

```sh
docker compose exec -T server ex1b admin --data /data set-bandwidth alice 2097152
```

### E｜加分功能二：可视化展示双向证书验证与 r/rw

**剪辑备注：本段加入“四项验证对照表”画面。** 把下面四行制作成一张表格，插在 E 段开头；随后按表格顺序剪入对应操作。也可在每组操作前短暂显示该表，并高亮当前行。表格展示的是预期结果，实际操作成功后再标注“通过”，不要提前当作已完成的测试结果。

**视频表格标题：双向证书验证与访问权限**

| 验证项目         | 演示操作                                  | 预期结果                                     |
| ---------------- | ----------------------------------------- | -------------------------------------------- |
| 正常连接         | 正确 CA ＋ Alice 客户端证书               | 连接成功，识别为 Alice                       |
| 客户端验证服务器 | 选择错误 CA，保留正常 Alice 身份          | 客户端拒绝连接                               |
| 服务端验证客户端 | 恢复正确 CA，选择外部 CA 签发的客户端证书 | 服务端拒绝连接                               |
| 读写权限对比     | Alice（rw）与 Bob（r）分别连接并操作      | Alice 可读写；Bob 可读取、下载，写操作被禁止 |

**表格与画面对应**：第 1 行对应 E1，第 2 行对应 E2，第 3 行对应 E3，第 4 行对应 E4。表格全景建议停留 4–6 秒，后续每组画面配同名字幕，段末可再次展示表格并按实际结果填写“通过”。

**目标**：在 App 中通过“连接成功 / 连接失败 / 文件操作允许或禁用”直观展示，不把一串测试命令作为主要镜头。只使用一个服务器。

#### E0. 已准备的样例与配置

| 项目                               | 路径                                                      |
| ---------------------------------- | --------------------------------------------------------- |
| 正常 CA                            | `runtime/certs/ca.pem`                                    |
| Alice 正常身份及密码文件           | `runtime/certs/alice.p12`、`alice.password`               |
| Bob 正常身份及密码文件             | `runtime/certs/bob.p12`、                                 |
| `bob.password`                     |
| 不信任服务器的 CA                  | `runtime/auth-demo/错误CA.pem`                            |
| 外部 CA 签发的客户端身份及密码文件 | `runtime/auth-demo/错误客户端.p12`、`错误客户端.password` |
| 本地权限演示目录                   | `runtime/folder-demo-20261117-181619-130f/E-权限演示`     |
| Bob 已有的独立下载样本             | 远端 `E-只读演示/只读样本.txt`                            |

错误证书独立生成，未替换原证书，未登记到服务端。三个认证组合已通过参考客户端验证预期拒绝或成功；GUI 录制仍需按实际结果拍摄。密码不入镜。

#### E1. 正常连接：双方身份正确

在 App 中使用 `127.0.0.1:8443`，选择正常 `ca.pem` 与 `alice.p12`，输入 Alice 的 P12 密码连接。拍下连接窗口关闭、状态栏显示 Alice 和远端文件列表。

> 首先使用正确的 CA 和客户端证书，连接成功，服务器识别当前身份为 Alice。

#### E2. 错误 CA：客户端拒绝服务器

1. 断开，重新打开连接窗口。
2. 客户端身份仍为 Alice，只把 CA 换成 `runtime/auth-demo/错误CA.pem`。
3. 点击连接，拍下所选 CA 文件名和失败提示。窗口应保留，不能进入已连接状态。
4. 下一步先把 CA 恢复为正常的 `runtime/certs/ca.pem`。

> 现在只更换客户端信任的 CA。服务器证书无法通过这个 CA 的验证，客户端拒绝连接。这展示客户端对服务器身份的检查。

这里没有真的替换运行中服务器的证书；改变的是客户端的信任锚。不要解说成“已经部署了一个中间人服务器”。

#### E3. 错误客户端证书：服务器拒绝客户端

1. CA 必须已恢复为正常 `runtime/certs/ca.pem`。
2. 点击“选择P12…”，改选 `runtime/auth-demo/错误客户端.p12`，输入其对应密码。
3. 点击连接，拍下错误客户端文件名和连接失败提示。服务端不会接受这个外部 CA 签发的身份。
4. 再换回正常 Alice 身份，连接应恢复成功。

> 接着恢复正确的 CA，但换成由外部 CA 签发的客户端证书。服务器不信任这个身份，因此拒绝连接。这展示服务器对客户端身份的检查。

错误提示可能显示 TLS 错误或“服务器关闭了连接”，具体文字以实际运行结果为准。关键是所选材料明确、连接被拒绝，再恢复正常材料后能成功。此处验证的是客户端证书不受信任，不是把未登记账户混同为 TLS 证书错误。

#### E4. r/rw：认证成功后能做什么

这部分也放进 E，作为认证后的授权演示。

| 身份  | 权限 | 浏览和下载自己的文件 | 上传、新建、远端粘贴和删除 |
| ----- | ---- | -------------------- | -------------------------- |
| Alice | `rw` | 允许                 | 允许                       |
| Bob   | `r`  | 允许                 | 拒绝                       |

录制前在本机项目根目录执行（会修改这两个实验账户的权限）：

```sh
docker compose exec -T server ex1b admin --data /data set-access alice rw
docker compose exec -T server ex1b admin --data /data set-access bob r
```

**只录这些直观操作**：

1. Alice 连接后，拍下状态栏 `alice · rw`，在远端新建一个临时演示文件夹，证明写操作允许；也可用已有 C 段上传镜头衔接。
2. 断开，选 Bob 的正常 `bob.p12` 重新连接，拍下状态栏 `bob · r` 和不同的账户目录。
3. 左侧选择本地 `E-权限演示` 目录，再进入 `Bob下载`；右侧进入 `E-只读演示`，将 `只读样本.txt` 拖到左侧。队列完成，证明 Bob 仍能下载。
4. 左侧返回上一级，选中“上传测试.txt”，拍下上传按钮禁用；右侧新建目录、粘贴和删除也应不可用。无需反复点击所有禁用按钮。
5. 切回 Alice，确认原来的文件还在，写操作恢复可用。

> 最后展示访问权限。Alice 的身份是读写权限，可以上传和新建目录；Bob 的身份验证同样成功，但只有只读权限，可以浏览和下载自己的文件，不能上传或删除。身份认证回答“你是谁”，权限控制决定“你能做什么”。

权限由证书指纹对应的服务端账户配置决定，不是证书文件名，也不需要再部署另一台服务器。按钮禁用是直观交互证据，服务端拒绝直接写请求由 J1 的 `test_copy_delete_and_readonly` 补充验证。

**收尾**：若 F/G 需要 Bob 上传，先恢复：

```sh
docker compose exec -T server ex1b admin --data /data set-access bob rw
```

**四组剪辑画面**：正确材料连接成功 → 错误 CA 拒绝 → 外部客户端证书拒绝 → Alice rw / Bob r 操作对比。前两种拒绝各拍一次即可，失败后都要明确恢复正确材料。

### F｜加分功能三：两个上传与两个下载同时进行

**本段只录一个并发场景**，不重复暂停、删除和 SHA-256 核对。

#### F0. 已准备好的样例

左侧通过系统选择器选中：

```text
/Users/vel/Desktop/学习/软件与系统安全/实验1B/runtime/folder-demo-20261117-181619-130f
```

里面新增了：

```text
F-上传A.bin                    5 MiB
F-上传B.bin                    5 MiB
下载结果/                 空下载目录
```

Alice 远端根目录里已准备：

```text
F-并发演示-20261117-191647/
├── 待上传/                    起初为空，接收两个上传文件
└── 待下载/
    ├── F-下载A.bin            5 MiB
    └── F-下载B.bin            5 MiB
```

四个文件名称不同；下载目标为空，避免与现有文件冲突。目前按用户要求，Alice 和 Bob 都取消应用层带宽限制；Bob 仍保持只读。重新连接后 Alice 状态栏应显示 `alice · rw · 双向TLS · 不限速`。不限速时任务可能很快完成，添加下载前确认上传尚未结束；G 段单独录制 Alice 不限速与 Bob 限速的对比。

#### F1. 先启动两个上传

1. 客户端切回 Alice。
2. 左侧停留在上面的本地目录，右侧进入 `F-并发演示-20261117-191647/待上传`。
3. 按住 Command 选中“F-上传A.bin”和“F-上传B.bin”，同时加入上传队列。

#### F2. 上传未结束时加入两个下载

1. 立即双击左侧“下载结果”，进入空下载目录。
2. 右侧点击上一级，从“待上传”返回本次 F 根目录，再进入“待下载”。
3. 多选“F-下载A.bin”和“F-下载B.bin”，一起拖到左侧。
4. 镜头停留在传输队列，展示两个向上图标、两个向下图标，以及不同任务的进度变化。
5. 等四个任务完成：本地下载目录应出现两个下载文件，远端“待上传”应出现两个上传文件。旧队列记录可能仍存在，重点拍名称以 F 开头的四条。

**解说文本（可直接照读）**：

> 第三项加分功能是 GUI 多文件并发传输。这里先启动两个上传，再加入两个下载。可以看到上传和下载任务在同一队列中同时推进，并分别显示进度、速度和状态，最终四个任务全部完成。

**预期**：同一画面里上传和下载都有正在增长的进度，最终四条均完成。总活动文件上限为四个，不是每个方向各四个；各任务共享账户的带宽上限，实际速度允许有波动。

**剪辑点**：双选上传 → 切换目标 → 双选拖动下载 → 四条任务同时推进 → 全部完成。若前两个上传已经结束，再添加下载就不能表现双向并发；使用新的空目录重新录制，避免重传到同名目标。

#### F3. 带宽设置

当前两个账户均为不限速（bandwidth=0），不需要在本段结束后设置回固定上限。下一段只给 Bob 设置上限，Alice 保持不限速。

### G｜加分功能四：Alice 不限速与 Bob 限速对比

**录制方案**：同一服务器、同一个 5 MiB 文件，先录 Alice 不限速下载，再执行命令给 Bob 限速，录 Bob 下载。两者本地目标目录不同，避免同名冲突。Bob 保持 r，用下载即可验证带宽，无需赋予上传权限。

#### G0. 当前已准备的状态

- Alice：rw，bandwidth=0，不限速。
- Bob：r，bandwidth=0，暂不限速，**限速命令留给录制时执行**。
- 两个账户各自远端目录：`G-用户限速对比/限速对比.bin`，文件相同，各 5 MiB。
- 本地根目录：`runtime/folder-demo-20261117-181619-130f`；分别下载到 `下载结果/G-Alice不限速` 与 `下载结果/G-Bob限速`。

数值 0 表示不启用应用层令牌桶限速，不代表传输速度没有网络、磁盘或 TLS 开销。目录名称不决定用户上限，服务端账户配置才决定上限。

#### G1. Alice 不限速下载

1. 使用正常 CA 和 Alice 身份连接，确认状态栏显示 Alice、rw、**不限速**。
2. 左侧进入“下载结果/G-Alice不限速”，右侧进入“G-用户限速对比”。
3. 将“限速对比.bin”拖到左侧，录下速度、进度和完成过程。任务过快时保留完整短片，不必人为凑时长。

> 第四项是根据用户身份控制带宽。首先使用 Alice 账户，不设置应用层带宽上限，下载这个 5 MiB 文件。

#### G2. 在镜头中给 Bob 设限

在 Mac 本机项目根目录执行这一条（256 KiB/s）：

```sh
docker compose exec -T server ex1b admin --data /data set-bandwidth bob 262144
```

**这条命令需要录制时亲自执行，目前没有替你执行。** Alice 保持 0，不修改其带宽。

#### G3. Bob 限速下载

1. 断开 Alice，改用 Bob 的正常 P12 连接。
2. 确认状态栏显示 `bob · r`，上限约 256 KiB/s。
3. 左侧进入“下载结果/G-Bob限速”，右侧进入 Bob 自己的“G-用户限速对比”。
4. 下载同名 5 MiB 文件，录下较慢的进度和稳定阶段速度，直到完成。理论上约 20 秒，实际可能更久；64 KiB 初始突发和显示平均值可能使开头短暂高于上限。

> 接着将 Bob 账户的带宽限制为每秒 256 KiB。使用 Bob 下载同样大小的文件，可以看到速度受到约束。这个限制由服务端根据账户身份执行，账户的多个连接和上传下载共享预算。

**剪辑表格**：

| 身份  | 权限 | 应用层带宽设置      | 画面                               |
| ----- | ---- | ------------------- | ---------------------------------- |
| Alice | rw   | 不限速（0）         | 状态栏不限速，下载进度及完成       |
| Bob   | r    | 256 KiB/s（262144） | 设置命令、状态栏上限、实际下载速度 |

只读与限速是独立属性：Bob 可以下载，正好用来演示限速。不承诺 Alice 的实际速度一定达到某个数值，以录制结果为准。多连接共享预算另外由 J 段自动化测试补充。

#### G4. 可选：恢复 Bob 为不限速

录完后如需继续不限速使用，执行：

```sh
docker compose exec -T server ex1b admin --data /data set-bandwidth bob 0
```

恢复两者不限速的完整命令：

```sh
docker compose exec -T server ex1b admin --data /data set-bandwidth alice 0
docker compose exec -T server ex1b admin --data /data set-bandwidth bob 0
```

### H｜补充验收：其他传输入口、同侧复制与异常操作

C 已演示基本操作。本段是补充验收，可完整执行但只选取尚未展示的操作剪入视频。若要验证工具栏按钮上传、下载，分别使用新的空目标操作一次；以下各方式也使用独立目标，避免同名冲突：

| 操作                | 来源                            | 目标               | 预期                             |
| ------------------- | ------------------------------- | ------------------ | -------------------------------- |
| 拖动上传            | 本地源的文本、空文件、资料夹    | 远端 `02-拖放`     | 多个任务加入队列并完成           |
| 拖动下载            | 远端 `02-拖放` 的上述项目       | 本地“下载-拖放”    | 项目保存到该栏当前目录           |
| ⌘C → ⌘V 上传        | 本地源的文本和资料夹            | 远端 `03-粘贴`     | 聚焦目标表格后粘贴，加入上传队列 |
| 右键复制 → 粘贴下载 | 远端 `03-粘贴`                  | 本地“下载-粘贴”    | 加入下载队列                     |
| 本地同侧复制        | 本地源的文本和资料夹            | 本地“本地副本”     | 文件和目录复制完成               |
| 远端同侧复制        | 远端 `03-粘贴` 中的文本和资料夹 | 远端 `04-远端副本` | 通过 SFT1 COPY/MKDIR 复制完成    |

拖动时从已选中行开始，在另一栏内松手；目标是该栏**当前目录**。复制之后通过上一级导航到目标目录，再在目标列表内右键粘贴。当前脚本验证应用内双栏，不包含 Finder 跨应用拖放。

**解说词**：“拖放和剪贴板使用系统交互，跨端操作统一进入传输队列；同端复制也遵守同名不覆盖规则。”

**剪辑点**：左右各保留一次完整拖动；其他方式可以用快切展示。

#### H1. 错误提示、重复文件、符号链接与删除

1. 切回 Alice，到本次远端演示目录的 `03-粘贴`，再次上传“单文件.txt”（H 前面的粘贴步骤应已上传它），预期同名冲突，原文件保持不变。
2. 勾选队列“仅失败”，选中该任务展示详细原因；随后取消这条失败任务，等取消同步后再清理。
3. 在本地源选中“含链接资料夹”，上传到新的空目标；预期真实文件传完，遍历到符号链接时跳过并显示说明。文件列表本身不显示符号链接，因此不直接选择链接行。
4. 将“单文件.txt”复制到本地“本地副本”中的一个新建子目录，选择这个副本按 **⌘Delete**，在系统确认中选择移到废纸篓。仅删除演示副本。
5. 在 Finder 的废纸篓中确认副本存在，不清空废纸篓。
6. 远端选择 `04-远端副本` 内已完成的文件，按 **⌘Delete**，确认永久删除后刷新；再删除其中的资料夹副本，展示递归删除。
7. 远端正在传输或暂停中的路径，若执行删除应提示先完成或取消任务，不应强删。目录权限、越界、符号链接逃逸由 J 段验证。

**解说词**：“同名文件拒绝覆盖；本地删除使用系统废纸篓，远端删除需要读写权限并检查未结束任务。”

**剪辑点**：确认窗口与删除后列表各保留 2 秒。不要对用户原有资料演示永久删除。

### I｜SSH / VS Code 核对服务器真实文件

1. 在本机终端执行 `ssh SFT1Docker`，展示用户为 transfer、端口为 2222；SSH 是调试通道，SFT1 仍使用 8443。
2. 在 VS Code 通过 Remote SSH 连接 SFT1Docker，打开 `/data/users/alice`，找到本段 C 的 `$REMOTE_DEMO_DIR` 文件夹，检查实际上传的“完整性样例.bin”。若 C5 已删除远端目录，则使用 H 段留下的演示文件。
3. 查看文件大小和目录结构；可在容器终端对“完整性样例.bin”执行 `sha256sum`，与本机 `shasum -a 256` 对比。
4. 查看 `/app/server/ex1b/protocol.py` 的 SFT1 标识，以及 `/app/server/ex1b/server.py` 的请求处理。

**解说词**：“这里查看的是服务端实际落盘文件。SSH 只用于调试和取证，客户端文件传输走独立的 SFT1 协议。”

**剪辑点**：App 中完成状态 → VS Code 中同一文件 → 服务端代码。`/workspace` 是只读宿主项目映射；`/app` 是容器代码副本，修改不会自动同步回本机。

### J｜自动化、安全、长连接和形式化验证

#### J1. 功能与安全测试

本机执行，完整结果可保存在本次演示日志目录：

```sh
.venv/bin/python -m pytest -v --junitxml="$DEMO_ROOT/日志/python-tests.xml"
swift test --package-path macos --build-system native
```

展示真实摘要，不把脚本中的历史通过数量当成本次结果。测试使用独立临时服务器，不改现有账户权限。

| 覆盖点                                     | 当前测试入口                                                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| 空文件、边界大小、长连接复用               | `test_roundtrip_and_connection_reuse`                                                                                     |
| 多用户并发与目录隔离                       | `test_users_parallel_and_isolation`                                                                                       |
| 双端重启续传                               | `test_resume_after_both_restart`                                                                                          |
| 下载恢复、源文件变化拒绝                   | `test_download_resume_and_changed_source`                                                                                 |
| 哈希错误、同名冲突、取消、配额             | `test_integrity_conflict_cancel_quota`                                                                                    |
| 路径穿越、链接、SQL 特殊输入               | `test_paths_links_and_sql`                                                                                                |
| 证书及主机名验证失败                       | `test_certificate_failures`                                                                                               |
| 不受信任及过期证书拒绝                     | `test_untrusted_and_expired_certificates`                                                                                 |
| 账户禁用、活动任务上限                     | `test_disable_and_active_limit`                                                                                           |
| 半包、粘包、报文长度上限                   | `test_framing_split_combined_and_oversize`                                                                                |
| 握手资源耗尽下保留正常会话                 | `test_pre_tls_flood_does_not_block_existing_session`                                                                      |
| 原子提交、重复块、任务所有权               | `test_atomic_commit_race_and_crash_window`、`test_duplicate_chunk_and_owner_check`                                        |
| 并发配额预留与跨连接限速                   | `test_reservation_prevents_parallel_quota_bypass`、`test_limit_is_shared_across_connections`、`test_bucket_shared_budget` |
| 复制不覆盖、r 权限直接拒绝写请求、删除配额 | `test_copy_delete_and_readonly`                                                                                           |
| 递归删除不越界、不跟随链接                 | `test_delete_stays_in_root`                                                                                               |
| Swift 共享协议样例、本地边界与任务恢复     | `macos/Tests/SafeTransferCoreTests/ProtocolTests.swift`                                                                   |

**解说词**：“这些测试直接构造异常消息和权限请求，验证服务器拒绝行为。资源限制用于缓解资源耗尽，不代表能够阻止所有规模的 DDoS。”

#### J2. Swift 与真实 Docker 服务端互通、心跳

先确认 Alice 为 rw 且处于正常带宽，不要同时运行耗时 GUI 传输，然后执行：

```sh
swift build --package-path macos --build-system native
macos/.build/debug/TransferProbe --certs runtime/certs --file-actions --idle-seconds 17
```

**预期**：输出 `result: passed`、账户、SHA-256、非零 `heartbeats`、同一会话的 `connection_id`。程序会创建带 UUID 的测试目录，验证文件夹往返、远端复制删除、队列清理，并清理本次服务端测试目录。界面操作不等价于这个探针的结果，两种证据分别展示。

代码讲解可切到 `Connection.swift` 中的 TCP keepalive、`TransferEngine.swift` 的心跳循环和 `protocol.md` 的 PING/PONG。界面正常浏览传输后连接保持，文件结束不关闭 TCP。

#### J3. 独立进程续传补充证据

使用新的状态目录；两条探针命令是不同的客户端进程：

```sh
export RESUME_STATE="$DEMO_ROOT/进程续传验证"
macos/.build/debug/TransferProbe --certs runtime/certs --resume-stage start --state "$RESUME_STATE"
dc restart server
dc ps
# 等服务 healthy 后执行：
macos/.build/debug/TransferProbe --certs runtime/certs --resume-stage finish --state "$RESUME_STATE"
```

**预期**：第一阶段输出非零 `durable_offset`，第二阶段输出 `resumed_after_process_restart`，`resumed_from` 与原检查点一致且小于完整大小。这个探针会留下带随机名称的验证文件，不要误认为用户文件。

#### J4. TLA+ / TLC

```sh
python3 scripts/verify_protocol.py
```

展示模型、选定不变量、真实检查摘要和一条故意破坏规则后的反例；参考[协议验证报告](protocol-verification-report.md)及[模型复现说明](../formal/README.md)。首次工具下载提前准备。

**预期**：脚本总体符合预期。正确模型检查通过；故意破坏规则、无公平性与可达性见证配置出现的指定反例是预期结果，不是“所有配置都无错误”。

**解说词**：“这里检查有限参数下的上传、下载和恢复模型。它补充实际测试，不证明全部代码、TLS、GUI、新增 COPY/DELETE 或任意规模系统完全正确。”

#### J5. 强化容器隔离（最后单独拍）

先结束 GUI 任务，断开 SSH / VS Code，再回到本机终端切换无 SSH 强化隔离模式：

```sh
docker compose -f compose.hardened.yaml up -d --build --force-recreate --wait
docker compose -f compose.hardened.yaml ps
docker compose -f compose.hardened.yaml exec -T server id
docker compose -f compose.hardened.yaml exec -T server python - <<'PY'
from pathlib import Path
import os
assert os.getuid() == 10001
assert not Path('/certs/ca.key').exists()
assert not Path('/workspace').exists()
try:
    Path('/outside-proof').write_text('test')
except OSError:
    print('PASS: UID=10001; CA private key absent; host project absent; outside write denied')
else:
    raise SystemExit('FAIL: unexpected outside write')
PY
```

**预期**：只发布本机 8443，不发布 2222；UID=10001，写根目录失败；容器无 CA 私钥及宿主项目挂载。默认 SSH 模式不能用来证明这一段的强化隔离性质。

如果录制后继续使用 VS Code，再执行 `sh scripts/ssh_up.sh` 返回默认模式。

## 四、验收记录与收尾

每段记录真实结果，建议把失败原因和重录时间也写下：

| 片段                     | 实际结果（通过 / 未通过 / 未执行） | 原始录像时间点或文件名 | 问题 / 重录说明 |
| ------------------------ | ---------------------------------- | ---------------------- | --------------- |
| A 代码架构               | 待执行                             |                        |                 |
| B1 Docker 启动           | 待执行                             |                        |                 |
| B2 客户端编译和连接      | 待执行                             |                        |                 |
| C 基本文件操作和核对     | 待执行                             |                        |                 |
| D 暂停、断开、重连后续传 | 已录制（用户确认）                 | 待填写                 |                 |
| E 双向认证、隔离与权限   | 待执行                             |                        |                 |
| F1 多文件与队列控制      | 待执行                             |                        |                 |
| F2 同时上传下载          | 待执行                             |                        |                 |
| G 用户限速               | 待执行                             |                        |                 |
| H 补充文件操作           | 待执行                             |                        |                 |
| I SSH 实际文件           | 待执行                             |                        |                 |
| J1 自动化测试            | 待执行                             |                        |                 |
| J2 长连接与心跳          | 待执行                             |                        |                 |
| J3 独立进程续传          | 待执行                             |                        |                 |
| J4 形式化验证            | 待执行                             |                        |                 |
| J5 强化隔离              | 待执行                             |                        |                 |

收尾时恢复准备阶段记录的账户 active、access 和 bandwidth；保持本次录像、测试摘要与实际错误信息。清理仅限本次命名的演示目录，删除前完成或取消相关任务；不用删除整个 runtime，也不清空系统废纸篓。源码、报告和 MP4 按课程格式最终统一整理，当前不生成提交包。
