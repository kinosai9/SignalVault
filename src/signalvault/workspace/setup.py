"""P2-L.1: Vault setup, validation, initialization, and repair.

No LLM, no external APIs, no destructive operations.
Never deletes user files. Non-empty directories are safe — we only add missing items.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Standard Obsidian vault directories for this project
REQUIRED_DIRS: list[str] = [
    "00_Inbox",
    "00_Inbox/LLM_Patches",
    "01_Reports",
    "02_Topics",
    "03_Companies",
    "04_People",
    "05_Channels",
    "06_Claims",
    "07_Signals",
    "90_Templates",
    "99_System",
    "attachments",
]

# Files that should exist in a healthy vault
REQUIRED_FILES: list[str] = [
    "Home.md",
    "99_System/Watchlist.yaml",
    "99_System/Research Brief.md",
    "99_System/Watchlist Brief.md",
    "99_System/Knowledge Map.md",
    "99_System/Review Queue.md",
    "99_System/Report Index.md",
    "99_System/Topic Taxonomy.md",
    "99_System/Getting Started.md",
]


@dataclass
class VaultValidationResult:
    exists: bool
    is_directory: bool
    missing_dirs: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    is_initialized: bool = False


@dataclass
class VaultSetupResult:
    vault_path: Path
    created_dirs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_vault(path: Path) -> VaultValidationResult:
    """Check whether a directory has a complete vault structure."""
    result = VaultValidationResult(
        exists=path.exists(),
        is_directory=path.is_dir() if path.exists() else False,
    )

    if not result.exists or not result.is_directory:
        return result

    # Check directories
    for d in REQUIRED_DIRS:
        full = path / d
        if not full.is_dir():
            result.missing_dirs.append(d)

    # Check files
    for f in REQUIRED_FILES:
        full = path / f
        if not full.is_file():
            result.missing_files.append(f)

    result.is_initialized = (
        len(result.missing_dirs) == 0 and len(result.missing_files) == 0
    )
    return result


def initialize_vault(path: Path) -> VaultSetupResult:
    """Create a complete vault directory structure and base files.

    Safe for non-empty directories: only creates missing items, never deletes.
    """
    result = VaultSetupResult(vault_path=path)

    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    elif not path.is_dir():
        result.warnings.append(f"路径存在但不是目录: {path}")
        return result
    elif any(path.iterdir()):
        result.warnings.append("目录非空，将只补齐缺失文件，不删除已有内容。")

    # Create missing directories
    for d in REQUIRED_DIRS:
        full = path / d
        if not full.exists():
            full.mkdir(parents=True, exist_ok=True)
            result.created_dirs.append(d)
        elif full.exists():
            result.skipped_existing.append(d)

    # Create missing files (never overwrite)
    for f in REQUIRED_FILES:
        full = path / f
        if not full.exists():
            _create_file(full, f)
            result.created_files.append(f)
        else:
            result.skipped_existing.append(f)

    # Ensure Watchlist.yaml has content if newly created
    wl_path = path / "99_System" / "Watchlist.yaml"
    if "99_System/Watchlist.yaml" in result.created_files:
        _write_watchlist_template(wl_path)

    return result


def repair_vault(path: Path) -> VaultSetupResult:
    """Repair a vault: same as initialize but always shows repair context."""
    return initialize_vault(path)


def _create_file(full_path: Path, rel_path: str) -> None:
    """Create an empty or templated file. Never overwrites."""
    if full_path.exists():
        return

    # Ensure parent dir exists
    full_path.parent.mkdir(parents=True, exist_ok=True)

    content = _get_default_content(rel_path)
    full_path.write_text(content, encoding="utf-8")


def _get_default_content(rel_path: str) -> str:
    """Return default content for a given system file."""
    if rel_path == "Home.md":
        return _HOME_MD_CONTENT
    if rel_path == "99_System/Watchlist.yaml":
        return _WATCHLIST_YAML_CONTENT
    if rel_path == "99_System/Getting Started.md":
        return _GETTING_STARTED_CONTENT
    # Other files: empty placeholder with heading
    name = rel_path.split("/")[-1].replace(".md", "").replace(".yaml", "")
    if rel_path.endswith(".md"):
        return f"# {name}\n\n"
    return f"# {name}\n"


_HOME_MD_CONTENT = """# Home

欢迎使用 AI 投资研究知识库。

## 快速导航

- [[Research Brief]] — 最新研究摘要
- [[Watchlist Brief]] — 我的关注简报
- [[Knowledge Map]] — 知识图谱
- [[Review Queue]] — 待审阅队列
- [[Report Index]] — 报告索引
- [[Topic Taxonomy]] — 主题分类
"""

_WATCHLIST_YAML_CONTENT = """# Watchlist — 我的关注
# 编辑此文件添加你关注的公司、主题和方向。
# 格式: 每行一个名称（用 - 开头）

companies:
  - OpenAI
  - NVIDIA

topics:
  - AI Agents
  - Enterprise AI

themes:
  - Agent 工具链
  - 企业级 AI 应用
"""

_GETTING_STARTED_CONTENT = """# Getting Started

欢迎使用 AI 投资研究知识库。

## 第一步：设置我的关注
在 Web Console 中打开「我的关注」，添加你关注的公司、主题或方向。

## 第二步：添加新内容
在 Web Console 中粘贴 YouTube 视频链接，选择「整理进知识库」。

## 第三步：阅读研究摘要
整理完成后查看 Research Brief 和 Watchlist Brief。

## 如何打开本知识库
在 Obsidian 中点击「打开其他 Vault」→ 选择本文件夹。
"""


def _write_watchlist_template(path: Path) -> None:
    """Write Watchlist.yaml template if the file doesn't exist."""
    if not path.exists():
        path.write_text(_WATCHLIST_YAML_CONTENT, encoding="utf-8")
