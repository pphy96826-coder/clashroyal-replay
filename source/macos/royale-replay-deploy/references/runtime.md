# Runtime preparation and restrictions

The adapter is for one audited binary: Tencent38.4.2 ARM64, full `libg.so` SHA256 `c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55`. A matching version string alone is insufficient. The user supplies their installed APK; the bundle contains neither APK nor proprietary executable/system libraries.

`prepare_runtime.py` uses only the selected instance's configured `127.0.0.1` ADB endpoint, checks AArch64 and existing privileged debugging access, reads the installed package/APK, checks the library hash and JNI bytes, and creates a new local runtime profile. It copies this emulator's own libc/libdl and stages the NDK's lldb-server in a hash-specific local test directory. It does not attach to the game, publish a replay, patch the app, root the device or alter network settings.

Runtime needs `/proc/<game-pid>/mem` access and ptrace permitted by the emulator/client. If unavailable, stop and ask the user to provide a suitable authorized local test environment. Do not bypass an access denial. Stock-client compatibility beyond the pinned binary and existing debugging setup is NOT guaranteed.

The native library keeps local Battle initialization, command validation, tower definitions, 20Hz stepping and graphics. Only the newly created local replay controller has private frame/render callbacks; shared/global code and server-check routines must remain intact. Stop uses fresh ownership checks before a client-only restart; the emulator is left running.

First import is intentionally slower: parse → public card/tower metadata → native deal → full execution → serialize → JSON round-trip → scene. Every command and raw HTML field is retained. One-second global delay affects both deploy and ability targets once; the match clock and terminal rules are not moved. Cache identity includes execution timing and code; zero-delay cache inputs must not be treated as current inputs.

Pause: native Android controls use speed0. Zero must stop simulation accumulation without stopping the rendering pumps. Invalid negative/nonfinite rates still fail. Four tower types use their legal native levels and source-specific official SupportCard169 entries; category159 is not valid native input. King level defaults to the same side's tower troop level unless the source explicitly provides it. Royal Chef has an independent King definition. Missing/illegal levels fail explicitly, without substitution.

The queue stores immutable, SHA-checked HTML. Only pure parsing is concurrent with a running battle; candidate simulation and scene transitions remain serialized. Restart-free return to lobby is not yet validated. Battle data versions must match the replay era: binary version/hash alone cannot rule out balance-parameter changes. A terminal tower HP match is not proof of a unique original trajectory.

All native attempts and results are generated on the receiving machine. No serialized original PID, heap address, worker handle, debugger server process or original run directory belongs in the transport archive.
