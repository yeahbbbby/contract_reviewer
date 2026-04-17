"""
LLM客户端模块
支持多种LLM提供商（Anthropic Claude、阿里云Qwen、OpenAI等）
"""
import os
from typing import Dict, List, Optional
from enum import Enum
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class LLMProvider(Enum):
    """LLM提供商枚举"""
    ANTHROPIC = "anthropic"
    QWEN = "qwen"
    OPENAI = "openai"


class LLMClient:
    """统一的LLM客户端"""

    def __init__(self, provider: str = None, api_key: str = None, **kwargs):
        """
        初始化LLM客户端

        Args:
            provider: 提供商名称 (anthropic/qwen/openai)
            api_key: API密钥
            **kwargs: 其他配置参数
        """
        self.provider = provider or os.getenv('LLM_PROVIDER', 'qwen')
        self.api_key = api_key or os.getenv('LLM_API_KEY')
        self.base_url = kwargs.get('base_url') or os.getenv('LLM_BASE_URL')
        self.model = kwargs.get('model') or os.getenv('LLM_MODEL')

        # 初始化对应的客户端
        self.client = self._init_client()

    def _init_client(self):
        """初始化具体的客户端"""
        if self.provider == 'anthropic':
            return self._init_anthropic()
        elif self.provider == 'qwen':
            return self._init_qwen()
        elif self.provider == 'openai':
            return self._init_openai()
        else:
            raise ValueError(f"不支持的LLM提供商: {self.provider}")

    def _init_anthropic(self):
        """初始化Anthropic客户端"""
        try:
            import anthropic
            return anthropic.Anthropic(api_key=self.api_key)
        except ImportError:
            raise ImportError("请安装anthropic库: pip install anthropic")

    def _init_qwen(self):
        """初始化Qwen客户端"""
        try:
            from openai import OpenAI
            # Qwen使用OpenAI兼容接口
            return OpenAI(
                api_key=self.api_key,
                base_url=self.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
        except ImportError:
            raise ImportError("请安装openai库: pip install openai")

    def _init_openai(self):
        """初始化OpenAI客户端"""
        try:
            from openai import OpenAI
            return OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
        except ImportError:
            raise ImportError("请安装openai库: pip install openai")

    def chat(self, messages: List[Dict], system: str = None,
             max_tokens: int = 4096, temperature: float = 0.7) -> str:
        """
        统一的对话接口

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            system: 系统提示词
            max_tokens: 最大token数
            temperature: 温度参数

        Returns:
            模型回复文本
        """
        if self.provider == 'anthropic':
            return self._chat_anthropic(messages, system, max_tokens, temperature)
        elif self.provider == 'qwen':
            return self._chat_qwen(messages, system, max_tokens, temperature)
        elif self.provider == 'openai':
            return self._chat_openai(messages, system, max_tokens, temperature)

    def _chat_anthropic(self, messages: List[Dict], system: str,
                       max_tokens: int, temperature: float) -> str:
        """Anthropic Claude对话"""
        response = self.client.messages.create(
            model=self.model or "claude-opus-4-6",
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages
        )
        return response.content[0].text

    def _chat_qwen(self, messages: List[Dict], system: str,
                   max_tokens: int, temperature: float) -> str:
        """Qwen对话（OpenAI兼容接口）"""
        # 如果有system提示词，添加到messages开头
        if system:
            messages = [{"role": "system", "content": system}] + messages

        response = self.client.chat.completions.create(
            model=self.model or "qwen-plus",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        return response.choices[0].message.content

    def _chat_openai(self, messages: List[Dict], system: str,
                    max_tokens: int, temperature: float) -> str:
        """OpenAI对话"""
        if system:
            messages = [{"role": "system", "content": system}] + messages

        response = self.client.chat.completions.create(
            model=self.model or "gpt-4",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        return response.choices[0].message.content

    def analyze(self, prompt: str, system_prompt: str = None,
                max_tokens: int = 4096) -> str:
        """
        简化的分析接口（单轮对话）

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            max_tokens: 最大token数

        Returns:
            分析结果文本
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, system=system_prompt, max_tokens=max_tokens)


# 全局单例客户端
_global_client = None


def get_llm_client() -> LLMClient:
    """获取全局LLM客户端"""
    global _global_client
    if _global_client is None:
        _global_client = LLMClient()
    return _global_client


def set_llm_client(client: LLMClient):
    """设置全局LLM客户端"""
    global _global_client
    _global_client = client
