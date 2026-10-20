# Deployment requirements

This skill packages the current **official HTML replay console**, not the historical PPO/imitation-learning project. Core Python runtime uses only the standard library. The previously external FirstLight parser is vendored with its license and a frozen public-card alias index; it does not require Torch, pandas, pyarrow, the author's data or the full FirstLight repository.

## External products

| Component | Requirement / source |
| --- | --- |
| Host | Apple-silicon macOS14+; native UI is Cocoa/WebKit |
| Python | 3.12+; prefer Python.org or an existing managed interpreter |
| Apple tools | `xcrun`, `swiftc`, LLDB, codesign and a compatible macOS SDK; install Command Line Tools through Apple's normal flow |
| Android tools | `adb`; NDK30.0.16248370 with AArch64 clang++, llvm-readelf and AArch64 lldb-server |
| Emulator | Existing MuMu instance, user-selected configuration and local debugging access already enabled |
| Game | User's own installed matching ARM64 Tencent client; supported libg SHA256 is in the dependency lock |
| Optional browser | Edge/Chrome; manual confirmed extension installation |

Official starting points: [Python](https://www.python.org/downloads/macos/), [Apple tools](https://developer.apple.com/xcode/resources/), [Android tools](https://developer.android.com/tools/releases/platform-tools), [NDK](https://developer.android.com/ndk/downloads), [MuMu](https://mumu.163.com/).
The skill does not ship these large vendor products or accept their terms. An Agent can guide their installation, subject to the user's download/network policy and any required user confirmation. `sdkmanager 'platform-tools' 'ndk;30.0.16248370'` is an option when the user already has Google's SDK manager and has completed the relevant license steps. Do not pipe an automatic yes into license acceptance.

## Commands

From the extracted skill directory:

```sh
python3 scripts/deploy.py doctor
python3 scripts/deploy.py verify-package
python3 scripts/deploy.py install --target /absolute/new/deployment-directory --vm-dir /absolute/path/to/existing/mumu/vms/1 --instance-name 我的安卓-1
```

Required instance arguments: `--vm-dir`, `--instance-name`; select the user's actual existing instance, not the first attached device. Optional install arguments: `--ndk-bin`, `--sdk`. No simulator is launched.

After consent for device-side debugging setup:

```sh
/absolute/new/deployment-directory/.venv/bin/python3 /absolute/new/deployment-directory/official-web-replay/prepare_runtime.py --config /absolute/new/deployment-directory/deploy-config.json
python3 scripts/deploy.py doctor --target /absolute/new/deployment-directory
open /absolute/new/deployment-directory/apps/官服HTML回放.app
```

Install refuses a pre-existing nonempty target. Keep prior deployments; do not delete or overwrite them to force a retry. The generated app's Info.plist binds the new source directory and interpreter, not any original home directory.

Share the ZIP or `.skill` archive with another Agent and say:

> 请使用这个 royale-replay-deploy Skill，在我的 Mac 上部署官服 HTML 回放控制台。先检查依赖和客户端兼容性，不改网络，也不要自动开始对局。

Extract the archive into the receiving Agent's supported skills directory. For Codex this is normally `$CODEX_HOME/skills` (default `~/.codex/skills`); restart/refresh skill discovery if needed. A `.skill` file is a ZIP transport, not an automatically executed installer. Other Agent products may require manually loading `SKILL.md`.

## Completion levels

“Package verified” from verify-package = file set and hashes only. validate_payload additionally checks syntax/import/script dependencies and compile-only native closure; a successful install separately proves a desktop build.
“Desktop installed” = private venv, native app and bridge built on the target.
“Runtime prepared” = user's exact installed binary verified, fresh identity/loader contract generated, debugger staged; not a battle.
“Playback verified” = a particular authorized HTML's commands, round-trip and actual visible native battlefield checked. Do not equate these levels or promise exact results for untested versions/replays.

The optional embedded browser requires an already configured explicit HTTPS or SOCKS system proxy and deliberately has no direct fallback. A PAC-only, VPN/TUN-only or direct-only network is not enough for that browser. Local HTML playback and the standard-browser extension do not have this extra WebKit prerequisite.
