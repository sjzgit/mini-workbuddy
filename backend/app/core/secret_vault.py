"""本地密钥库：API Key 的唯一存取入口。

方案（specs/002-model-management/research.md R1）：
- 主密钥：首次访问自动生成 Fernet key，写入 secret.key（0600，不入库）
- 密文：Fernet 加密后存 secrets_vault 表，与业务表 models 分离
- 对外：业务代码只拿到 has_secret / 明文（仅在调用模型时）两种结果

约束（spec FR-009~012）：任何明文/密文不得出现在接口响应与日志。
"""

import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import SecretVaultEntry

_lock = threading.Lock()
_fernet: Fernet | None = None


def _load_or_create_fernet() -> Fernet:
    """加载主密钥文件；不存在则生成并落盘（进程内缓存）。"""
    global _fernet
    if _fernet is not None:
        return _fernet
    with _lock:
        if _fernet is not None:
            return _fernet
        path = Path(settings.secret_vault_path)
        if path.exists():
            key = path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(key)
            try:  # Windows 上 chmod 语义有限，尽力收紧权限
                path.chmod(0o600)
            except OSError:
                pass
        _fernet = Fernet(key)
        return _fernet


def reset_fernet_cache() -> None:
    """测试夹具用：清理进程内缓存，强制下次重新加载。"""
    global _fernet
    with _lock:
        _fernet = None


def has_secret(session: Session, secret_ref: int | None) -> bool:
    """密钥是否已配置（对外唯一暴露的信息）。"""
    if secret_ref is None:
        return False
    return session.get(SecretVaultEntry, secret_ref) is not None


def store_secret(session: Session, secret_ref: int | None, plaintext: str) -> int | None:
    """写入或替换密钥，返回 secret_ref。

    plaintext 为空时原样返回当前引用（保留原密钥，FR-012）。
    """
    if not plaintext:
        return secret_ref
    fernet = _load_or_create_fernet()
    ciphertext = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
    if secret_ref is not None:
        entry = session.get(SecretVaultEntry, secret_ref)
        if entry is not None:
            entry.ciphertext = ciphertext
            session.add(entry)
            return secret_ref
    entry = SecretVaultEntry(ciphertext=ciphertext)
    session.add(entry)
    session.flush()  # 取得自增 id
    return entry.id


def load_secret(session: Session, secret_ref: int | None) -> str | None:
    """解密读取密钥明文（仅供后端调用模型使用，禁止进入响应/日志）。"""
    if secret_ref is None:
        return None
    entry = session.get(SecretVaultEntry, secret_ref)
    if entry is None:
        return None
    try:
        return _load_or_create_fernet().decrypt(entry.ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        # 主密钥更换过：视为密钥不可用（不抛堆栈，调用方按未配置处理）
        return None


def delete_secret(session: Session, secret_ref: int | None) -> None:
    """删除密钥记录（删除模型时同事务调用，FR-021）。"""
    if secret_ref is None:
        return
    session.execute(delete(SecretVaultEntry).where(SecretVaultEntry.id == secret_ref))
