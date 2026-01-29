"""
AI parser modules - PydanticAI with OpenAI-compatible providers
"""

from services.scraper.ai.cache import AIParserCache, get_cache
from services.scraper.ai.parser import parse_with_ai
from services.scraper.ai.router import should_use_ai_parser

__all__ = [
    "AIParserCache",
    "get_cache",
    "parse_with_ai",
    "should_use_ai_parser",
]
