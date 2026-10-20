# Packaging validation — 2026-10-16

These checks concern this portable source bundle, not an untested receiving device.

- Relocated source imports passed with isolated Python and site-packages disabled. No Torch, pandas or pyarrow dependency is required.
- Called-script and recipe-file dependency closure passed. SHA256 manifest covers all 63 source payload files.
- Synthetic events retained their raw fields and received the global20-tick delay exactly once.
- Native bootstrap, scene and read-only helper compiled and linked for Android AArch64. Map headers were regenerated from the author's own matching APK for this test; neither that APK nor generated resources are distributed.
- Desktop console and native-messaging bridge compiled, ad-hoc signed and signature-verified in a fresh deployment path containing spaces and Chinese characters. Tested desktop SDK: macOS26.5.
- Configured ADB path priority has an isolated regression test.

No emulator, game process, browser login, public endpoint or online match was contacted by these packaging checks. Receiving-machine runtime preparation and a real authorized HTML playback remain distinct required verification stages. Do not call installation-only receipts a successful battle test.
