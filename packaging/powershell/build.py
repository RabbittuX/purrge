"""把 Purrge 打包成 PowerShell 模块（发布到 PowerShell Gallery 用）。
用法：python packaging/powershell/build.py [输出目录，默认 dist/Purrge]
模块里带着完整的 runtime 和 install.ps1，用户 Install-Module 之后运行 Install-Purrge 即可安装，不用再从 GitHub 下载。"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "Purrge"

version = re.search(r'VERSION = "([^"]+)"', (ROOT / "runtime/lib/common.py").read_text(encoding="utf-8")).group(1)
m = re.fullmatch(r"(\d+\.\d+\.\d+)(?:-([0-9A-Za-z]+))?", version)
if not m:
    sys.exit(f"版本号格式不对：{version}")
module_version, prerelease = m.group(1), m.group(2)

shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True)
shutil.copy2(HERE / "Purrge.psm1", out / "Purrge.psm1")
shutil.copy2(ROOT / "install.ps1", out / "install.ps1")
shutil.copy2(ROOT / "LICENSE", out / "LICENSE")
shutil.copytree(ROOT / "runtime", out / "runtime", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

pre = f"\n            Prerelease   = '{prerelease}'" if prerelease else ""
manifest = f"""@{{
    RootModule           = 'Purrge.psm1'
    ModuleVersion        = '{module_version}'
    GUID                 = '6f1d6b2e-3c7a-4b8e-9a51-2f0c8e7d4a19'
    Author               = 'RabbittuX'
    CompanyName          = 'RabbittuX'
    Copyright            = 'Copyright (c) RabbittuX. PolyForm Noncommercial 1.0.0.'
    Description          = 'Purrge by RabbittuX: AI-powered disk space manager for Windows and macOS. Warns when disk space is low, lets an AI (Claude Code, Codex, WorkBuddy, DeepSeek Harness or Pi) explain what can be cleaned, and deletes only what you approve. Run Install-Purrge after installing this module.'
    PowerShellVersion    = '5.1'
    CompatiblePSEditions = @('Desktop', 'Core')
    FunctionsToExport    = @('Install-Purrge')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{{
        PSData = @{{
            Tags         = @('disk', 'cleanup', 'storage', 'ai', 'windows', 'claude', 'codex', 'workbuddy', 'deepseek', 'pi', 'purrge')
            LicenseUri   = 'https://github.com/RabbittuX/purrge/blob/master/LICENSE'
            ProjectUri   = 'https://github.com/RabbittuX/purrge'
            IconUri      = 'https://raw.githubusercontent.com/RabbittuX/purrge/master/runtime/assets/icon-256.png'
            ReleaseNotes = 'https://github.com/RabbittuX/purrge/releases'{pre}
        }}
    }}
}}
"""
(out / "Purrge.psd1").write_text(manifest, encoding="ascii")
for f in ("Purrge.psd1", "Purrge.psm1"):
    (out / f).read_bytes().decode("ascii")   # 模块文件必须纯 ASCII（Windows PowerShell 5.1 按系统代码页读）
print(out)
