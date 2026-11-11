"""
公共配置：所有示例都从这里拿到 client 和 MODEL。
换模型、换平台只需要改 .env 文件，不用改任何代码。
"""
import os

from openai import OpenAI

try:
    from dotenv import load_dotenv
    load_dotenv()                       # 读取同目录下的 .env 文件，把里面的配置放进环境变量
except ImportError:
    pass                                # 没装 python-dotenv 也能用，只是要自己设置环境变量

API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

if not API_KEY or API_KEY.startswith("sk-在这里"):
    raise SystemExit("没有找到可用的 LLM_API_KEY：请把 .env.example 复制为 .env 并填入你的 Key（见 README 第 2 步）。")

# 注意：Key 永远从环境变量读，绝不写死在代码里，否则一上传 GitHub 就泄露了
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def to_dict(message):
    """把模型返回的消息对象转成普通字典，方便放回对话历史（去掉空字段，兼容各家接口）。"""
    return message.model_dump(exclude_none=True)
