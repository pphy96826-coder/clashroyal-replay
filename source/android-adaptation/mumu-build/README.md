# MuMu 构建资料

普通使用直接安装 Release APK。运行依赖全部内置，无需 Windows 构建工具。

这些脚本保留本次 Windows 构建目录布局：work/android-mumu-adaptation 是源码；work/android-mumu-support、work/android-native-runtime/selected 与 work/android-native-compiler/selected 对应依赖包 Python 运行时的相关目录；work/package/WinReplay/tools 是历史完整 Windows 环境的 JDK17、Build-tools37 与 NDK r27d。

基础 ARM APK 来自公开的 Android hotfix10 Release。依次构建固定用途 CLI、运行时 ZIP 和 APK；逐文件校验并核验 v2/v3 签名。发布私钥不分发；自行重建会生成个人签名，不能冒充原签名覆盖安装。游戏库哈希、代码和任务归属检查不得跳过。
