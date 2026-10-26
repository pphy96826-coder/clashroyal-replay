# Issue #1：回放服务启动超时修复

对应 [issue #1](https://github.com/pphy96826-coder/clashroyal-replay/issues/1)，基于 main `d999e2289fc4fffb81fc804a4e19892b460c636b`。

## 判断与修改

上报堆栈明确指向 Android 的 `ForegroundServiceDidNotStartInTimeException`。它说明服务没有及时完成前台化，但仅凭该堆栈和零字节执行日志，不能确认是 Python 初始化、MuMu 翻译层或游戏引擎不兼容。

旧代码的 Python/工具初始化已经位于后台线程；通知首次建立仍在 `onStartCommand`，且重置、重复启动检查可以先行返回。本修复：

- 在 `onCreate` 立即建立通知渠道并调用 `startForeground`，此前不读取请求、不检查重置文件、不加载 Python、不打开游戏。
- 每次 `onStartCommand` 都先重新确认前台状态，再判断重置、重复或无效请求。被重置拦截的空闲服务解除自身 busy 并退出；不重复启动执行器。
- Android 12 及以上使用 `FOREGROUND_SERVICE_IMMEDIATE`，避免系统默认延迟展示启动通知。
- 请求读取、输入校验、Python 与工具初始化在命名工作线程执行；有效输入才向主线程提交悬浮窗／游戏请求，工作线程等待该请求处理后再启动执行器。
- 新增 `ReplayService` 日志及两份轮换的私有 `playback-service-startup*.jsonl`。写盘异步、有大小上限；尚无任务目录时也能导出这些记录。

不改游戏包、签名、Python／工具依赖、引擎校验、匹配算法或网络。不使用粘性服务恢复，不自动重发已提交的原生任务。

## 验证

构建 `2026.10.21-mumu-dev57`，版本代码 `2026102157`，实际构建日期 2026-10-26。日期前缀沿用现有构建命名。

- 344 项既有主机回归及 2 项实际 Java 诊断导出新增用例通过，共 346 项；新增用例覆盖无活动任务时导出启动日志，以及拒绝超限日志。
- 本机 MuMu / Android 12 的 10 项新生命周期检查、72 项原控制台检查通过；Windows 安装注册版本核对为 MuMu 6.8.7.0。用私有 FIFO 阻塞工作线程 7.5 秒，验证服务仍为前台、通知可见、主线程响应、重复启动不产生第二工作线程；再验证重置拦截后的 7.5 秒观察期及无任务诊断导出。
- 两次服务 `onCreate` 内的前台化耗时为 21 ms、4 ms。这只计回调内耗时，不包含 Android 调度或进程启动总时延。
- 安装前后游戏 PID、历史 active/status/service 记录哈希一致；无遗留原生工作进程。Root 与悬浮窗授权保留。
- APK 内全部 11 个依赖／原生成员与 dev54 字节相同，v2/v3 签名核验通过。

APK SHA-256：`1a378e49f17745b10c0e7857269614ef413d4fbc8514d162ceb11f08af275c51`。

本机没有 MuMu 6.8.8.0 环境，也没有本次 issue 的完整回放 HTML，未复现上报机器的原始崩溃，未进行该版本或样本的整场播放。因此这是服务生命周期修复及受控回归通过，仍需报告者在原环境验证；不能据此保证新版 MuMu 的所有 NativeBridge 路径兼容。

## 后续诊断

覆盖安装修复构建后，在原环境手动验证一次，避免自动循环重试。若仍异常，导出新的诊断 ZIP，私下提供 `console/playback-service-startup.jsonl`、前一份轮换日志及 `console/phone-service-state.json`。这些文件可能含私有路径或请求标识，不要求公开整份诊断。

复现前可采集：

```text
adb logcat -v threadtime ReplayService:I AndroidRuntime:E ActivityManager:I *:S
```

关注 `start_requested`、`on_create_foreground`、`on_start_foreground`、`worker_read_source`、`worker_runtime_start` 与 `worker_runtime_started` 的先后顺序。若已有前台化记录，随后才在执行器阶段失败，应根据新错误继续定位，不能再次归为同一个前台服务超时。

Android 官方说明：[前台服务启动超时](https://developer.android.com/develop/background-work/services/fgs/troubleshooting#foreground-service-did-not-start-in-time-exception)。
