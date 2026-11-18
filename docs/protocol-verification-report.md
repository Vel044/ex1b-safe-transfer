# SFT1 协议形式化验证报告

## SFT1 协议验证报告

软件与系统安全实验 1B  独立验证报告

作者：俞乐楠    学号：202628013229090

验证方法：TLA+ 形式化建模与 TLC 有限状态模型检查

验证日期：2026年11月17日

### 结论与适用范围

在本报告规定的有限状态空间与模型假设下，选定的 SFT1 上传、下载与恢复流程通过了 6 项配置检查。检查覆盖安全不变量、终态保持，以及带弱公平调度假设的最终完成性质。双任务上传配置遍历了 8,464 个不同状态。

另运行了 5 个故意破坏保护规则的配置，均找到预期不变量反例；去掉公平性假设后，找到最终完成性质的反例；2 个可达性见证确认模型存在真正完成传输的路径。全部 14 个配置的实际结果与预期一致。

这些结果支持限定范围内的协议状态机设计。它们不证明整个 SFT1 软件、TLS 实现、所有输入或任意数量用户均正确。模型由人工从源码抽象，没有完成模型到源码的形式化精化证明。

### 交付内容

formal/SFT1Upload.tla 与 SFT1Download.tla 为模型；14 个 cfg 文件给出参数与性质；formal/results 保留每次 TLC 原始输出及 summary.json。scripts/verify_protocol.py 可复现检查，本报告和对应 Markdown 文本单独保存。

源码基准提交：3e63570819b28ec1c1839efa98b5d348b02c68c6

新增模型和验证脚本以 summary.json 中的 SHA-256 为准。该提交号只标识实现基准，不表示新增验证文件已提交或上传。

## 验证方法与建模假设

### 从实现到数学模型

TLA+ 用变量、初始状态 Init 和下一步关系 Next 描述系统。规范 Spec = Init /\ [][Next]_vars 允许协议动作和状态不变的等待。TLC 从初始状态出发，按广度优先搜索枚举可达状态，检查不变量，并分析时序性质。

使用的是模型检查，不是对任意参数的归纳证明。正确配置不设深度截断，不使用状态约束剪枝；TLC 在有限状态图遍历完成后给出结果。反例配置在找到首次违反性质的路径时停止。

| 抽象对象 | 处理方式及边界 |
| --- | --- |
| 文件与分块 | 每块抽象为一个单位；以块数表示长度，不枚举 65,536 字节的内容。 |
| 内容与哈希 | good、sourceOK 和 prefixOK 表示内容身份检查的结果；假设哈希比较可靠，不验证 SHA-256 算法。 |
| 通信与认证 | 从初始化后的任务开始；可信 TLS 通道抽象下，完整请求作为动作处理。重复块代表应用重试，不模拟 TCP 内部重传。 |
| 故障 | Crash 可插入拆分的持久化步骤之间；重连截断未确认尾部。每任务至多 1 次故障，表示连接或进程中断，不表示任意掉电行为。 |
| 并发 | 2 个独立上传任务交错执行；每任务至多一个未确认块。未建模共享配额、同名目标竞争和连接槽。 |

### 外部原语假设

写盘与 fsync 完成后数据持久，数据库检查点更新作为原子动作；正式文件创建成功后可由后续恢复识别。不模拟 I/O 错误、文件系统损坏及 fsync 失效。所有权抽象为 owner 参数，证书链和 SQL 查询本身由实现测试补充。

## 上传状态机与安全性质

### 上传动作与持久化边界

Receive → Checkpoint → SendAck → ConsumeAck；数据全部确认后，Verify → Publish → Complete。Receive 抽象写入并 fsync，Checkpoint 单独保存数据库偏移；Publish 单独创建正式文件，Complete 才把任务记录为完成。

Crash 可发生在上述边界；Reconnect 使用持久偏移恢复，并截断未确认尾部。如果正式文件已创建，则恢复为完成。Pause、Resume、Cancel 在模型规定的稳定边界执行，终态不再转回 active。

| 变量 | 含义 |
| --- | --- |
| disk / cp / ack | 落盘长度 / 持久化检查点 / 发送方已获知的确认偏移 |
| good / cpGood | 当前数据前缀正确性 / 检查点对应前缀正确性 |
| published / status | 正式文件存在标记 / active、paused、cancelled、failed、complete |
| phase / online / crashes | 处理阶段 / 连接可用性 / 已发生故障次数 |
| breach | 是否存在未授权恢复被接受的历史事件 |

| 性质 | 模型中的精确要求 |
| --- | --- |
| Bounds | 0 <= ack <= cp <= disk <= Blocks |
| AckDurable | ack <= cp；确认不能超前于持久化检查点 |
| PublishedIntegrity | published 蕴含 disk = cp = Blocks 且 good 为真 |
| CompleteIntegrity | status = complete 蕴含 published |
| Isolation | 任何任务的 breach 始终为假 |
| TerminalStable | 进入 complete、cancelled 或 failed 后，该状态永远保持 |

TypeOK 另检查类型、阶段枚举和故障次数。所有权只分析恢复守卫；路径隔离、其他消息的权限检查和账户数据库不在该不变量的证明范围。

## 下载状态机与活性条件

### 下载动作与恢复依据

ReadWrite → Save → Ack 分别表示客户端写入并 fsync、保存本地检查点、服务端接收确认。下载恢复以客户端 saved 为准，使 disk 与 server 回到 saved；恢复前同时检查源文件身份和本地前缀。

全部数据接收后，Verify 表示本地长度和内容校验；Finish 表示服务端重新确认源文件及完成响应；Commit 表示本地正式文件提交。只有本地提交之后，published 才为真。

| 性质 | 模型中的精确要求 |
| --- | --- |
| CheckpointSafe | server <= saved <= disk；服务端确认不超过客户端持久偏移 |
| PublishSafe | published 蕴含 saved = disk = Blocks 且 checked 为真 |
| ResumeIdentity | online 蕴含 sourceOK 且 prefixOK；身份不匹配不能重连恢复 |
| EventuallyComplete | 最终 published 为真 |

下载模型只允许离线期间源文件变化或前缀失配；错误后停在拒绝恢复状态。它未分析在线修改、部分写入内容的所有组合，以及提交之后客户端状态记录的完整恢复流程。

### 为什么最终完成需要额外假设

活性配置关闭用户暂停与取消、上传错误内容、下载源变化及前缀错误，故障次数至多一次；对 Progress 和 Reconnect 或 Resume 施加弱公平性 WF。其含义是：当某个推进动作持续可执行时，调度器最终会执行它。

在这些条件下，上传 EventuallyComplete 要求每个任务最终进入 complete，下载要求最终本地提交。如果网络一直不可用、用户持续暂停或进程永远不再调度，则不承诺完成。

所有配置明确关闭 TLC 的死锁检查，以容纳完成、取消、失败、身份拒绝后的静止状态。安全检查通过不代表无死锁；本次仅在单独的活性配置中验证上述有条件的最终完成。

## 检查过程与实际结果

运行环境：macOS 27.2.1 arm64；Homebrew OpenJDK 17.0.17。TLA+ Tools v1.7.4 提供 TLC 2.19，构建修订 5a47802。采用单 worker、1 GiB 最大堆、seed = 1、fp = 0。

| 配置场景 | 不同状态 | 退出码 | 实际结果 |
| --- | --- | --- | --- |
| 下载完成见证 | 35 | 12 | 发现预期反例 |
| 下载活性 | 37 | 0 | 检查通过 |
| 下载跳过身份校验 | 14 | 12 | 发现预期反例 |
| 下载安全性 | 70 | 0 | 检查通过 |
| 上传完成见证 | 41 | 12 | 发现预期反例 |
| 双任务上传安全性 | 8464 | 0 | 检查通过 |
| 空文件上传 | 18 | 0 | 检查通过 |
| 上传活性 | 45 | 0 | 检查通过 |
| 上传重复追加 | 83 | 12 | 发现预期反例 |
| 上传提前确认 | 8 | 12 | 发现预期反例 |
| 上传提前提交 | 3 | 12 | 发现预期反例 |
| 上传跳过所有权 | 6 | 12 | 发现预期反例 |
| 单任务上传安全性 | 129 | 0 | 检查通过 |
| 上传去掉公平性 | 45 | 13 | 发现预期反例 |

“不同状态”为各配置日志中的 distinct states found，不能相加解释成一个统一模型的状态总数。反例配置只列发现反例前已探索的状态数，不表示完成了整个状态空间搜索。

6 个正确配置均报告 Model checking completed. No error has been found. 双任务上传的 8,464 个不同状态由各 2 块、各至多一次故障得到；单任务上传与下载使用 3 块，另检查 0 块上传。

退出码 12 是预期的不变量反例，13 是预期的时序性质反例。完成见证故意设定 NoCompletion 不变量，以其被违反确认完成状态确实可达。脚本仅在 14 项结果全部符合预期时整体返回成功。

## 故意修改规则后的反例

以下反例来自故意修改模型规则的对照实验。它们验证模型和检查性质能够发现对应错误，不能表述为在实际 SFT1 实现中发现了这些缺陷。原始路径见相应日志。

| 修改点 | TLC 给出的关键异常及违反性质 |
| --- | --- |
| early_ack | Receive 后 disk = 1、cp = 0；提前 SendAck 使 ack = 1，违反 AckDurable。说明 fsync 成功仍不足以立即确认，持久化偏移也必须先保存。 |
| early_finish | 初始数据尚未到达就允许 Publish，正式文件标志变真，而 disk = cp = 0，违反 PublishedIntegrity。 |
| duplicate_append | 已确认块被再次追加，使长度超出声明块数，违反 Bounds。当前实现对旧块返回已有偏移，不执行追加。 |
| no_owner | 允许 owner = FALSE 的 Resume，将 breach 置真，违反 Isolation。 |
| unchecked_resume | 离线时源身份或前缀变为无效，仍允许 Resume 令 online 变真，违反 ResumeIdentity。 |

### 没有公平性时的反例

upload_unfair 使用与正确活性模型相同的动作和参数，但不加弱公平性。TLC 输出一条有限路径后接 Stuttering 的无限行为，表示系统可以永久停在尚未完成的状态。此时安全性质仍可能成立，但 EventuallyComplete 不成立。

### 可达性对照

上传和下载各设置 NoCompletion，断言永远不会完成；TLC 均找到反例。结合正确活性配置检查，确认模型允许真正的完成路径，避免只因协议始终无法执行而让安全条件空泛成立。

## 模型与实现的对应及复现

| 模型动作 | 实际实现位置与补充测试 |
| --- | --- |
| Receive / Checkpoint / SendAck | server/ex1b/server.py 的 DATA 分支依次调用 write_chunk、database.update 后返回 ACK；storage.py 的 write_chunk 包含 pwrite 和 fsync。 |
| Verify / Publish / Complete | server.py 的 FINISH 分支检查偏移和哈希，调用 Jail.commit 后更新 complete；storage.py 用 os.link 和目录 fsync 提交。 |
| Reconnect / Resume | server.py 的 ready、RESUME 分支返回持久偏移并校验下载身份；partial_identity 截断未确认尾部。 |
| 所有权 | database.py 的 get 以 id 和 user 同时查找；test_duplicate_chunk_and_owner_check 覆盖跨用户恢复拒绝。 |
| 下载持久化与完成 | TransferEngine.swift 的 download 流程依次 Disk.write、store.save、ACK；完整校验和 FINISH 成功后才 Disk.commit。 |

补充实现验证：本次运行 .venv/bin/python -m pytest -q，终端结果为 19 passed in 6.17s。现有测试包括完整往返、长连接复用、用户并发与隔离、双端重启续传、源变化、重复块、提交冲突、路径和证书拒绝等；这些是实际运行测试，不计入形式化证明。

### 复现步骤

1. 在实验1B根目录安装 Java 11 或以上版本，并保证 python3 可用。首次运行需联网下载官方工具。

2. 执行 python3 scripts/verify_protocol.py。脚本逐个读取 formal 下的 cfg，运行 TLC，保存 stdout、stderr 及退出码。

3. 检查 formal/results/summary.json 中各项 expectation_met 均为 true；逐项日志应与本报告表格一致。运行时间和环境信息可随机器改变。

4. 如需重建报告，使用有 reportlab 的 Python 运行 scripts/build_protocol_report.py。独立报告同时更新 PDF 与 docs/protocol-verification-report.md。

工具校验：发布页 SHA-1 校验已执行；本次 JAR 的 SHA-256 为 936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88

## 结论边界与证据索引

### 可以得出的结论

在选定的有限参数和可信持久化原语假设下，模型未出现不完整上传文件被提交、确认超前于持久检查点、下载确认超前于本地检查点、无效身份恢复或未授权恢复等违反已列性质的状态。终态保持及带公平性假设的最终完成也在对应配置中通过。

### 尚未验证的范围

未证明任意数量用户、文件和无限故障下的性质；未对 TLS、SHA-256、证书实现、SQL 注入防护、目录访问、心跳时间、带宽限制、解析器及请求编号进行形式化验证。

双任务模型只覆盖不同任务的动作交错，没有共享目标和资源竞争；上传将正式链接提交抽象为成功的原子动作，不模拟 link 与 unlink 内部所有崩溃窗口、同名目标覆盖冲突及提交中取消。下载未完整建模正式文件创建之后、客户端任务状态保存之前的崩溃。

源码与模型之间只有人工对应和测试佐证。守卫直接写入模型，TLC 检查它们的组合后果，不能自动判断源码是否遗漏同一守卫。若修改协议、持久化顺序或模型，需要重新检查并更新证据。

### 证据索引

模型与全部 cfg：formal/；各场景原始输出：formal/results/<配置名>.log；机器可读汇总、命令、实现基准提交和文件散列：formal/results/summary.json；复现入口：scripts/verify_protocol.py。

### 参考资料

[1] TLA+ 项目官方 TLC 文档，https://docs.tlapl.us/using:tlc:start 。说明 TLC 的有限状态检查用途及命令行选项。

[2] TLA+ Tools v1.7.4 官方发布页，https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4 。工具版本与发布校验值来源。

[3] 项目 docs/protocol.md 及本报告列明的 Python、Swift 实现。验证基准和文件散列由脚本记录；本报告未把模型检查结果扩展为整个软件的正确性承诺。

