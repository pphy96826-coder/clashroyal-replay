# Windows 回放控制台适配（实验版）

本目录独立于 Mac 原项目，源自已核对哈希的回放 Skill。**当前没有 Windows 实机/虚拟机测试结果，不是已验证可用的 Windows 正式版。**

## 本轮已实现

- Tkinter 桌面入口：选择 HTML、播放、停止/取消、倍速、日志与原生实际进度。
- Windows 文件锁、UTF-8 文件与子进程协议、NDK `.exe` 工具路径。
- 明确的本机 ADB 端点绑定；每次观察重读配置，端口变化拒绝旧句柄。
- 可配置 LLDB，环境检查要求 Python 脚本和 `remote-android` 插件可用。
- Windows 源码安装器及不连接设备的验收测试入口。
- 完整指令、全局 +1秒、版本指纹、所有权、失败不自动重提等原有约束保持。

## 必须满足的条件

目标控制端为 Windows x64、Python 3.12+（安装时带 Tkinter）、ADB、NDK `30.0.16248370`、支持 Python 脚本及 Android 远程调试的 LLDB。

**Android 目标仍必须是 `arm64-v8a` 且使用已适配的腾讯38.4.2库，完整 SHA256 仍须匹配。Windows x64 控制端不意味着 x86_64 Android 引擎也兼容。** Windows 模拟器若运行 x86/x86_64 或 ARM 翻译层，将被当前检查拒绝，不能只修改架构检查强行通过。现有测试设备还须具备允许的调试访问。

不创建模拟器，不接受协议，不提升权限、不更改代理/DNS、不扫描端口、不重置 ADB server。

## Windows 上的准备与安装

以下路径均为示例，必须替换为接收方真实路径。先解压整个 `windows-adaptation` 目录，用 PowerShell 切到该目录。

1. 用户在自己的模拟器配置中确认该实例的本机 ADB 端口。下面的端口仅为示例，不能猜测或扫描：

```powershell
py -3.12 -X utf8 scripts/windows_setup.py select-device --output "C:\ReplayConfig\android1.json" --name "我的安卓-1" --port 16384
```

生成的是本项目的显式绑定文件，不是通用 MuMu 配置解析器。实例端口变化后须据真实配置更新此文件；程序会重新读取，但不会擅自选择其他设备。

2. 安装到一个不存在的新目录（LLDB 需要满足上述脚本/插件条件，不是任意 `lldb.exe` 都行）：

```powershell
py -3.12 -X utf8 scripts/windows_setup.py install --target "C:\ReplayConsole" --binding-file "C:\ReplayConfig\android1.json" --adb "C:\Android\platform-tools\adb.exe" --lldb "C:\LLVM-with-Python\bin\lldb.exe" --ndk-bin "C:\Android\Sdk\ndk\30.0.16248370\toolchains\llvm\prebuilt\windows-x86_64\bin"
```

安装器不下载依赖，不写浏览器注册表，失败保留现场。没有通过主机前提检查时，不产生“安装成功”结论。

3. 双击新目录中的 `Start-Replay.cmd`。先检查环境；用户确认本地调试准备后，再点“准备本机运行时”。该步检查自己的客户端并生成本机资源，不会创建回放。

也可手动运行：

```powershell
& "C:\ReplayConsole\.venv\Scripts\python.exe" -X utf8 "C:\ReplayConsole\official-web-replay\prepare_runtime.py" --config "C:\ReplayConsole\deploy-config.json"
```

4. 运行时完成后选择完整回放 HTML，点击播放，在所选安卓设备中观看原生战场。控制台启动不会立即连接设备；用户发起操作后才连接。

## 本地验收

```powershell
py -3.12 -X utf8 -m unittest discover -s tests -v
py -3.12 -X utf8 scripts/windows_setup.py doctor --config "C:\ReplayConsole\deploy-config.json"
```

单测和静态导入通过不等于 Windows 调试器可用，更不等于真实回放通过。最后还必须在 Windows 上检查界面、客户端库、完整指令、往返导入、画面、暂停和逐座塔血。

## 暂未完成 / 待验证

- Windows 原生运行、Tk 字体与文件选择器的真实交互测试。
- Windows LLDB 的 Python/Android 插件与当前 native 调用链实测。
- Windows 模拟器 ARM64 原生调试可行性；不能保证常见 x64 模拟器适用。
- 浏览器 Native Messaging 的 Windows 主机及注册。当前仅提供本地 HTML 导入；未宣称一键网页播放可用。
- 无电脑、纯安卓手机独立版不在本目录的适配范围内。

Windows 默认 ACL 与 POSIX `0700/0600` 不等价；请选择自己用户的私有目录，勿把含账号信息的 HTML/日志放在公共共享目录。

工具依据：[NDK 构建工具说明](https://developer.android.com/ndk/guides/other_build_systems)、[Python Windows 文件锁](https://docs.python.org/3/library/msvcrt.html)、[Android ABI](https://developer.android.com/ndk/guides/abis)。
