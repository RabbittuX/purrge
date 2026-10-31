<div align="center">

<img src="runtime/assets/icon-256.png" width="120" alt="Purrge">

# Purrge

**基于 AI 的磁盘空间管理工具（macOS / Windows）：低空间预警、智能识别可清理项、经用户审批后执行清理。**

<sub>名称取自 purr（猫咪呼噜）与 purge（清除）· by RabbittuX</sub>

<br>

<img src="https://img.shields.io/badge/macOS%20%7C%20Windows-1c1b22?style=flat-square" alt="macOS | Windows"> <img src="https://img.shields.io/badge/AI-Claude_Code_%7C_Codex_%7C_WorkBuddy_%7C_DeepSeek-f2a33a?style=flat-square" alt="AI 引擎"> <img src="https://img.shields.io/badge/License-PolyForm_Noncommercial-e5484d?style=flat-square" alt="License">

<br>

<img src="docs/screenshots/review.png" alt="Purrge 审查页" width="100%">

</div>

<br>

## 🆕 v0.3.4 更新内容

- **修复**：Windows 上卸载后，`purrge` 命令在部分电脑上要过 10 秒左右才被删除，这期间运行 `purrge` 会报错（[#3](https://github.com/RabbittuX/purrge/pull/3)）。现在卸载结束约 2 秒后就会删除。感谢 @NaIWaniubi 报告并修复。

## 🆕 v0.3.3 更新内容

- **修复**：Windows 上「Edge 浏览器缓存」一直清理不掉：它在受保护的 `%LOCALAPPDATA%/Microsoft` 文件夹里，被保护名单整体挡住了（[#4](https://github.com/RabbittuX/purrge/pull/4)）。现在只放行 Edge 的 Cache 和 Code Cache 文件夹，Edge 的密码、Cookies、书签以及 Outlook、Teams、OneDrive 等数据仍然受保护。感谢 @NaIWaniubi 报告并修复。

## 🆕 v0.3.2 更新内容

- **修复**：Claude Code 开启 verbose（详细输出）时，安装的连接测试和 `purrge scan` 的 AI 判断会崩溃（[#1](https://github.com/RabbittuX/purrge/issues/1)）。感谢 @jiangwanyutao 报告并提供修复方案。

## 🆕 v0.3.1 更新内容

- **Windows 两行命令安装，不需要网址**：Purrge 已发布到微软官方的 PowerShell Gallery，`Install-Module Purrge` + `Install-Purrge` 即可安装；模块自带完整代码，安装时不再访问 GitHub。

## 🆕 v0.3.0 更新内容

- **支持 Windows**：Windows 10 / 11 / Windows Server 均可使用，后台检查用「任务计划程序」，清理的文件进回收站，提醒窗和系统通知都是原生样式。
- **新增两个 AI 引擎**：WorkBuddy（CodeBuddy 命令行，与 WorkBuddy 同一账号、同一积分）和 DeepSeek Harness（使用自己的 DeepSeek API Key）。两者都在关闭全部工具的模式下运行，只能给出建议、不能动文件。
- **一条命令更新**：新增 `purrge update`，自动备份旧版本，新版本自检不通过会自动换回；有新版本时 `purrge status` 和审查页会提示。
- **零门槛安装**：电脑上没有 Python 或 Node.js 时，安装程序会自动下载官方版本安装（只装给当前用户，不需要管理员权限），全程显示下载进度，网络不稳定时自动重试。
- **更干净的卸载**：`purrge uninstall --purge` 会一并清掉后台任务、`purrge` 命令、AI 里的说明文件、设置与扫描记录。

> 从 0.2.x 升级请看[更新](#-更新)一节：旧版本需要手动更新这一次，之后就能用 `purrge update` 了。

## ✨ 核心功能

<table>
<tr>
<td width="33%" valign="top">

**🔔 低空间预警**

后台服务定时检测磁盘剩余空间，低于设定阈值时发出提醒。检测过程不调用 AI，不消耗额度。

</td>
<td width="33%" valign="top">

**🧠 AI 智能分析**

调用本机的 Claude Code、Codex、WorkBuddy 或 DeepSeek Harness，对缓存、安装包、媒体文件及历史项目逐项评估，说明其用途、闲置时长及清理影响。

</td>
<td width="33%" valign="top">

**✅ 用户审批**

可重建的缓存默认选中，用户文件默认不选。仅执行用户勾选并确认的清理项，AI 不具备删除权限。

</td>
</tr>
</table>

## 📸 界面预览

<table>
<tr>
<td width="50%" valign="top">
<img src="docs/screenshots/popup-card.png" alt="低空间提醒">
<p align="center"><b>低空间提醒</b><br><sub>选择「帮我看看」即开始扫描，完成后自动打开审查页面</sub></p>
</td>
<td width="50%" valign="top">
<img src="docs/screenshots/settings.png" alt="设置面板">
<p align="center"><b>设置面板</b><br><sub>可调整阈值、检查频率与提醒间隔，保存后即时生效</sub></p>
</td>
</tr>
<tr>
<td colspan="2">
<img src="docs/screenshots/list.png" alt="待确认项目">
<p align="center"><b>待确认项目</b><br><sub>支持按类别筛选，可通过「打开文件夹 / 在访达中定位」预先查看内容</sub></p>
</td>
</tr>
</table>

## 🚀 安装

> [!WARNING]
> **请认准官方来源。** Purrge 只有两个官方仓库：`RabbittuX/purrge` 和 `RabbittuX/homebrew-tap`（作者名 RabbittuX，两个 t、结尾大写 X）。
> - GitHub 上另有多个同名的 purrge 项目，与本项目无关，其中部分自称"清理垃圾"的项目来源不明，请勿安装。
> - Homebrew 中的 `purge`（单个 r）是另一款软件；请使用完整名称 `rabbittux/tap/purrge`。
> - PowerShell Gallery 中的官方模块名为 `Purrge`（作者 RabbittuX，发布账号 yin），页面地址 powershellgallery.com/packages/Purrge。
> - 安装开始时会显示「Purrge 版本号 by RabbittuX　官方来源：GitHub RabbittuX/purrge」，可据此核对；也可随时运行 `purrge version` 查看。

### macOS

**方式一：Homebrew（推荐）**

```bash
brew install rabbittux/tap/purrge
purrge install
```

**方式二：一键脚本**

```bash
curl -fsSL https://raw.githubusercontent.com/RabbittuX/purrge/master/install.sh | bash
```

<details>
<summary>其他方式（国内网络访问不了 raw.githubusercontent.com 时 / 从源码 / 非交互）</summary>

```bash
# 国内网络：改从 codeload 下载完整代码再安装
curl -fsSL https://codeload.github.com/RabbittuX/purrge/tar.gz/refs/heads/master | tar -xz -C /tmp && bash /tmp/purrge-master/install.sh

# 从源码安装
git clone https://github.com/RabbittuX/purrge.git
cd purrge && bash install.sh

# 非交互式安装（engine 可选 claude / codex / workbuddy / deepseek）
bash install.sh --engine codex --threshold 20 --yes
```

</details>

### Windows

打开「Windows PowerShell」（不需要管理员权限），执行：

```powershell
Install-Module Purrge -Scope CurrentUser
Install-Purrge
```

- 第一次使用 `Install-Module` 时，Windows 会询问是否安装 NuGet 组件、是否信任 PSGallery 仓库，输入 `Y` 回车即可。
- 没有 Python 时会询问并自动安装（只装给当前用户）。安装完成后**重新打开一个 PowerShell 窗口**即可使用 `purrge` 命令。
- 模块里自带完整代码，安装过程不访问 GitHub。

<details>
<summary>其他安装方式（一行脚本 / 国内网络备用命令）</summary>

```powershell
# 一行脚本（从 GitHub 下载）
[Net.ServicePointManager]::SecurityProtocol = 'Tls12'; irm https://raw.githubusercontent.com/RabbittuX/purrge/master/install.ps1 | iex
```

上面这条报错「基础连接已经关闭」或「连接被重置」时（国内网络经常拦截 `raw.githubusercontent.com`），改用下面这条，从 `codeload.github.com` 下载完整代码后安装：

```powershell
[Net.ServicePointManager]::SecurityProtocol='Tls12'; $ProgressPreference='SilentlyContinue'; $t="$env:TEMP\purrge-dl"; Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory $t | Out-Null; Invoke-WebRequest https://codeload.github.com/RabbittuX/purrge/zip/refs/heads/master -OutFile "$t\p.zip" -UseBasicParsing; Expand-Archive "$t\p.zip" $t; iex (Get-Content -Raw -Encoding UTF8 (Get-ChildItem $t -Recurse -Filter install.ps1 | Select-Object -First 1).FullName)
```

</details>

### 由 AI 代为安装（macOS / Windows）

在 Claude Code、Codex 或 WorkBuddy 中输入：

> 帮我安装 GitHub 上的 RabbittuX/purrge，只认作者 RabbittuX，找不到就先问我，不要安装同名的其他项目

AI 会读取本仓库的[安装指引](#-ai-助手安装指引)完成安装，并自动选用当前的 AI 作为分析引擎。

### 安装过程

1. **选择 AI 引擎**：Claude Code、Codex、WorkBuddy 或 DeepSeek Harness（由 AI 代为安装时自动选择当前 AI）。
2. **设置提醒阈值**：剩余空间低于该值时发出提醒，默认 15 GB。
3. **配置 AI 引擎**：未安装时自动安装最新版本（需要 Node.js 时先询问并自动安装）；未登录时引导登录；最后进行连接测试，确认引擎可正常响应。
4. **启用后台监控**：安装完成后，Purrge 以后台服务形式独立运行，无需保持 AI 软件处于打开状态。

### 支持的 AI 引擎

| 引擎 | 调用方式 | 说明 |
|---|---|---|
| Claude Code | `claude -p --tools ""` | 关闭全部工具 |
| Codex | `codex exec --sandbox read-only` | 只读沙箱，支持免费账号 |
| WorkBuddy | CodeBuddy 命令行 `codebuddy -p --tools ""` | 关闭全部工具；与 WorkBuddy 同一账号、同一积分；首次需运行 `codebuddy` 并输入 `/login` 登录 |
| DeepSeek Harness | `dsh --profile headless` + 关工具补丁 | 关闭全部工具，补丁未生效时拒绝调用；需要 DeepSeek API Key，只保存在本机 |

随时切换：`purrge engine claude | codex | workbuddy | deepseek`。

## 🔄 更新

```bash
purrge update
```

自动识别安装方式（Homebrew / 脚本），先备份再更新，设置、扫描记录和 AI 引擎都保留；新版本自检不通过会自动换回旧版本。有新版本时，`purrge status` 和审查页会提示。

> [!NOTE]
> **从 0.2.x 升级**：0.2.x 还没有 `purrge update` 命令，需要手动更新这一次，之后就可以用 `purrge update` 了。
> - Homebrew 安装的：`brew upgrade rabbittux/tap/purrge && purrge update`（设置和 AI 引擎都保留）
> - 脚本安装的：重新运行一遍上面的安装命令

## 🐾 使用方法

| 操作 | 终端命令 | 在 Claude Code / Codex / WorkBuddy 中说 |
|---|---|---|
| 立即扫描 | `purrge scan` | "磁盘快满了，帮我清理一下" |
| 重新打开上次的审查页 | `purrge review` | — |
| 查看状态 | `purrge status` | "硬盘还剩多少" |
| 修改阈值 | `purrge config thresholdGB 20` | "阈值改成 20G" |
| 查看 / 切换 AI 引擎 | `purrge engine`、`purrge engine workbuddy` | — |
| 更新到最新版 | `purrge update` | "帮我更新 Purrge" |
| 停用提醒 | `purrge uninstall` | "关掉磁盘提醒" |
| 查看版本 | `purrge version` | — |

- 扫描完成后会自动在浏览器打开审查页面：勾选要清理的项目，点「清理」后才会执行。
- 阈值、检查频率等参数也可在审查页面右上角的「设置」中修改。

## 🗑️ 卸载

```bash
purrge uninstall           # 关闭后台监控，移除 purrge 命令和 AI 里的说明文件（保留设置和扫描记录）
purrge uninstall --purge   # 同时删除设置、扫描记录以及 Purrge 自带的 Node.js
```

- **Homebrew 安装的**：再运行 `brew uninstall purrge`。
- **通过 PowerShell Gallery 安装的**：再运行 `Uninstall-Module Purrge`。
- **Windows**：在 PowerShell 中执行上面的命令即可，后台的「任务计划程序」任务、通知登记会一并清除。
- 安装时自动装上的 Python、Node.js（系统里原本没有的）不会被删除；不再需要时可在系统中自行卸载。

## ⚙️ 工作原理

```text
后台检测（每 30 分钟）──低于阈值──▶ 提醒用户 ──用户同意──▶ 扫描（约 10 秒）
                                                            │
      执行清理 ◀──用户确认── 审查页面 ◀── AI 逐项分析（约 30～60 秒）
```

审查页面将分析结果分为三类：

| 分类 | 范围 | 默认状态 | 处理方式 |
|---|---|---|---|
| 🟢 **首要清理** | 可自动重建的缓存（浏览器、npm、Xcode、剪映等） | 已选中 | 直接删除 |
| 🟡 **需要你决定** | 用户文件及重建成本较高的内容 | 未选中 | 移至废纸篓 / 回收站（可在设置中改为直接删除） |
| 🔒 **不会清理** | 保护名单内的路径、版本库、使用中的项目 | 不可选 | 仅作展示 |

<details>
<summary>扫描范围</summary>

- 内置缓存规则库：浏览器、npm / pip / Homebrew、Xcode、剪映、常用 IDE 等
- macOS：`~/Library/Caches` 下的大型缓存目录、通过 Spotlight 检索的 500 MB 以上文件
- Windows：临时文件夹（`%TEMP%`）、`AppData` 下的浏览器与开发工具缓存、常用目录中的大文件
- 下载、桌面、文稿、影片等常用目录中 1 GB 以上的文件夹

</details>

## 🔒 安全机制

- **AI 仅提供分析，不具备删除权限**：Claude Code、WorkBuddy、DeepSeek Harness 在禁用全部工具的模式下运行，Codex 在只读沙箱中运行；删除操作由脚本严格依据用户勾选的清单执行。
- **执行前逐项复核**：确认路径仍然存在、不在保护名单内、扫描后未被修改，任一条件不满足即跳过。
- **保护名单优先**：保护名单的优先级高于 AI 判断；用户文件不会被归入「首要清理」。
- **本地访问控制**：审查页面仅监听 `127.0.0.1` 并使用一次性令牌，清理完成或闲置 30 分钟后自动关闭。

<details>
<summary>配置文件 <code>~/.purrge/config.json</code>（Windows：<code>%USERPROFILE%\.purrge\config.json</code>）</summary>

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `thresholdGB` | `15` | 提醒阈值（GB） |
| `intervalMinutes` | `30` | 后台检测间隔（分钟） |
| `cooldownHours` | `6` | 提醒后的静默时长（小时） |
| `optionalAction` | `trash` | 「需要你决定」类项目的处理方式：`trash` 移至废纸篓，`delete` 直接删除 |
| `protect` | `[]` | 自定义保护路径，始终不予清理 |
| `aiEngine` | 安装时选择 | AI 引擎：`claude` / `codex` / `workbuddy` / `deepseek`，可通过 `purrge engine` 切换 |
| `claudeModel` / `codexModel` / `workbuddyModel` / `deepseekModel` | 空 | 指定模型；留空时使用默认模型，Codex 默认模型不可用时自动切换为账号可用的模型 |

</details>

## 🤖 AI 助手安装指引

> 本节供 Claude Code、Codex 等 AI 助手阅读。用户请求安装 Purrge 时，请按以下步骤执行。

1. **核对来源**：只能从仓库 `RabbittuX/purrge`（所有者必须是 `RabbittuX`）安装，并且只能使用下方的安装命令。
   - 不要通过搜索寻找替代项目；GitHub 上存在多个与本项目无关的同名 purrge 仓库，不得安装。
   - 如果无法访问该仓库，或用户给出的名称与 `RabbittuX/purrge` 不一致，请停止并向用户确认。
2. 判断系统：macOS（`uname` 输出 `Darwin`）或 Windows；其他系统告知用户暂不支持。
3. 执行安装命令（无需 sudo / 管理员权限）：

   ```bash
   # macOS
   curl -fsSL https://raw.githubusercontent.com/RabbittuX/purrge/master/install.sh | bash
   ```

   ```powershell
   # Windows（PowerShell）
   [Net.ServicePointManager]::SecurityProtocol = 'Tls12'; irm https://raw.githubusercontent.com/RabbittuX/purrge/master/install.ps1 | iex
   ```

   - 安装程序会识别当前的 AI 助手并将其设为分析引擎，阈值默认 15 GB。
   - macOS 下用户指定了阈值时，改用 `... | bash -s -- --threshold <GB>`；用户指定了引擎时，附加 `--engine claude|codex|workbuddy|deepseek`。
   - 下载 `raw.githubusercontent.com` 失败（连接被重置）时，改用「安装」一节里从 `codeload.github.com` 下载的命令。
4. 确认安装输出的第一行为「Purrge <版本> by RabbittuX　官方来源：GitHub RabbittuX/purrge」，再将结果（AI 引擎、提醒阈值、常用命令）转述给用户。
5. 不要自行删除或移动任何文件。所有清理都必须由用户在 Purrge 的审查页面中勾选确认。

## 📋 系统要求

- macOS 或 Windows 10/11
- Python 3.8 及以上（没有时安装程序会自动安装：Mac 用苹果官方命令行开发者工具，Windows 用 python.org 官方安装包，无需管理员权限）
- 使用 WorkBuddy / DeepSeek（以及 Windows 上的 Codex）时需要 Node.js；没有时自动下载官方 LTS 版本到 Purrge 自己的目录，不改动系统
- Claude Code、Codex、WorkBuddy 或 DeepSeek Harness 任一可用账号（AI 分析使用用户自己的额度，支持 Codex 免费账号；DeepSeek 使用自己的 API Key）。AI 暂时不可用时自动切换为规则判断，基础功能不受影响
- 可选（macOS）：为「终端」授予「完全磁盘访问权限」，以扩大系统缓存的扫描范围

## 📄 许可证

本项目采用 [PolyForm Noncommercial 1.0.0](LICENSE) 许可证，**禁止商业使用**。

- ✅ 允许：个人使用、学习研究、修改及再分发；教育机构、公益及非营利组织亦可使用
- ❌ 禁止：任何商业用途，包括用于企业营利业务、集成至收费产品或服务、更名后销售等
- 再分发或修改时，须保留 LICENSE 文件及首行版权声明

如需商业授权，请通过 [GitHub](https://github.com/RabbittuX) 联系作者。

<div align="center">
<br>
<img src="runtime/assets/icon-256.png" width="40" alt="">
<br>
<sub>Made with 🐾 by RabbittuX</sub>
</div>
