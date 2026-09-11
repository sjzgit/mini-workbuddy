"""内嵌 FastMCP 假 Server（供 stdio 集成测试，tasks T031）。

用法：python fake_mcp_server.py --tools 2   正常提供 2 个工具
      python fake_mcp_server.py --tools 0   正常但无工具
      python fake_mcp_server.py --hang      启动后挂起不响应 MCP 协议（超时场景）
      python fake_mcp_server.py --garbage   stdout 输出非 MCP 内容（协议不兼容场景）
"""

import argparse
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", type=int, default=2)
    parser.add_argument("--hang", action="store_true")
    parser.add_argument("--garbage", action="store_true")
    args = parser.parse_args()

    if args.garbage:
        print("hello, not-mcp-content", flush=True)
        time.sleep(10)
        return
    if args.hang:
        time.sleep(60)
        return

    from mcp.server.mcpserver import MCPServer

    server: MCPServer = MCPServer("fake-server")

    if args.tools >= 1:

        @server.tool(description="查询城市天气预报")
        def get_weather(city: str, days: int = 1) -> str:
            return f"{city} {days}d: sunny"

    if args.tools >= 2:

        @server.tool(description="原样返回消息")
        def echo(message: str) -> str:
            return message

    server.run()


if __name__ == "__main__":
    main()
