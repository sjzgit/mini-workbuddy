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
    # 开发服务器监听地址与端口（uv run python start_dev.py 读取，可用环境变量覆盖）
    dev_server_host: str = "127.0.0.1"
    dev_server_port: int = 8218
    # 主密钥文件路径（密钥库；secret.key 不入库，见 .gitignore）
    secret_vault_path: str = "./secret.key"
    # ---- 工具管理（specs/003-tool-management/contracts/tool-definitions.md §6）----
    default_timezone: str = "Asia/Shanghai"  # 时间工具未指定时区时使用
    authorized_dir: str = "./workspace"  # 文件读写工具授权目录（相对 backend 运行目录）
    shell_timeout_seconds: int = 60  # Shell 命令执行超时
    shell_output_max_chars: int = 20000  # Shell 输出截断上限
    file_max_bytes: int = 1048576  # 文件读写单文件上限（1MB）
    # ---- Skills 与 MCP 管理（specs/004-skills-mcp-management/contracts/*.md §7/§8）----
    skills_dir: str = "./workspace/skills"  # Skill 目录根（相对 backend 运行目录）
    skill_import_max_bytes: int = 10485760  # ZIP 导入解压总大小上限（10MB）
    mcp_test_timeout_seconds: int = 30  # MCP 测试连接总超时（启动+初始化+读工具）
    # ---- 聊天（specs/008-chat-conversations/contracts/chat-api.md"生成任务内部约定"节）----
    chat_stream_connect_timeout_seconds: int = 10  # 上游模型连接超时
    chat_stream_read_timeout_seconds: int = 120  # 上游读间隔超时（首字可能较慢）
    # ---- Agent Runtime（specs/009-agent-runtime/data-model.md §4）----
    runtime_skill_max_bytes: int = 65536  # load_skill 指令大小上限（超限报错不截断）
    runtime_mcp_connect_timeout_seconds: int = 30  # 运行内 MCP 连接+列工具超时
    runtime_tool_result_summary_chars: int = 200  # 工具结果/参数脱敏摘要截断长度
    # ---- 工具过程展示（specs/010-tool-execution-display/contracts/display-events.md §1.3）----
    runtime_tool_params_max_chars: int = 4000  # 工具事件 params 字段字符上限（超出截断+标记）
    runtime_tool_result_max_chars: int = 16000  # 工具事件 result 字段字符上限（超出截断+标记）


settings = Settings()
