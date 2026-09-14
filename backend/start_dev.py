"""开发服务器一键启动脚本。

用法（backend/ 目录执行）：
    uv run python start_dev.py          # 前台启动（Ctrl+C 正常退出）
    uv run python start_dev.py --reset  # 启动前先清理端口上的残留进程（孤儿自愈）

地址与端口从 app.core.config.settings 读取（dev_server_host / dev_server_port），
可用环境变量 DEV_SERVER_HOST / DEV_SERVER_PORT 覆盖。
"""

from __future__ import annotations

import subprocess
import sys

from app.core.config import settings


def find_port_pids(port: int) -> list[int]:
    """返回监听指定端口的进程 PID 列表。"""
    result = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        # 形如：TCP  127.0.0.1:8218  0.0.0.0:0  LISTENING  1234
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
            local = parts[1].rsplit(":", 1)
            if len(local) == 2 and local[1] == str(port):
                try:
                    pids.append(int(parts[4]))
                except ValueError:
                    pass
    return pids


def reset_port(port: int) -> None:
    """强制结束监听端口的进程树（含 uvicorn reloader 及其 worker）。"""
    pids = find_port_pids(port)
    if not pids:
        print(f"[start_dev] 端口 {port} 无残留进程")
        return
    for pid in pids:
        print(f"[start_dev] 清理残留进程: PID {pid}")
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )


def main() -> None:
    reset = "--reset" in sys.argv
    host, port = settings.dev_server_host, settings.dev_server_port
    if find_port_pids(port):
        if reset:
            reset_port(port)
        else:
            print(
                f"[start_dev] 端口 {port} 已被占用。"
                f"若是残留孤儿进程，请执行: uv run python start_dev.py --reset"
            )
            sys.exit(1)
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--host",
        host,
        "--port",
        str(port),
    ]
    print(f"[start_dev] 启动: {' '.join(cmd)}")
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
