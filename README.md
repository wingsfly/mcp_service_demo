# MCP Service Demo

这个项目演示了如何使用模型上下文协议(Model Context Protocol, MCP)服务，支持SSE和stdio两种交互方式。

## 功能特点

- 支持SSE和stdio类型的MCP服务交互
- 同时兼容Ollama和OpenAI格式的大模型调用
- 提供可配置的服务列表，兼容Claude Desktop格式
- 工具调用路由，自动选择对应服务进行调用
- 统计各环节耗时

## 项目结构

- `server.py`: MCP服务器示例，提供网站内容获取功能
- `client.py`: MCP客户端，支持多种模型和服务调用
- `mcp_config.json`: MCP服务配置文件

## 使用方法

### 1. 启动服务器

```bash
python server.py
```

### 2. 配置服务

编辑`mcp_config.json`文件，添加所需的MCP服务：

```json
{
  "mcpServers": {
    "example_sse_service": {
      "type": "sse",
      "url": "http://localhost:8000/sse",
      "description": "An example SSE service for testing purposes."
    }
  }
}
```

### 3. 运行客户端

```bash
python client.py --query "使用工具回答这个问题" --model-type ollama --model-name qwen2.5:7b --model-url http://localhost:11434
```

## 参数说明

```
--model-type: 使用的模型类型(openai或ollama)
--model-name: 使用的模型名称
--model-url: 模型的URL
--config-file: MCP服务列表的配置文件路径
--service-name: 指定加载的MCP服务名称(可选)
--query: 要询问的问题
```

## 依赖项

- python-mcp-sdk
- ollama-python
- openai
- httpx
- uvicorn
- starlette

## 许可证

MIT