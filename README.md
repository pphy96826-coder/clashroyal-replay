# Clash Royale HTML 回放：Android / macOS / Windows

## 2026-10-19 同步更新

新版三平台资源见 [Releases](https://github.com/pphy96826-coder/clashroyal-replay/releases)。本次同步回放队列、等级支持、技能分支诊断、原生塔血校验与失败恢复。详见 [更新说明与验证范围](docs/更新说明-20261019.md)。

- Android：`source/android-adaptation/` 是控制台源码；APK及内置运行依赖在发布包中，仍需要兼容的现有root调试环境。
- macOS：`source/macos/royale-replay-deploy/` 为可独立部署的源码Skill，安装到新目录，沿用已有MuMu实例。
- Windows：保留已验证的MuMu翻译运行时连接层；已有完整环境可用本次小体积更新包，不必重新下载下述旧版3GB环境。关闭控制台后运行更新包的 `Update-Windows.cmd`。

结束后当前采用“核验归属→释放现场→自动重新打开客户端”的兜底方案，**不是免重启返回大厅**。Windows新版尚未在Windows实机验收；不要将源码检查或Mac编译成功等同于实机播放验证。

## Windows 原完整环境（继续保留）

用于在 Windows 与 MuMu Android 12 实例上运行腾讯客户端本地回放，支持 Edge 插件发送 RoyaleAPI 完整回放网页，以及本地 HTML 导入。

## 下载与安装

完整环境包放在本仓库 Releases 中。下载同一版本的 `.zip.001`、`.zip.002`、`.zip.003` 三卷和 `Merge-Environment.cmd`，放在同一文件夹。双击合并程序，等待 SHA-256 校验通过，再完整解压 ZIP。也可以用支持分卷的 7-Zip 打开第一卷进行解压。

1. 阅读 [图文安装教程](docs/安装教程.pdf)，或下载仓库后打开 [离线网页版教程](docs/安装教程.html)。
2. 完整环境包含 Python、NDK/LLDB、JDK、Android Build-tools、ADB、适配程序、浏览器插件、客户端 APK 及运行时参考。
3. MuMu 按需从 [官方网站](https://mumu.163.com/download/) 安装；本项目实测 MuMu 6.6.4.0 + Android 12 + 腾讯客户端 38.4.2。
4. 解压后运行 `00-Install.cmd`，绑定当前实例，检查环境并准备运行时，再连接 Edge 插件。账号由使用者在 MuMu 中自行登录。

## 行为与验证

- 原生回放完成后自动返回控制台，可重新回放或退出，并刷新本工具拥有的客户端。
- 客户端被强制关闭后，控制台清理播放状态并恢复操作。
- 37 项源码回归测试通过；完整环境经过逐文件 SHA-256 校验及含中文、空格目录的迁移自检。
- 新电脑仍须重新绑定实例、校验运行时并完成播放验收。参考运行时不是目标电脑已部署成功的证明。

## 源码与文件说明

`source/windows-adaptation/` 保存适配源码、测试与来源记录；`install/` 是完整环境包的安装向导源码；`browser-extension/` 是 Edge 扩展。仓库源码本身不含大型工具链。请用 Releases 完整环境安装。各组件许可见 [组件来源与许可](docs/组件来源与许可.txt) 和对应组件原有文件。

完整环境 ZIP 的 SHA-256：

`529b5acca37563a4dc193d14e739c2f943552666bada9a70684e3c577798a91c`
