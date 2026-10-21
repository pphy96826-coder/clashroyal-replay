# 纯安卓适配（安卓原生控制台）

控制台、运行时、游戏都在**同一个安卓系统**里运行：Mac 上的 MuMu 模拟器 Pro 安卓实例、已 Root 的安卓手机，或非 Root 手机里的虚拟大师虚拟机。下载、配置与图文教程见仓库的 [android/ 页面](../../android/README.md)。

- `android-adaptation/`：控制台 APK 源码、设备端运行时、构建脚本与回归测试（`python3 -m pytest tests`）。
- `official-web-replay/`：APK 内置运行时共用的回放模块（技能目标搜索、逐塔终局比对、发牌校准等）。

与仓库里的 Windows + MuMu 一体版（`source/android-adaptation/`，教程在 `docs/mumu-android/`）是两套独立适配，互不替代。
