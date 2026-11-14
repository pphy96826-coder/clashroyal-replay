# RoyaleAPI 回放导出（Edge / Chrome 扩展）

RoyaleAPI 在 2026-11 改版后，单场回放页 `/replay?tag=…` 已下线（返回 404），对战列表里也不再给回放链接。这个扩展改为在**有对战列表的页面**上直接批量导出回放：

- 玩家对战记录：`https://royaleapi.com/player/<玩家标签>/battles`
- 卡组胜利榜：`https://royaleapi.com/decks/ranked` 等
- 其他带 Replay（回放）按钮的对战列表页

## 安装

1. 打开 `edge://extensions`（Chrome 为 `chrome://extensions`），打开“开发人员模式”。
2. 点“加载解压缩的扩展”，选这个 `browser-extension` 文件夹。
3. 在同一个浏览器里登录 RoyaleAPI（右上角 Login）。**不登录拿不到回放数据**，扩展会提示并停下。

## 使用

1. 打开上面任一种页面，等对战列表加载完；要更多对战就先往下滚动加载。
2. 点工具栏上的扩展图标，弹出本页全部回放的列表，**默认全部勾选**。可以逐个取消，或用“全选 / 全不选”。
3. 点“导出所选”。扩展逐场请求回放（每场间隔 1.5 秒），每场存成一个 HTML 文件：
   - 位置：浏览器下载目录下的 `RoyaleAPI回放/`
   - 文件名：**对手名字**.html（2v2 为两个对手名用 `&` 连接）；同名自动变成 `名字 (1).html`。文件系统不允许的字符（`\ / : * ? " < > | ~`）换成 `_`。
4. 关闭弹窗不会中断导出；再点开图标可以看进度和每场结果。导出时不弹下载气泡。

## 文件内容

每个文件是一个完整的 HTML 页面，依次包含：

- `<script id="royaleapi-replay-export" type="application/json">`：导出信息（来源页面、回放标签、双方标签和名字、皇冠数、对战时间、模式、操作数）
- `<a href="/replay?tag=…&team_tags=…">`：与旧回放页地址相同的查询参数
- 对战那一行的 HTML：模式、双方卡组和卡牌等级、塔血、玩家名字（已去掉页面上手动展开过的回放，避免操作重复）
- `/data/replay` 返回的回放片段：`div.battle_replay[data-tag]` 里的全部操作标记（`data-x / data-y / data-c / data-t / data-i / data-s`）和结束时间标记

决斗（Crown Series Duel）一行里有 6 套卡组、三局连在一条时间线上，片段里没有分局标记；列表里会标出“3 局连续（决斗）”。

## 出错时

| 提示 | 处理 |
| --- | --- |
| 要求登录才能看回放 | 在这个浏览器里登录 RoyaleAPI，再点“导出所选”。 |
| Cloudflare 拒绝了请求，已停止 | 刷新页面，自己通过验证后再导出剩下的（列表里会标“未导出”）。扩展不会点或绕过验证。 |
| 无回放（Replay not found） | RoyaleAPI 没有这场的回放，跳过。 |
| 页面上找不到这一场 | 导出时页面被刷新或换页了；回到原页面后点“刷新列表”。 |

## 权限说明

- `host_permissions` 只有 `royaleapi.com`：读取对战列表、在页面里用你的登录状态请求 `/data/replay`。
- `scripting`：在 RoyaleAPI 页面里运行上面的读取。
- `downloads`、`downloads.ui`：保存文件；导出期间暂时关闭下载气泡，结束后恢复。
- `storage`：在浏览器会话内保存导出进度，供弹窗显示。

不读取 Cookie、密码，不上传任何数据，只在你点“导出所选”时请求 RoyaleAPI。
