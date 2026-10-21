# official-web-replay（安卓运行时共用模块）

安卓控制台 APK 内置运行时里、来自共用回放引擎的模块：发牌校准、塔楼资料、技能目标搜索与逐塔终局比对（`ability_search.py`）、场景输入、终局整理，以及原生组件的 C++ 源码。

`source/android-native/android-adaptation/scripts/refresh_playback_payload.py` 从这里把它们打进 APK；`source/android-native/android-adaptation/tests` 也会直接导入其中的模块。
