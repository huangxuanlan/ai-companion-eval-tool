"""
DB 重命名 migration: longform.db → ops_v6.db（v6.0 ADR-001）

策略：
- 不复制 423MB 物理文件，使用 Windows hardlink 让两个文件名指向同一 inode
- 兼容期 1 周后，可以删除 longform.db 名字（原始 inode 仍由 ops_v6.db 持有）

用法：
    python scripts/migrate_db_rename.py [--dry-run] [--rollback]

幂等：可重复执行；如 ops_v6.db 已存在且与 longform.db 互为 hardlink，则跳过。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = PROJECT_ROOT / "server"
LONGFORM_DB = SERVER_DIR / "longform.db"
OPS_V6_DB = SERVER_DIR / "ops_v6.db"


def _is_hardlink_pair(p1: Path, p2: Path) -> bool:
    """检查两个路径是否指向同一 inode（Windows: file index）"""
    if not (p1.exists() and p2.exists()):
        return False
    try:
        # Windows: stat().st_ino 是 file index
        return p1.stat().st_ino == p2.stat().st_ino
    except OSError:
        return False


def _create_hardlink(target: Path, source: Path) -> bool:
    """在 target 处创建指向 source 的 hardlink。Windows 使用 mklink /H。"""
    import subprocess

    if target.exists():
        if _is_hardlink_pair(target, source):
            print(f"  [SKIP] {target.name} 已是 {source.name} 的 hardlink")
            return True
        print(f"  [ERROR] {target.name} 已存在但不是 hardlink，请人工处理")
        return False

    # PowerShell 创建 hardlink（不需管理员权限）
    cmd = [
        "powershell",
        "-Command",
        f'New-Item -ItemType HardLink -Path "{target}" -Target "{source}" | Out-Null',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] 创建 hardlink 失败: {result.stderr}")
        return False
    print(f"  [OK] 创建 hardlink: {target.name} → {source.name}")
    return True


def _rollback() -> int:
    """回滚：删除 ops_v6.db hardlink 名字（不动原始 inode）"""
    if not OPS_V6_DB.exists():
        print("  [SKIP] ops_v6.db 不存在，无需回滚")
        return 0
    if not _is_hardlink_pair(OPS_V6_DB, LONGFORM_DB):
        print(f"  [ERROR] ops_v6.db 不是 longform.db 的 hardlink，拒绝删除（避免数据丢失）")
        return 1
    OPS_V6_DB.unlink()
    print(f"  [OK] 删除 hardlink: {OPS_V6_DB.name}（原始 inode 仍由 longform.db 持有）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DB 重命名 migration: longform.db → ops_v6.db")
    parser.add_argument("--dry-run", action="store_true", help="只检查不执行")
    parser.add_argument("--rollback", action="store_true", help="删除 ops_v6.db hardlink 回到 v5.9 状态")
    args = parser.parse_args()

    print(f"[migrate_db_rename] SERVER_DIR = {SERVER_DIR}")

    # 检查源文件
    if not LONGFORM_DB.exists():
        print(f"  [ERROR] 源文件 {LONGFORM_DB} 不存在")
        return 1
    print(f"  [INFO] {LONGFORM_DB.name}: {LONGFORM_DB.stat().st_size / 1024 / 1024:.1f} MB")

    if args.rollback:
        return _rollback()

    # 状态判断
    if OPS_V6_DB.exists():
        if _is_hardlink_pair(OPS_V6_DB, LONGFORM_DB):
            print(f"  [OK] 已迁移：ops_v6.db ↔ longform.db hardlink 已就绪")
            return 0
        print(f"  [ERROR] {OPS_V6_DB.name} 已存在但不是 hardlink，请人工处理")
        return 1

    if args.dry_run:
        print(f"  [DRY-RUN] 将创建 hardlink: {OPS_V6_DB.name} → {LONGFORM_DB.name}")
        return 0

    # 实际创建
    success = _create_hardlink(OPS_V6_DB, LONGFORM_DB)
    if not success:
        return 1

    # 验证
    if _is_hardlink_pair(OPS_V6_DB, LONGFORM_DB):
        print(f"  [VERIFIED] 两个路径指向同一 inode（{OPS_V6_DB.stat().st_ino}）")
        return 0
    print(f"  [ERROR] hardlink 创建后验证失败")
    return 1


if __name__ == "__main__":
    sys.exit(main())
