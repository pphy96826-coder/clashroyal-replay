# Clash Royale 官服 HTML 回放

把 RoyaleAPI 完整 Replay 详情页的 HTML 转成指令，在锁定版本（38.4.2）的腾讯安卓客户端里用游戏自己的战斗引擎重新跑一遍。当前所有最新版本均采用**控制台、游戏、浏览器运行在同一个安卓环境内**的架构。区别在于 APK 的架构适配：**Windows + MuMu** 因架构与翻译运行时不同，需要使用单独翻译适配的回放控制台 APK；**Mac + MuMu 模拟器 Pro、已 Root 的安卓手机、非 Root 安卓手机中的虚拟大师**这三种方案可共用同一个回放控制台 APK。

## 选择你的平台

| 平台 | 安装教程 | 下载 | 源码文件夹 |
| --- | --- | --- | --- |
| **Mac**（Apple Silicon，MuMu 模拟器 Pro） | [纯安卓适配教程 · 第 3 节](android/README.md) | [hotfix54](https://github.com/pphy96826-coder/clashroyal-replay/releases/tag/replay-sync-20261021-hotfix54) | [`source/android-native/`](source/android-native/README.md) |
| **Windows**（MuMu 6.6.4.0） | [Windows + MuMu 一体版教程](docs/mumu-android/安装教程.md) | [mumu-android hotfix3](https://github.com/pphy96826-coder/clashroyal-replay/releases/tag/mumu-android-20261022-hotfix3) | [`source/android-adaptation/`](source/android-adaptation/README.md)（共用模块在 `source/windows-adaptation/project/`） |
| **已 Root 的安卓手机** | [纯安卓适配教程 · 第 4 节](android/README.md) | [hotfix54](https://github.com/pphy96826-coder/clashroyal-replay/releases/tag/replay-sync-20261021-hotfix54) | [`source/android-native/`](source/android-native/README.md) |
| **非 Root 的安卓手机**（虚拟大师，实验性） | [纯安卓适配教程 · 第 5–7 节](android/README.md)；[其他方案](docs/非Root安卓与iOS播放方案.md) | [hotfix54](https://github.com/pphy96826-coder/clashroyal-replay/releases/tag/replay-sync-20261021-hotfix54) | [`source/android-native/`](source/android-native/README.md) |
| iPhone / iPad | 没有本机方案，只能远程观看：[可能的播放方法](docs/非Root安卓与iOS播放方案.md) | — | — |

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `android/` | 纯安卓适配页面：完整图文教程（Markdown / PDF / 离线 HTML）、截图、更新说明 |
| `source/android-native/` | 纯安卓适配源码：控制台 APK、设备端运行时、测试、共用回放模块 |
| `docs/mumu-android/` | Windows + MuMu 一体版教程、PDF、修复说明与验收记录 |
| `source/android-adaptation/` | Windows + MuMu 一体版 APK 源码与构建脚本 |
| `source/windows-adaptation/` | 旧 Windows 桌面代码与原始验证源码；一体版仍使用其中的共用模块 |
| `docs/非Root安卓与iOS播放方案.md` | 非 Root 安卓与 iOS 的可选方案 |
| `docs/组件来源与许可.txt` | 第三方组件来源与许可 |
| `scripts/build_android_manual.py` | 从 `android/README.md` 生成 PDF 与离线 HTML |

旧的全平台教程、旧 Windows 安装器、旧 Edge 桌面扩展和已停用的 macOS 桌面版已从仓库移除；需要时可在 git 历史和旧 Releases 中找到。

## Windows + MuMu 一体版

Windows 默认部署已更新为 MuMu 内的安卓 APK。控制台和运行依赖直接在安卓实例内执行，可在游戏悬浮窗操作。

[下载新版完整资料](https://github.com/pphy96826-coder/clashroyal-replay/releases/tag/mumu-android-20261022-hotfix3) · [详细图文教程](docs/mumu-android/安装教程.md) · [离线网页版](docs/mumu-android/安装教程.html) · [PDF](docs/mumu-android/MuMu-Replay-Installation-Guide.pdf) · [实机验收范围](docs/mumu-android/验收结果.json)

### 安装

1. 使用 MuMu 6.6.4.0 / Android 12，开启实例 Root 并重启；[MuMu 官方下载](https://mumu.163.com/download/)。
2. 安装匹配的腾讯客户端 38.4.2，自行登录并进入普通大厅。
3. 安装 `MuMu-Replay-20261022.apk`，给“MuMu回放控制台 · 测试版”允许 Root 和悬浮窗。
4. 在模拟器内 Chrome 保存发布包里的 Play Replay 书签，从完整 RoyaleAPI Replay 页面发送回放。
5. 导入后自动准备，在游戏悬浮窗点“播放下一个”，无需回到完整控制台启动。

APK 已内置 Python 3.14.8、Clang / LLDB 21.1.8、ARM64 运行工具及 MuMu 翻译辅助模块。普通使用无需 Windows Python、NDK、桌面桥接服务或旧 Edge 扩展。

### Hotfix3 更新

- 先固定种子比较技能组合，选择六座塔逐项绝对血差合计最小的完整对局，再固定技能组合搜索随机种子。
- 有完整结果后，技能搜索与种子搜索都能安全停止并播放当前最优；未执行完整的候选不参加评选。
- 切后台暂停、同一客户端回大厅恢复；预留正式播放容量；中断解包可恢复。
- MuMu 加载组件前观察宿主主线程等待位置，避免从翻译执行上下文直接调用；函数失败仍不重试。
- 同一 85 指令 / 16 次技能 / 3 次猎人回放实际完整播放；最终六塔血差 1492，按实际标签保留。82 项 Python、10 项 Java 和 60 项控制台检查通过。
- [根因、实机范围和限制](docs/mumu-android/修复说明.md)。

### Hotfix2 历史更新

- 统一检查公主塔、炮塔、匕首女爵、皇家厨师，修复特殊编号被漏记导致不开播。
- 去掉 owner0 多余镜像，双方按固定出生顺序逐塔比较；3408、4275 的假差 1734 修正为 0，不排序或择优交换。
- 修复毁塔编号符号、皇家厨师国王塔编号及终局记录所有权交接；播完刷新并自动返回控制台。
- 55 条指令原始回放在新版完整播放，六塔血差 0、种子重试 0。53 项主机回归、60 项控制台检查，以及 16 种塔楼组合的隔离原生观察器检查通过。
- [历史根因、六塔数值与验证范围](docs/mumu-android/Hotfix2-历史说明.md)。组合检查不等同于 16 种完整实战均已播放。

### Hotfix1 历史更新

游戏客户端未变化：[下载仓库原有的腾讯 38.4.2 安装包](https://github.com/pphy96826-coder/clashroyal-replay/releases/download/mumu-android-20261021/Tencent-ClashRoyale-38.4.2.apk)。新版下载页沿用此已校验文件，已有匹配客户端无需重装。

- 只有实际打出猎人，或使用可明确归属骷髅帝王的技能，且终局不匹配时搜索种子。
- 修复毁塔后存活公主塔列表被误当成固定左右槽位的问题；双塔顺序保留，不排序凑匹配。
- 同一 106 指令回放重新完整核验播放：0 次种子重试，战报血差 0，毁塔侧保留未核定标记。
- [历史说明与已纠正项](docs/mumu-android/Hotfix1-历史说明.md)。

### 本版功能

- 导入即排队准备。独立 HTML 解析可在当前播放时进行，最多两个进程，低内存降为一个。
- 同一个游戏进程里的原生校准、完整模拟和 JSON 核验按顺序执行。
- 悬浮窗和完整控制台都有“停止匹配，播放当前最优”。等待当前原生步骤安全结束，选择已经完整跑过的最佳对局，核验 JSON 后开播。
- 随机种子与终局优劣没有单调关系，不使用二分法，也不选择未执行的推测结果。
- 播完刷新游戏并返回控制台，保留重放／退出；下一场准备时仍可选择上一场。强退游戏后解除占用，不循环自动重播。
- “终局近似／仅胜负相同／不符”保留实际标签；停止搜索不会被当作精确还原。

### 发布文件

| 文件 | 用途 |
| --- | --- |
| MuMu-Replay-20261022.apk | 直接安装，全部回放运行依赖已内置 |
| MuMu-Replay-Offline-20261022.zip | APK、图文教程、Chrome 书签、验收与校验说明 |
| Tencent-ClashRoyale-38.4.2.apk | 匹配的游戏客户端，不含账号数据；已有该版本可沿用 |
| MuMu-Replay-Runtime-Dependencies-20261022.zip | 所有内置运行依赖的独立备份、许可与逐文件清单 |
| MuMu-Replay-Source-20261022.zip | 适配源码与测试 |
| MuMu-Replay-Installation-Guide.pdf | 离线图文手册 |
| SHA256SUMS.txt | 发布文件的 SHA-256 |

当前构建：`2026.10.21-mumu-dev32`。APK SHA-256：`34c48a78c3ea6c04cfad6be559c81f6052fbb0f01fe00bd45ba876513a2973ff`。

### 验证与限制

已在 MuMu 中完整执行并可见播放 141 条指令，原生 JSON 往返通过，终局 tick 6196、塔血差 0。客户端自动重开、回到大厅与实际控制台恢复事件有记录。播放中强退约 3 秒解除占用并回到控制台。Hotfix1 的最新 106 指令完整播放和种子搜索限制见随包验收 JSON。毁塔后的来源列表不证明具体左右侧；历史“精确”指塔血记录匹配，不能证明过程唯一。

同一实例资料准备阶段 A/B 实测 69.95 秒 → 8.01 秒，这只是一段准备；完整预演和种子匹配仍需时间。新电脑须核验自己的实例，不将本机结果推广为所有安卓虚拟机兼容。

### 旧 Windows 桌面方案

旧桌面适配已由本方案替换为默认入口。[历史完整环境](https://github.com/pphy96826-coder/clashroyal-replay/releases/tag/windows-mumu-20261019) 仍在 Releases 中保留供回退。`source/windows-adaptation/` 保留旧桌面代码和原始验证 C++ 源码，一体版的构建与测试仍使用其中的 `project/official-web-replay/`。

## 纯安卓适配 · 2026-10-21 hotfix54

[安卓适配页面与完整图文教程](android/README.md) · [下载 APK 与完整资料包](https://github.com/pphy96826-coder/clashroyal-replay/releases/tag/replay-sync-20261021-hotfix54) · [更新说明与验证范围](android/更新说明-hotfix54.md)

- 控制台、游戏、Edge 都装在同一个安卓系统里：Mac 上 MuMu 模拟器 Pro 的安卓 12 实例、已 Root 手机，或非 Root 手机里的虚拟大师虚拟机。原 macOS 桌面版已停用。
- **同一场回放可稳定复现**：随机种子按对局内容生成（与网页保存几次无关），并记住每场最接近的种子，下次第一个就试。
- 英雄技能先选六塔血差最小的组合再匹配随机种子；分支定界剪枝、“先筛选后精修”的种子搜索。
- 调试器丢失游戏进程后自动重启游戏继续准备；游戏短暂不在大厅或任务队列拒绝时安全卸载并重试。新增「冻结卡顿的指纹服务」「清理旧运行环境和任务记录」按钮。
- 教程第 13 节列出了[常见的播放失败情形](android/README.md#13-常见的播放失败情形)及处理方法。
- MuMu 实机验证：092PYR8PUC9R、02RYPY228YCQ 六座塔与网页完全一致；极端回放 02JYPPC02YUL 完整播放（终局近似）。虚拟大师路线仍为**实验性**。
