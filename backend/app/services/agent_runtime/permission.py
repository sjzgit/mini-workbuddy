"""路径解析与统一权限判定（specs/014-workspace-permission，research R3/R6）。

判定引擎（纯逻辑，不依赖 DB / HTTP）：

    resolve_path   规范化：expanduser → 相对按 base 拼接 → resolve()（穿透 Symlink）
    is_within      目录树包含（== 或 root 在 parents 链），禁止字符串前缀比较
    PermissionManager.check   三值决策：保护集 DENY → 系统 ALLOW → 会话 ALLOW
                              → 临时授权 ALLOW → 其余 ASK_USER（data-model §3 状态机）

Windows 大小写/分隔符等价由 pathlib 的平台语义保证（PureWindowsPath 比较不区分
大小写；resolve() 已归一分隔符），POSIX 保持大小写敏感。
运行时权限唯一入口：agent_runtime.tools.run_tool 的权限检查阶段（Invariant 2/9）。
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

# ---- 决策常量（契约 workspace-permission-api.md §2.1；禁止布尔化，Invariant 4）----

DECISION_ALLOW = "allow"
DECISION_ASK_USER = "ask_user"
DECISION_DENY = "deny"

GRANT_SCOPE_CURRENT_RUN = "current_run"


def resolve_path(raw: str, base: Path | None = None) -> Path:
    """把工具参数中的路径字符串规范化为真实绝对路径（research R3）。

    expanduser → 相对路径按 base 拼接（file: 系统授权目录；shell: 执行基准 cwd）
    → resolve()：展开 `..`/`.`、重复分隔符并穿透符号链接（非严格，不存在路径可解析）。
    解析失败（非法形式等）由调用方捕获 OSError → DENY(path_resolution_failed)。
    """
    expanded = os.path.expanduser(raw.strip())
    candidate = Path(expanded)
    if not candidate.is_absolute() and base is not None:
        candidate = base / candidate
    return candidate.resolve()


def is_within(resolved: Path, root: Path) -> bool:
    """目录树包含判断：resolved == root，或 root 出现在其 parents 链（spec 十四）。

    Path 相等比较按平台语义（Windows 不区分大小写与分隔符写法）；
    `D:\\project2` 与 `D:\\project` 互不包含（前缀相似不构成授权）。
    """
    return resolved == root or root in resolved.parents


# ---- 运行期结构（data-model.md §2；随 RunContext 生灭，不落盘，Invariant 5）----


@dataclass
class TemporaryGrant:
    """一次用户允许产生的临时授权（仅当前 AgentRun 内有效）。"""

    path: str  # 规范化后的授权路径（str(resolved)）
    scope: str = GRANT_SCOPE_CURRENT_RUN
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )


@dataclass
class PermissionDecision:
    """一次权限判定的结果（FR-011：三值 + 原因；deny 附错误码）。"""

    decision: str  # allow | ask_user | deny
    path: str  # 展示用规范化路径
    reason: str  # 人话原因（不含文件内容，FR-033）
    error_code: str | None = None  # deny 时的 ToolErrorCode（契约 §3）


def _grant_covers(resolved: Path, grant: TemporaryGrant) -> bool:
    """授权命中：请求路径 == 授权路径，或授权路径是其目录祖先（授权目录覆盖子树）。"""
    granted = Path(grant.path)
    return resolved == granted or granted in resolved.parents


@dataclass
class RunPermissionContext:
    """一次运行的权限上下文（最小 ExecutionContext；运行期不可变，除 grants 追加）。

    system_root/session_root 在运行启动时快照（Invariant 6）；grants 仅运行内追加。
    """

    system_root: Path  # 规范化后的系统授权目录
    session_root: Path | None  # 规范化后的会话工作空间快照；None = 未选择
    protected: list[Path] = field(default_factory=list)  # 保护集（默认 + 配置追加）
    grants: list[TemporaryGrant] = field(default_factory=list)


def default_protected() -> list[Path]:
    """系统保护路径集：平台默认 + settings.protected_paths 追加（data-model §7）。"""
    items = [
        r"C:\Windows",
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"C:\ProgramData",
    ]
    home = Path.home()
    items += [str(home / ".ssh"), str(home / ".aws"), str(home / ".gnupg")]
    extra = settings.protected_paths or ""
    for piece in extra.split(os.pathsep):
        piece = piece.strip()
        if piece:
            items.append(piece)
    resolved: list[Path] = []
    for item in items:
        try:
            resolved.append(Path(os.path.expanduser(item)).resolve())
        except OSError:  # noqa: PERF203 — 单项非法不影响其余保护项
            continue
    return resolved


def build_context(system_root: str | Path, session_root: str | Path | None) -> RunPermissionContext:
    """构造运行权限上下文：规范化根目录并冻结保护集（research R8 快照语义）。

    系统授权目录不存在时自动创建（003 既有口径：首次使用自动创建）。
    """
    system = Path(system_root).resolve()
    system.mkdir(parents=True, exist_ok=True)
    session = Path(session_root).resolve() if session_root else None
    return RunPermissionContext(
        system_root=system,
        session_root=session,
        protected=default_protected(),
    )


class PermissionManager:
    """统一权限判定（Invariant 2：判断只来自这里；Invariant 8：保护集不可确认绕过）。"""

    @staticmethod
    def check(resolved: Path, ctx: RunPermissionContext) -> PermissionDecision:
        """三值判定（data-model §3 状态机，顺序即优先级）。"""
        display = str(resolved)
        # ① 保护集最高优先级：命中即 DENY（即使在工作空间内、用户也不可放行）
        for root in ctx.protected:
            if is_within(resolved, root):
                return PermissionDecision(
                    decision=DECISION_DENY, path=display,
                    reason=f"路径位于系统保护目录，禁止访问：{display}",
                    error_code="system_protected_path",
                )
        # ② 系统工作空间
        if is_within(resolved, ctx.system_root):
            return PermissionDecision(
                decision=DECISION_ALLOW, path=display,
                reason="路径在系统工作空间内",
            )
        # ③ 会话工作空间（快照）
        if ctx.session_root is not None and is_within(resolved, ctx.session_root):
            return PermissionDecision(
                decision=DECISION_ALLOW, path=display,
                reason="路径在会话工作空间内",
            )
        # ④ 临时授权（仅当前运行）
        for grant in ctx.grants:
            if _grant_covers(resolved, grant):
                return PermissionDecision(
                    decision=DECISION_ALLOW, path=display,
                    reason="路径已获本次运行临时授权",
                )
        # ⑤ 其余 → 询问用户
        return PermissionDecision(
            decision=DECISION_ASK_USER, path=display,
            reason="路径在工作空间之外",
        )
