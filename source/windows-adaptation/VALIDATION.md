# 本轮验证记录

日期：2026-10-16。执行主机为 Apple Silicon macOS，不是 Windows。

- 20 项测试通过：源码导入、Windows 编译命令构造、模拟的 msvcrt 锁分支、真实本机跨进程互斥、中文路径、显式设备选择、端口更新后拒绝旧身份、LLDB 前提检查分支、完整事件与统一 +20tick、重复延时拒绝、初始化/场景头文件生成。
- Android ARM64 bootstrap、scene、只读读取器均在本机使用 NDK 编译/链接通过；输入为合成夹具，没有执行生成的原生代码。
- 原生 C++/头文件与上游哈希一致；没有改引擎、暂停、塔楼或命令语义。
- 原 Mac Skill 的 63 文件清单验证仍通过；本轮未更改原项目或原 Skill。
- 未联系安卓设备，未启动虚拟机，未修改网络，未进行 Windows 实机回放。

**尚不可勾选：** Windows 图形交互、真实 Windows msvcrt 竞争、Windows LLDB 原生调用、Android 设备运行时、实际 HTML 回放与逐塔血量一致。

后续在真实 Windows 中先运行 `scripts/Verify-Windows.ps1`。该脚本只记录源码单测结论，不会把界面/设备/回放标记为通过。然后按 README 检查与部署，最后由用户授权一场真实回放验收。
