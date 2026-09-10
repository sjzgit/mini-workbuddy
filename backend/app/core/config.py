"""集中配置管理。

所有可配置项以此处为唯一入口，环境变量可覆盖默认值。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置（默认值面向本地开发环境）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "mini-workbuddy"
    database_url: str = "sqlite:///./app.db"
    # 主密钥文件路径（密钥库；secret.key 不入库，见 .gitignore）
    secret_vault_path: str = "./secret.key"
    # ---- 工具管理（specs/003-tool-management/contracts/tool-definitions.md §6）----
    default_timezone: str = "Asia/Shanghai"  # 时间工具未指定时区时使用
    authorized_dir: str = "./workspace"  # 文件读写工具授权目录（相对 backend 运行目录）
    shell_timeout_seconds: int = 60  # Shell 命令执行超时
    shell_output_max_chars: int = 20000  # Shell 输出截断上限
    file_max_bytes: int = 1048576  # 文件读写单文件上限（1MB）


settings = Settings()
