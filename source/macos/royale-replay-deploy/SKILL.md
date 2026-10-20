---
name: royale-replay-deploy
description: Deploy the bundled RoyaleAPI HTML replay desktop console on macOS with an existing MuMu Android instance, validate its pinned official-client build and local debug prerequisites, and optionally install the click-scoped browser bridge. Use for this replay project, not general Android setup or model training.
---

# 官服 HTML 回放部署

Deploy the self-contained source payload in `assets/project`; do not reconstruct it from historical chat or require the author's checkout. It includes the parser/card alias dependency, native support sources, desktop/browser sources and global command delay of **1 second (20 ticks)**. HTML timestamps, positions, forms and terminal rules remain unchanged.

## Deployment

1. Read [deployment.md](references/deployment.md). Supported target is Apple-silicon macOS14+ with Command Line Tools, Python3.12+, Android platform-tools/NDK and an existing MuMu instance. Other platforms are not validated.
2. Run `python3 scripts/deploy.py doctor`. This is offline and does not contact an emulator. Read `assets/dependencies.lock.json` for exact external tool/build requirements. Missing prerequisites are a real blocker, not a completed deployment.
3. With the user's chosen new target and existing emulator, run `python3 scripts/deploy.py install --target <new-directory> --vm-dir <existing-instance-directory> --instance-name <name>`. It copies sources, creates a private Python environment and compiles/signs the desktop app; it does not overwrite an existing deployment or change network settings.
4. Obtain confirmation that the user wants to enable local debugging on their existing test emulator. Do not root/repack a client, weaken protections, accept agreements, install browser permissions, or start online matches automatically. Read [runtime.md](references/runtime.md), then run the installed `official-web-replay/prepare_runtime.py --config <deployment>/deploy-config.json`. It imports the user's installed matching APK locally, binds freshly obtained public metadata and prepares the local debugger. APK/system libraries are intentionally not redistributed.
5. Run the deployment doctor's target check. Open the generated app if requested. For a user-provided HTML, normal playback verifies the full native command stream and JSON round-trip before publishing its visible scene. Deployment/source tests alone are not proof of visible replay accuracy. Do not launch a test match when the user requested installation only.

For browser capture, read [browser-bridge.md](references/browser-bridge.md). Google login stays in the user's standard browser. Register the bridge only after they choose a browser and approve it; loading the extension requires their confirmation. No cookie import or CAPTCHA automation.

## Invariants

- Use only the explicitly selected existing instance's configured loopback ADB endpoint. Never create/reset an emulator, scan a LAN, reset all ADB devices or change proxy/DNS settings.
- Native support is pinned by the **full libg SHA256**, not the marketing version. A different binary requires new adaptation, not offset guessing. Ordinary stock clients may lack required debugging access; report that prerequisite rather than bypass it.
- Bind PID/start time, APK mapping, resource generation and worker afresh. A reconnect never migrates an old native handle into a new process.
- Never replace an unrelated active battle. Never resubmit a failed/pending native task automatically. Keep immutable receipts and scene/cache owners until normal release or an authorized client-only restart.
- Preserve every source command and raw source field; never skip unavailable cards or replace unsupported tower troops. Four native tower types support their legal client levels; default King level follows that side's tower troop unless explicitly provided. Skill target ambiguity may be explored only as fresh, cleanly released candidate simulations (maximum256); accept complete command execution and a full terminal tower-HP match. Label this as inferred, not a unique original target/trajectory.
- Queues accept up to128 HTML files/256MB and may parse during playback. Native simulation is serialized. Seamless return-to-lobby/scene reuse is not yet verified; do not claim a restart-free queue switch. Never automatically retry a failed native publication. Only restart the exact detached, verified owned failed game process under explicit user authorization.
- Share no downloaded personal HTML, account/session data, logs, APKs, debugger receipts or process addresses in a redistributed skill. The bundled manifest describes source/tool dependencies, not a license to redistribute third-party products.

## Verification and delivery

Run `python3 scripts/deploy.py verify-package` and `python3 scripts/validate_payload.py`. Report source validation, local build, device setup and real replay verification as separate outcomes. If installing dependencies requires a download or license acceptance, use official sources and the user's existing network policy; never silently fall back to a direct connection. See `references/deployment.md` for a copyable end-user invocation.

The desktop's “导出诊断…” uses independent read-only `diagnostic_export.py`, not an engine operation. It excludes raw HTML, binaries and browser stores but contains private paths/process/replay records. Share ZIP privately, never in public releases. The illustrated all-platform manual is under `guides/`; iOS local emulation and arbitrary Android VMs remain unverified, not turnkey deployments.
