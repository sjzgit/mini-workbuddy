"""危险命令拦截规则表（FR-016，research R3）。

纯函数模块：check(command) → DangerCategory | None。
类别枚举与拒绝文案主定义：specs/003-tool-management/contracts/tool-definitions.md §5

匹配策略：规范化（小写、空白折叠、%VAR% 保守展开）后按类别检查；
"危险目标"用带边界的正则而非子串匹配（避免 ./deploy.sh 这类路径误伤），
组合类规则要求"动作 token 与目标 token 同时命中"才拦截。
规则表是数据：新增形态 = 加规则 + 配套单测（tasks.md Notes）。
"""

import re
from collections.abc import Callable

from app.schemas.tool import DangerCategory

# ---- 规范化 ----

_WHITESPACE = re.compile(r"\s+")

# Windows 环境变量形态（%SystemRoot% 等）在匹配前展开为保守字面值（仅目标判断用）
_WIN_ENV_VARS = {
    "systemroot": "c:\\windows",
    "windir": "c:\\windows",
    "programfiles": "c:\\program files",
}


def _expand_win_env(text: str) -> str:
    """%VAR% 与 PowerShell 常见 env 形态展开为保守字面值（仅目标判断用）。"""
    def _replace(match: re.Match[str]) -> str:
        return _WIN_ENV_VARS.get(match.group(1), match.group(0))

    expanded = re.sub(r"%([a-z_][a-z0-9_]*)%", _replace, text)
    # PowerShell：$env:USERPROFILE → 用户主目录（含 .ssh 等密钥源的场景）
    return expanded.replace("$env:userprofile", "c:\\users\\public")


def normalize(command: str) -> str:
    """供规则匹配的规范形式：小写、空白折叠、%VAR% 展开。"""
    compact = _WHITESPACE.sub(" ", command).strip()
    return _expand_win_env(compact.lower())


# ---- 危险目标（带边界，避免普通路径误伤）----

# 目标之后允许出现的字符（空白 / 路径分隔 / 命令分隔 / 引号 / 行尾 / 通配符）
_TAIL = r"(?:\s|/|\\|;|&|\"|'|\)|\*|$)"
# 目标之前允许出现的字符（行首 / 空白 / 引号 / 等号 / 括号）
_LEAD = r"(?:^|[\s\"'=(])"

# POSIX：裸根 /、/* 或系统目录（/etc /usr /bin …）
_ROOT_TARGET = re.compile(
    _LEAD + r"/" + _TAIL
    + r"|" + _LEAD + r"/(?:etc|usr|bin|sbin|lib|lib64|boot|var|opt|dev|sys|proc|root|home)" + _TAIL,
)
# Windows：盘符根 c:\ 与系统目录（c:\windows、c:\program files、c:\users …）
_WIN_TARGET = re.compile(
    r"[c-z]:\\" + _TAIL
    + r"|[c-z]:\\(?:windows|program files|programdata|users)" + _TAIL
    + r"|[c-z]:/" + _TAIL
    + r"|[c-z]:/(?:windows|program files|programdata|users)" + _TAIL,
)

# ---- 各类别规则 ----

# 1. 递归删除系统目录：递归删除动作 + 系统/根目标
_RM_RECURSIVE = re.compile(r"\brm\b[^|;&]*?\s(-[a-z]*r[a-z]*|--recursive)\b")
_WIN_RECURSIVE_DELETE = (
    re.compile(r"\brd\b[^|;&]*\s/s\b"),
    re.compile(r"\bdel\b[^|;&]*\s/[sf]"),
    re.compile(r"\brmdir\b[^|;&]*\s/s\b"),
    re.compile(r"\bremove-item\b[^|;&]*\s(-recurse|-r)\b"),
)

# 2. 格式化磁盘
_FORMAT_DISK = (
    re.compile(r"\bformat(\.com)?\s+[c-z]:"),
    re.compile(r"\bmkfs(\.\w+)?\b"),
    re.compile(r"\bdiskpart(\.exe)?\b"),
    re.compile(r"\bformat-volume\b"),
    re.compile(r"\bclear-disk\b"),
)

# 3. 修改关键系统权限：权限命令 + 系统/根目标
_PERMISSION_CMDS = re.compile(r"\b(chmod|chown|icacls|cacls|takeown|setacl)\b")

# 4. 关闭安全防护
_SECURITY_SERVICES = (
    "windefend", "wscsvc", "mpssvc", "securityhealthservice", "sysmon",
    "firewalld", "ufw", "clamd", "fail2ban", "crowdsec", "apparmor", "auditd",
    "kaspersky", "mcafee", "esets",
)
_SECURITY_DISABLE_PATTERNS = (
    re.compile(r"\bufw\s+disable\b"),
    re.compile(r"\bset-mppreference\b[^|;&]*-disable\w*\s+\$?(true|1)\b"),
    re.compile(r"\bnetsh\s+(advfirewall|firewall)\b[^|;&]*(off|disable)"),
    re.compile(r"\biptables\b[^|;&]*\s(-f|--flush)\b"),
    re.compile(r"\bfirewall-cmd\b[^|;&]*--(remove|disable)\b"),
)
_STOP_LIKE = re.compile(r"\b(net\s+stop|sc\s+(config|stop)|systemctl\s+(stop|disable|mask))\b")

# 5. 读取并外传密钥：密钥源 + 外传通道同时命中
_SECRET_SOURCES = (
    ".ssh", "id_rsa", "id_ed25519", "id_ecdsa", "authorized_keys",
    ".aws/credentials", ".env", "secret.key", ".gnupg",
    "credentials.json", "secrets.yml", "secrets.yaml", ".netrc", "wallet.dat",
)
_EXFIL_CHANNELS = (
    re.compile(r"(?<![\w-])(curl|wget|nc|ncat|netcat|socat|scp|sftp)(?![\w-])"),
    re.compile(r"\b(invoke-webrequest|invoke-restmethod)\b"),
    re.compile(r"(?<![\w-])(iwr|irm)(?![\w-])"),
)

# 6. 直接执行远程下载的脚本
_REMOTE_FETCH = re.compile(
    r"\b(curl|wget|invoke-restmethod|invoke-webrequest)(?![\w-])[^|;&]*(https?://|ftp://)"
    r"|(?<![\w-])(irm|iwr)(?![\w-])[^|;&]*(https?://|ftp://)",
)
_PIPE_TO_INTERPRETER = re.compile(
    r"[|>]\s*(sudo\s+)?(ba|z|k|da|fi)?sh\b|\|\s*(pwsh|powershell|python\d*|perl|ruby|node)\b",
)
_BASH_PROCESS_SUB = re.compile(r"\b(ba|z)?sh\s*<\(")
_IEX_REMOTE = re.compile(r"\biex\s*\(\s*((?<![\w-])(irm|iwr)(?![\w-])|invoke-restmethod|invoke-webrequest)")
_IEX_DOWNLOADSTRING = re.compile(r"\biex\b[^|;&]*downloadstring")


def _hits_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _is_system_target(cmd: str) -> bool:
    return bool(_ROOT_TARGET.search(cmd) or _WIN_TARGET.search(cmd))


def _recursive_delete_system(cmd: str) -> bool:
    if not _is_system_target(cmd):
        return False
    return bool(
        _RM_RECURSIVE.search(cmd)
        or _hits_any(cmd, _WIN_RECURSIVE_DELETE)
    )


def _format_disk(cmd: str) -> bool:
    return _hits_any(cmd, _FORMAT_DISK)


def _modify_system_permissions(cmd: str) -> bool:
    return bool(_PERMISSION_CMDS.search(cmd)) and _is_system_target(cmd)


def _disable_security(cmd: str) -> bool:
    if _hits_any(cmd, _SECURITY_DISABLE_PATTERNS):
        return True
    return bool(_STOP_LIKE.search(cmd)) and _contains_any(cmd, _SECURITY_SERVICES)


def _secret_exfiltration(cmd: str) -> bool:
    return _contains_any(cmd, _SECRET_SOURCES) and _hits_any(cmd, _EXFIL_CHANNELS)


def _remote_script_execution(cmd: str) -> bool:
    if _IEX_REMOTE.search(cmd) or _IEX_DOWNLOADSTRING.search(cmd):
        return True
    if _BASH_PROCESS_SUB.search(cmd):
        return True
    return bool(_REMOTE_FETCH.search(cmd)) and bool(_PIPE_TO_INTERPRETER.search(cmd))


_CHECKERS: dict[DangerCategory, Callable[[str], bool]] = {
    "recursive_delete_system": _recursive_delete_system,
    "format_disk": _format_disk,
    "modify_system_permissions": _modify_system_permissions,
    "disable_security": _disable_security,
    "secret_exfiltration": _secret_exfiltration,
    "remote_script_execution": _remote_script_execution,
}

# 类别 → 人话类别名（契约 §5 拒绝文案的组成部分）
CATEGORY_LABELS: dict[DangerCategory, str] = {
    "recursive_delete_system": "递归删除根目录或系统目录",
    "format_disk": "格式化磁盘",
    "modify_system_permissions": "修改关键系统权限",
    "disable_security": "关闭安全防护",
    "secret_exfiltration": "读取并外传密钥",
    "remote_script_execution": "直接执行远程下载的脚本",
}

# 类别 → 拒绝原因简述
_CATEGORY_REASONS: dict[DangerCategory, str] = {
    "recursive_delete_system": "此类操作会造成系统不可恢复的破坏",
    "format_disk": "格式化将清除目标磁盘的全部数据",
    "modify_system_permissions": "修改系统位置的权限会破坏安全边界",
    "disable_security": "关闭防护会使系统暴露在攻击风险中",
    "secret_exfiltration": "外传密钥等敏感凭据会造成凭据泄露",
    "remote_script_execution": "未经检查执行远程脚本可能引入任意恶意代码",
}


def check(command: str) -> DangerCategory | None:
    """返回命中的危险类别（按固定顺序，首个命中即返回）；None = 放行。"""
    normalized = normalize(command)
    for category, checker in _CHECKERS.items():
        if checker(normalized):
            return category
    return None


def block_message(category: DangerCategory) -> str:
    """拒绝原因文案（契约 §5 dangerous_command_blocked 模板）。"""
    label = CATEGORY_LABELS[category]
    reason = _CATEGORY_REASONS[category]
    return (
        f"已拒绝执行危险命令（{label}）：{reason}。"
        "如确需相关操作，请拆分为安全步骤后手动执行"
    )
