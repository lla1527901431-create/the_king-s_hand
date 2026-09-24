import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

def get_llm():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("没有读到 DEEPSEEK_API_KEY，请检查 .env 文件")
    if not api_key.isascii():
        raise ValueError(
            "DEEPSEEK_API_KEY 含有非 ASCII 字符，请检查是不是还留着中文占位符"
        )
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL"),
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0,
        # 输出稳定，减少随机性
    )

def get_memory_llm():
    return ChatOpenAI(
        model=os.getenv("MEMORY_MODEL"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0,
    )
