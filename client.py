import argparse
import asyncio
import json
import boto3
import logging
import datetime
import time
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from ollama import ChatResponse, Client
from openai import OpenAI
import os
from dataclasses import dataclass

# 定义 Context 类
@dataclass
class Context:
    args: None
    system_message: None
    messages: list
    with_tools: bool = False
    services: list = None
    combined_tools: list = None    

context = Context(None, None, [])
model_type = "ollama"
model_url = "http://192.168.16.218:11434"
model_name = "qwen2.5:32b"
mcp_config = "mcp_config.json"
service_name = None
system_promt = "You are a helpful AI assistant. " + \
    "使用中文回答, " #", Use Wiki website first, "
start_query = None

# 配置日志格式，包含毫秒级时间戳
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def handle_input(promt="请继续输入对话内容: "):
    """
    检查用户输入是否需要继续对话。
    """
    exit_chat = False
    user_input = None
    while True:
        user_input = input(promt)
        if user_input.strip() == "":
            print("输入不能为空，请重新输入。")
            continue

        if user_input.lower() == "exit":
            return None, True  # 退出对话

        if user_input.lower() == "clear":
            context.messages.clear()
            print("Messages cleared.")
        elif user_input.lower() == "reset":
            context.messages.clear()
            context.messages.append(context.system_message)  # 修复：清空并追加 system_message
            print("Messages reset to system message.")
        elif user_input.lower() == "tools":
            print("Available tools:", context.combined_tools)
        elif user_input.lower() == "services":
            print("Available services:", context.services)
        elif user_input.lower() == "model":
            print("Model name:", context.args.model_name)
        elif user_input.lower() == "url":
            print("Model URL:", context.args.model_url)
        elif user_input.lower() == "help":
            print("Available commands: clear, reset, tools, services, model, url, exit, help")
        else:
            # 处理正常输入                  
            message = { 
                "role": "user", 
                "content": user_input
            }
            context.messages.append(message)
            return user_input, False  # 继续对话

def load_mcp_services(config_file, service_name=None):
    """
    从JSON配置文件加载MCP服务列表。
    
    参数：
        config_file (str): 配置文件路径
        service_name (str): 指定加载的服务名称，默认为None加载所有服务

    返回：
        list: 加载的服务列表
    """
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    services = config.get("mcpServers", {})

    if service_name:
        return [{"name": service_name, **services[service_name]}] if service_name in services else []

    return [{"name": name, **details} for name, details in services.items()]

async def fetch_and_combine_tools(services):
    """
    遍历MCP服务列表，获取并拼接为完整的工具列表。

    参数：
        services (list): MCP服务列表

    返回：
        list: 拼接后的工具列表
    """
    combined_tools = []

    for service in services:
        logger.info("Fetching tools from service: %s", service['name'])
        try:
            service_type = service.get('type', 'stdio').lower()

            if service_type == 'sse':
                async with sse_client(service['url']) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        # 稍等片刻，让会话初始化
                        await asyncio.sleep(1)
                        logger.info("Session initialized")

                        tools_result = await session.list_tools()

                        tools_list = [{
                            "serviceName": service['name'],
                            "name": tool.name, 
                            "description": tool.description,
                            "inputSchema": tool.inputSchema} for tool in tools_result.tools]
                        logger.info("Available tools: %s", tools_list)
                        combined_tools.extend(tools_list)
            elif service_type == 'stdio':
                from mcp.client.stdio import stdio_client, StdioServerParameters

                process_env = os.environ.copy()
                if 'env' in service:
                    process_env.update(service['env'])

                cmd = StdioServerParameters(
                    command=service['command'].split()[0],
                    args=service['command'].split()[1:],
                    env=process_env
                )
                async with stdio_client(cmd) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()

                        tools_result = await session.list_tools()

                        tools_list = [{
                            "serviceName": service['name'],
                            "name": tool.name, 
                            "description": tool.description,
                            "inputSchema": tool.inputSchema} for tool in tools_result.tools]
                        logger.info("Available tools: %s", tools_list)
                        combined_tools.extend(tools_list)
            else:
                raise ValueError(f"Unsupported service type: {service_type}")

        except Exception as err:
            logger.error("Failed to fetch tools from service %s: %s", service['name'], str(err))

    return combined_tools  # 返回工具列表

async def format_system_promt():
    """
    格式化系统提示信息。
    """
    with_tools = False
    context.services = load_mcp_services(context.args.config_file, context.args.service_name)
    if not context.services:
        logger.warning("未加载到任何MCP服务，请检查配置文件或服务名称")

    logger.info("加载的MCP服务: %s", context.services)
    # 获取并合并所有服务的工具列表
    context.combined_tools = await fetch_and_combine_tools(context.services)
    if not context.combined_tools:
        logger.warning("未加载到任何工具，请检查配置文件或服务名称")
    else:
        logger.info("加载的工具: %s", context.combined_tools)
        with_tools = True

    context.with_tools = with_tools
    # 生成系统提示信息，with_tools为true时，使用工具列表
    if with_tools:
        system_message = { 
            "role": "system", 
            "content": system_promt + #", Use Wiki website first, " +
                "You have access to the following tools: " + json.dumps(context.combined_tools) +
                 ". Use these tools if called to answer any questions posed by the prompt (user)."}
    else:
        # 如果没有工具，则使用默认的系统提示信息
        system_message = { 
            "role": "system", 
            "content": system_promt}

    return system_message

def convert_tool_format(tools):
    """
    将工具转换为Ollama所需的格式。

    参数：
        tools (list): 工具对象列表

    返回：
        dict: Ollama所需格式的工具
    """
    converted_tools = []

    for tool in tools:
        print(f"Converting tool: {tool['name']}")
        converted_tool = {
             'type': 'function',
             'function': {
                 'name': tool['name'],
                 'description': tool['description'],
                 'parameters': tool['inputSchema']
                 }
             }
        converted_tools.append(converted_tool)

    return converted_tools

async def call_tool_with_selected_session(services, combined_tools, tool_name, arguments):
    """
    根据chat选择的工具，选择相应的MCP服务会话并进行工具调用。

    参数：
        services (list): MCP服务列表
        tool_name (str): 选择的工具名称
        arguments (dict): 工具调用的参数

    返回：
        dict: 工具调用的结果
    """
    # 先从combined_tools中查找匹配tool_name的serviceName
    matching_services = [tool['serviceName'] for tool in combined_tools if tool['name'] == tool_name]
    if not matching_services:
        raise ValueError(f"Tool {tool_name} not found in any service")

    for service in services:
        if service['name'] not in matching_services:
            continue
        #logger.info("Searching for tool %s in service: %s", tool_name, service['name'])
        try:
            service_type = service.get('type', 'stdio').lower()

            if service_type == 'sse':
                async with sse_client(service['url']) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        # 稍等片刻，让会话初始化
                        await asyncio.sleep(1)
                        logger.info("Session initialized")

                        logger.info("Tool %s found in service: %s", tool_name, service['name'])
                        start_time = time.time()
                        tool_response = await session.call_tool(tool_name, arguments)
                        elapsed_time = time.time() - start_time
                        logger.info("Tool %s executed in %.3f seconds", tool_name, elapsed_time)
                        return tool_response
            elif service_type == 'stdio':
                from mcp.client.stdio import stdio_client, StdioServerParameters

                process_env = os.environ.copy()
                if 'env' in service:
                    process_env.update(service['env'])

                cmd = StdioServerParameters(
                    command=service['command'].split()[0],
                    args=service['command'].split()[1:],
                    env=process_env
                )
                async with stdio_client(cmd) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()

                        logger.info("Tool %s found in service: %s", tool_name, service['name'])
                        start_time = time.time()
                        tool_response = await session.call_tool(tool_name, arguments)
                        elapsed_time = time.time() - start_time
                        logger.info("Tool %s executed in %.3f seconds", tool_name, elapsed_time)
                        return tool_response
            else:
                raise ValueError(f"Unsupported service type: {service_type}")
        except Exception as err:
            logger.error("Failed to call tool %s in service %s: %s", tool_name, service['name'], str(err))

    raise ValueError(f"Tool {tool_name} not found in any service")

async def complete():
    """
    执行对话并完成任务。
    """
    logger.info("Starting session using %s model", context.args.model_type)

    try:
        converted_tools = None
        if context.with_tools:
            converted_tools = convert_tool_format(context.combined_tools)
        # 与大模型服务交互
        if context.args.model_type.lower() == "ollama":
            client = Client(host=context.args.model_url)
            while True:
                print("Messages:", context.messages)
                response: ChatResponse = client.chat(
                    model=context.args.model_name,
                    messages=context.messages,                    
                    tools=converted_tools
                )
                print("Response from Ollama:")
                print(response.message)
                #print(response.message.content)
                context.messages.append(response['message'])

                if response.message.tool_calls:
                    for tool_call in response.message.tool_calls:
                        tool_name = tool_call.function.name
                        #tool_id = tool_call.id
                        # 如果arguments是字符串，则需要解析为字典
                        if isinstance(tool_call.function.arguments, str):
                            try:
                                arguments = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                arguments = tool_call.function.arguments
                        else:
                            arguments = tool_call.function.arguments
                        tool_result = await call_tool_with_selected_session(context.services, context.combined_tools, tool_name, arguments)
                        context.messages.append({
                            #"tool_call_id": tool_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": str({"toolResult": tool_result})
                        })
                else:
                    user_input, exit_chat = handle_input()
                    if exit_chat:
                        print("退出对话")
                        break

        elif context.args.model_type.lower() == "openai":
            openai_client = OpenAI(base_url=context.args.model_url, api_key=os.getenv("OPENAI_API_KEY"))
            while True:
                print("Messages:", context.messages)
                response = openai_client.chat.completions.create(
                    model=context.args.model_name,
                    messages=context.messages,
                    tools=converted_tools
                )
                print("Response from OpenAI:")
                print(response.choices[0].message.content)
                context.messages.append(response.choices[0].message)

                if response.choices[0].message.tool_calls:
                    for tool_call in response.choices[0].message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_id = tool_call.id
                        # 如果arguments是字符串，则需要解析为字典
                        if isinstance(tool_call.function.arguments, str):
                            try:
                                arguments = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                arguments = tool_call.function.arguments
                        else:
                            arguments = tool_call.function.arguments
                        tool_result = await call_tool_with_selected_session(context.services, context.combined_tools, tool_name, arguments)
                        context.messages.append({
                            "tool_call_id": tool_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": str(tool_result)
                        })
                else:
                    user_input, exit_chat = handle_input()
                    if exit_chat:
                        print("退出对话")
                        break
        else:
            raise ValueError(f"Unsupported model type: {context.args.model_type}")
    except Exception as err:
        logger.error("Error during conversation: %s", str(err))
        raise

async def main():
    parser = argparse.ArgumentParser(description='运行MCP客户端')
    parser.add_argument('-t', '--model-type', type=str, choices=['openai', 'ollama'], default=model_type,
                        help='使用的模型类型：openai或ollama')
    parser.add_argument('-n', '--model-name', type=str, default=model_name,
                        help='使用的模型名称')
    parser.add_argument('-l', '--model-url', type=str, default=model_url,
                        help='模型的URL')
    parser.add_argument('-c', '--config-file', type=str, default=mcp_config,
                        help='MCP服务列表的配置文件路径')
    parser.add_argument('-s', '--service-name', type=str, default=service_name,
                        help='指定加载的MCP服务名称，默认为None加载所有服务')
    parser.add_argument('-q', '--query', type=str, default=start_query,
                        help='要询问的问题')

    context.args = parser.parse_args()
    print("命令行参数:", context.args)

    context.system_message = await format_system_promt()
    context.messages.append(context.system_message)

    # 未指定query或者query内容为空时，提示用户输入查询的问题
    if not context.args.query:
        context.args.query, exit_chat = handle_input("请输入要询问的问题: ")
        if exit_chat:
            print("退出对话")
            return
    else:
        context.args.query = context.args.query.strip()
        context.messages.append({
            "role": "user",
            "content": context.args.query
        })

    start_time = datetime.datetime.now()
    logger.info("开始执行，时间: %s.%03d", 
                start_time.strftime("%Y-%m-%d %H:%M:%S"), 
                start_time.microsecond // 1000)

    await complete()

    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    logger.info("执行完成，时间: %s.%03d，总耗时: %.3f秒", 
               end_time.strftime("%Y-%m-%d %H:%M:%S"), 
               end_time.microsecond // 1000, 
               duration)

if __name__ == "__main__":
    asyncio.run(main())
