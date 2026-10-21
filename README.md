# Clash Royale 回放 · Windows + MuMu 安卓一体版

Windows 默认部署已更新为 MuMu 内的安卓 APK。控制台和运行依赖直接在安卓实例内执行，可在游戏悬浮窗操作。

[下载新版完整资料](https://github.com/pphy96826-coder/clashroyal-replay/releases/tag/mumu-android-20261021) · [详细图文教程](docs/mumu-android/安装教程.md) · [离线网页版](docs/mumu-android/安装教程.html) · [PDF](docs/mumu-android/MuMu-Replay-Installation-Guide.pdf) · [实机验收范围](docs/mumu-android/验收结果.json)

## 安装

1. 使用 MuMu 6.6.4.0 / Android 12，开启实例 Root 并重启；[MuMu 官方下载](https://mumu.163.com/download/)。
2. 安装匹配的腾讯客户端 38.4.2，自行登录并进入普通大厅。
3. 安装 `MuMu-Replay-20261021.apk`，给“MuMu回放控制台 · 测试版”允许 Root 和悬浮窗。
4. 在模拟器内 Chrome 保存发布包里的 Play Replay 书签，从完整 RoyaleAPI Replay 页面发送回放。
5. 导入后自动准备，在游戏悬浮窗点“播放下一个”，无需回到完整控制台启动。

APK 已内置 Python 3.14.8、Clang / LLDB 21.1.8、ARM64 运行工具及 MuMu 翻译辅助模块。普通使用无需 Windows Python、NDK、桌面桥接服务或旧 Edge 扩展。

## 本版功能

- 导入即排队准备。独立 HTML 解析可在当前播放时进行，最多两个进程，低内存降为一个。
- 同一个游戏进程里的原生校准、完整模拟和 JSON 核验按顺序执行。
- 悬浮窗和完整控制台都有“停止匹配，播放当前最优”。等待当前原生步骤安全结束，选择已经完整跑过的最佳对局，核验 JSON 后开播。
- 随机种子与终局优劣没有单调关系，不使用二分法，也不选择未执行的推测结果。
- 播完刷新游戏并返回控制台，保留重放／退出；下一场准备时仍可选择上一场。强退游戏后解除占用，不循环自动重播。
- “终局近似／仅胜负相同／不符”保留实际标签；停止搜索不会被当作精确还原。

## 发布文件

| 文件 | 用途 |
| --- | --- |
| MuMu-Replay-20261021.apk | 直接安装，全部回放运行依赖已内置 |
| MuMu-Replay-Offline-20261021.zip | APK、图文教程、Chrome 书签、验收与校验说明 |
| Tencent-ClashRoyale-38.4.2.apk | 匹配的游戏客户端，不含账号数据；已有该版本可沿用 |
| MuMu-Replay-Runtime-Dependencies-20261021.zip | 所有内置运行依赖的独立备份、许可与逐文件清单 |
| MuMu-Replay-Source-20261021.zip | 适配源码与测试 |
| MuMu-Replay-Installation-Guide.pdf | 离线图文手册 |
| SHA256SUMS.txt | 发布文件的 SHA-256 |

当前构建：`2026.10.21-mumu-dev21`。APK SHA-256：`70e87ba0c0df247d2bbb3f88fdd928f2d0a3469de78088ede290eff8b588377b`。

## 验证与限制

已在 MuMu 中完整执行并可见播放 141 条指令，原生 JSON 往返通过，终局 tick 6196、塔血差 0。客户端自动重开、回到大厅与实际控制台恢复事件有记录。播放中强退约 3 秒解除占用并回到控制台。新按钮设备结果见随包验收 JSON。

同一实例资料准备阶段 A/B 实测 69.95 秒 → 8.01 秒，这只是一段准备；完整预演和种子匹配仍需时间。新电脑须核验自己的实例，不将本机结果推广为所有安卓虚拟机兼容。

## 旧 Windows 方案

旧桌面适配已由本方案替换为默认入口。[历史完整环境](https://github.com/pphy96826-coder/clashroyal-replay/releases/tag/windows-mumu-20261019) 与 [旧说明](docs/历史部署入口-20261021以前.md) 保留供回退。`source/windows-adaptation/` 保留旧桌面代码和原始验证 C++ 源码，新运行时仍检查原始源码、游戏库完整哈希和代码指纹。

通用 Android 与 macOS 历史资料保留在各自目录。本次重点适配 MuMu x86_64 → ARM64 翻译层；未分发虚拟磁盘、登录信息、私钥或本机调试日志。
