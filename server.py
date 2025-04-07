import mcp.types as types

from mcp import Tool
from mcp.server.sse import SseServerTransport
from mcp.server import Server
from mcp.server import Server

from starlette.applications import Starlette
from starlette.routing import Route

import uvicorn
import httpx

from readability import Document
import html2text

import os 

os.environ['HTTP_PROXY'] = 'http://192.168.16.248:7890'
os.environ['HTTPS_PROXY'] = 'http://192.168.16.248:7890'

app = Server("mcp-server")
sse = SseServerTransport("/messages")

port = 8000

async def handle_sse(request):
    print("Handling sse")
    async with sse.connect_sse(
            request.scope, request.receive, request._send
    ) as streams:
        await app.run(
            streams[0], streams[1], app.create_initialization_options()
        )

async def handle_messages(request):
    print(f"Handling messages with {request.scope}, {request.receive}, {request._send}")
    # 1. 处理消息
    await sse.handle_post_message(request.scope, request.receive, request._send)

async def fetch_website(
        url: str,
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()

        # 2. 提取正文
        doc = Document(response.text)
        clean_html = doc.summary()  # 获取清理后的正文HTML

        # 3. 转换为Markdown
        h = html2text.HTML2Text()
        h.single_line_break = True   # 单换行转为<br>
        h.wrap_links = False        # 不换行长链接
        h.mark_code = True          # 高亮代码块
        h.ignore_links = False      # 保留链接
        h.ignore_images = False     # 保留图片

        markdown = h.handle(clean_html)
        # 移除多余空行
        markdown = "\n".join([line for line in markdown.split("\n") if line.strip()])

        return [types.TextContent(type="text", text=markdown)]

@app.call_tool()
async def call_tool(
  name: str, arguments: dict
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name == "fetch":
        if "url" not in arguments:
            raise ValueError("Missing required argument 'url'")
        return await fetch_website(arguments["url"])
    else:
        raise ValueError(f"Unknown tool '{name}'")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    print("Listing tools")
    return [
        types.Tool(
            name="fetch",
            description="Fetches a website and returns its content",
            inputSchema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    }
                },
            },
        )
    ]

starlette_app = Starlette(
    debug=True,
    routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Route("/messages", endpoint=handle_messages, methods=["POST"]),
    ],
)

# 使用uvicorn运行服务器
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)
