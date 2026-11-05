---
name: purrge
description: Purrge by RabbittuX，macOS 磁盘清理工具。用户说"磁盘空间不够/快满了""帮我清理磁盘/缓存""硬盘还剩多少""阈值改成 xxG""关掉磁盘提醒"时使用：查看状态、扫描并打开审查页面、修改设置。清理只能由用户在审查页面勾选确认，AI 不直接删除任何文件。
---
# Purrge by RabbittuX

命令：`~/.purrge/app/bin/purrge <子命令>`（装好后通常也可以直接用 `purrge`）

| 用户想做的 | 子命令 |
|---|---|
| 清理磁盘 / 空间不够了 | `scan`（后台扫描，完成后自动在浏览器打开审查页面，约 1～2 分钟） |
| 还剩多少空间 / 提醒开着没 | `status` |
| 改阈值、检查频率、删除方式 | `config thresholdGB 20`、`config intervalMinutes 60`、`config optionalAction trash` 或 `delete` |
| 也扫一下别的目录 / 其他分区（如 D 盘项目文件夹） | `config scanDirs add <路径>`（`remove <路径>` 移除，`clear` 清空；系统盘根目录、系统目录、用户主目录不能添加） |
| 换用 Claude Code / Codex 判断 | `engine claude` / `codex` / `workbuddy` / `deepseek`（需要在终端里交互，请让用户自己运行） |
| 更新 Purrge | `update`（自动备份，失败自动回滚，设置保留） |
| 关掉提醒 / 卸载 | `uninstall`（`--purge` 连设置和记录一起删） |

## 规则
- **绝不自己用 rm 等命令删除或移动文件。** 所有清理都必须经过审查页面，由用户勾选并点「确认清理」。
- 用户问"这个能不能删"时，可以读 `~/.purrge/runs/<最新目录>/review.json` 里对应项的 `tier` 和 `reason` 来解释。
- 如果 `~/.purrge/config.json` 不存在，说明还没安装，请让用户在终端运行：
  `curl -fsSL https://raw.githubusercontent.com/RabbittuX/purrge/master/install.sh | bash`
- 支持 macOS 和 Windows（Windows 为测试版；安装命令：PowerShell 执行 `irm https://raw.githubusercontent.com/RabbittuX/purrge/master/install.ps1 | iex`）。
