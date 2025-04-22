import asyncio
import base64
import json
import logging
from typing import Dict, Generic, Optional, TypeVar

from browser_use import Browser as BrowserUseBrowser
from browser_use import BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.dom.service import DomService
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from app.config import config
from app.llm import LLM
from app.tool.base import BaseTool, ToolResult
from app.tool.web_search import WebSearch


logger = logging.getLogger(__name__)

_BROWSER_DESCRIPTION = """\
A powerful browser automation tool that allows interaction with web pages through various actions.
* This tool provides commands for controlling a browser session, navigating web pages, and extracting information
* It maintains state across calls, keeping the browser session alive until explicitly closed
* Use this when you need to browse websites, fill forms, click buttons, extract content, or perform web searches
* Each action requires specific parameters as defined in the tool's dependencies

Key capabilities include:
* Navigation: Go to specific URLs, go back, search the web, or refresh pages
* Interaction: Click elements, input text, select from dropdowns, send keyboard commands
* Scrolling: Scroll up/down by pixel amount or scroll to specific text
* Content extraction: Extract and analyze content from web pages based on specific goals
* Tab management: Switch between tabs, open new tabs, or close tabs

Note: When using element indices, refer to the numbered elements shown in the current browser state.
"""

# 定义页面加载超时时间常量（毫秒）
DEFAULT_TIMEOUT_MS = 15000
# 定义截图质量
SCREENSHOT_QUALITY = 70

Context = TypeVar("Context")


class BrowserUseTool(BaseTool, Generic[Context]):
    name: str = "browser_use"
    description: str = _BROWSER_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "go_to_url",
                    "click_element",
                    "input_text",
                    "scroll_down",
                    "scroll_up",
                    "scroll_to_text",
                    "send_keys",
                    "get_dropdown_options",
                    "select_dropdown_option",
                    "go_back",
                    "web_search",
                    "wait",
                    "extract_content",
                    "switch_tab",
                    "open_tab",
                    "close_tab",
                ],
                "description": "The browser action to perform",
            },
            "url": {
                "type": "string",
                "description": "URL for 'go_to_url' or 'open_tab' actions",
            },
            "index": {
                "type": "integer",
                "description": "Element index for 'click_element', 'input_text', 'get_dropdown_options', or 'select_dropdown_option' actions",
            },
            "text": {
                "type": "string",
                "description": "Text for 'input_text', 'scroll_to_text', or 'select_dropdown_option' actions",
            },
            "scroll_amount": {
                "type": "integer",
                "description": "Pixels to scroll (positive for down, negative for up) for 'scroll_down' or 'scroll_up' actions",
            },
            "tab_id": {
                "type": "integer",
                "description": "Tab ID for 'switch_tab' action",
            },
            "query": {
                "type": "string",
                "description": "Search query for 'web_search' action",
            },
            "goal": {
                "type": "string",
                "description": "Extraction goal for 'extract_content' action",
            },
            "keys": {
                "type": "string",
                "description": "Keys to send for 'send_keys' action",
            },
            "seconds": {
                "type": "integer",
                "description": "Seconds to wait for 'wait' action",
            },
        },
        "required": ["action"],
        "dependencies": {
            "go_to_url": ["url"],
            "click_element": ["index"],
            "input_text": ["index", "text"],
            "switch_tab": ["tab_id"],
            "open_tab": ["url"],
            "scroll_down": ["scroll_amount"],
            "scroll_up": ["scroll_amount"],
            "scroll_to_text": ["text"],
            "send_keys": ["keys"],
            "get_dropdown_options": ["index"],
            "select_dropdown_option": ["index", "text"],
            "go_back": [],
            "web_search": ["query"],
            "wait": ["seconds"],
            "extract_content": ["goal"],
        },
    }

    # 为不同类型的操作创建不同的锁
    locks: Dict[str, asyncio.Lock] = Field(
        default_factory=lambda: {
            "browser_init": asyncio.Lock(),  # 浏览器初始化锁
            "navigation": asyncio.Lock(),  # 导航操作锁
            "interaction": asyncio.Lock(),  # 元素交互锁
            "extraction": asyncio.Lock(),  # 内容提取锁
            "tab": asyncio.Lock(),  # 标签页管理锁
            "state": asyncio.Lock(),  # 状态获取锁
            "cleanup": asyncio.Lock(),  # 清理资源锁
        }
    )
    browser: Optional[BrowserUseBrowser] = Field(default=None, exclude=True)
    context: Optional[BrowserContext] = Field(default=None, exclude=True)
    dom_service: Optional[DomService] = Field(default=None, exclude=True)
    web_search_tool: WebSearch = Field(default_factory=WebSearch, exclude=True)

    # Context for generic functionality
    tool_context: Optional[Context] = Field(default=None, exclude=True)

    llm: Optional[LLM] = Field(default_factory=LLM)

    @field_validator("parameters", mode="before")
    def validate_parameters(cls, v: dict, info: ValidationInfo) -> dict:
        if not v:
            raise ValueError("Parameters cannot be empty")
        return v

    async def _ensure_browser_initialized(self) -> BrowserContext:
        """Ensure browser and context are initialized."""
        async with self.locks["browser_init"]:
            if self.browser is None:
                # 默认启用无头模式以提高性能
                browser_config_kwargs = {"headless": True, "disable_security": True}

                if config.browser_config:
                    from browser_use.browser.browser import ProxySettings

                    # handle proxy settings.
                    if (
                        config.browser_config.proxy
                        and config.browser_config.proxy.server
                    ):
                        browser_config_kwargs["proxy"] = ProxySettings(
                            server=config.browser_config.proxy.server,
                            username=config.browser_config.proxy.username,
                            password=config.browser_config.proxy.password,
                        )

                    browser_attrs = [
                        "headless",
                        "disable_security",
                        "extra_chromium_args",
                        "chrome_instance_path",
                        "wss_url",
                        "cdp_url",
                    ]

                    for attr in browser_attrs:
                        value = getattr(config.browser_config, attr, None)
                        if value is not None:
                            if not isinstance(value, list) or value:
                                browser_config_kwargs[attr] = value

                # 添加禁用图片和视频加载的参数，提高性能
                extra_args = browser_config_kwargs.get("extra_chromium_args", [])
                extra_args.extend(
                    [
                        "--disable-images",
                        "--blink-settings=imagesEnabled=false",
                        "--disable-video",
                    ]
                )
                browser_config_kwargs["extra_chromium_args"] = extra_args

                self.browser = BrowserUseBrowser(BrowserConfig(**browser_config_kwargs))

            if self.context is None:
                context_config = BrowserContextConfig()

                # if there is context config in the config, use it.
                if (
                    config.browser_config
                    and hasattr(config.browser_config, "new_context_config")
                    and config.browser_config.new_context_config
                ):
                    context_config = config.browser_config.new_context_config

                self.context = await self.browser.new_context(context_config)
                self.dom_service = DomService(await self.context.get_current_page())

            return self.context

    # 获取特定操作类型的锁
    def _get_lock_for_action(self, action: str) -> asyncio.Lock:
        """根据操作类型获取相应的锁"""
        navigation_actions = ["go_to_url", "go_back", "refresh", "web_search"]
        interaction_actions = [
            "click_element",
            "input_text",
            "scroll_down",
            "scroll_up",
            "scroll_to_text",
            "send_keys",
            "get_dropdown_options",
            "select_dropdown_option",
            "wait",
        ]
        tab_actions = ["switch_tab", "open_tab", "close_tab"]
        extraction_actions = ["extract_content"]

        if action in navigation_actions:
            return self.locks["navigation"]
        elif action in interaction_actions:
            return self.locks["interaction"]
        elif action in tab_actions:
            return self.locks["tab"]
        elif action in extraction_actions:
            return self.locks["extraction"]
        else:
            # 默认使用导航锁
            return self.locks["navigation"]

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        index: Optional[int] = None,
        text: Optional[str] = None,
        scroll_amount: Optional[int] = None,
        tab_id: Optional[int] = None,
        query: Optional[str] = None,
        goal: Optional[str] = None,
        keys: Optional[str] = None,
        seconds: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        """
        Execute a specified browser action.

        Args:
            action: The browser action to perform
            url: URL for navigation or new tab
            index: Element index for click or input actions
            text: Text for input action or search query
            scroll_amount: Pixels to scroll for scroll action
            tab_id: Tab ID for switch_tab action
            query: Search query for Google search
            goal: Extraction goal for content extraction
            keys: Keys to send for keyboard actions
            seconds: Seconds to wait
            **kwargs: Additional arguments

        Returns:
            ToolResult with the action's output or error
        """
        # 确保浏览器已初始化（使用初始化锁）
        context = await self._ensure_browser_initialized()

        # 根据操作类型获取相应的锁
        lock = self._get_lock_for_action(action)

        async with lock:
            try:
                # Get max content length from config
                max_content_length = getattr(
                    config.browser_config, "max_content_length", 2000
                )

                # Navigation actions
                if action == "go_to_url":
                    if not url:
                        return ToolResult(
                            error="URL is required for 'go_to_url' action"
                        )
                    page = await context.get_current_page()
                    await page.goto(url, timeout=DEFAULT_TIMEOUT_MS)
                    await page.wait_for_load_state(timeout=DEFAULT_TIMEOUT_MS)
                    return ToolResult(output=f"Navigated to {url}")

                elif action == "go_back":
                    await context.go_back()
                    # 添加页面加载状态等待超时
                    page = await context.get_current_page()
                    await page.wait_for_load_state(timeout=DEFAULT_TIMEOUT_MS)
                    return ToolResult(output="Navigated back")

                elif action == "refresh":
                    await context.refresh_page()
                    # 添加页面加载状态等待超时
                    page = await context.get_current_page()
                    await page.wait_for_load_state(timeout=DEFAULT_TIMEOUT_MS)
                    return ToolResult(output="Refreshed current page")

                elif action == "web_search":
                    if not query:
                        return ToolResult(
                            error="Query is required for 'web_search' action"
                        )
                    try:
                        # 执行搜索
                        logger.info(f"执行网络搜索: {query}")
                        search_response = await self.web_search_tool.execute(
                            query=query, fetch_content=True, num_results=1
                        )

                        # 验证搜索结果
                        if not search_response.results:
                            return ToolResult(error=f"搜索未返回任何结果: {query}")

                        # 获取第一个搜索结果并确保URL格式正确
                        first_search_result = search_response.results[0]
                        url_to_navigate = first_search_result.url

                        # 确保URL包含协议
                        from urllib.parse import urlparse

                        parsed_url = urlparse(url_to_navigate)
                        if not parsed_url.scheme:
                            if url_to_navigate.startswith("//"):
                                url_to_navigate = f"https:{url_to_navigate}"
                            else:
                                url_to_navigate = f"https://{url_to_navigate}"
                            logger.info(f"修正URL格式: {url_to_navigate}")

                        # 验证URL是否有效
                        if not parsed_url.netloc:
                            return ToolResult(error=f"搜索结果URL无效: {url_to_navigate}")

                        # 导航到URL，设置超时
                        page = await context.get_current_page()

                        # 使用默认超时时间
                        try:
                            logger.info(f"导航到搜索结果: {url_to_navigate}")
                            await page.goto(url_to_navigate, timeout=DEFAULT_TIMEOUT_MS)
                            await page.wait_for_load_state(timeout=DEFAULT_TIMEOUT_MS)
                            return ToolResult(
                                output=f"成功导航到搜索结果: {url_to_navigate}\n\n{search_response.output}"
                            )
                        except Exception as nav_error:
                            logger.warning(f"导航到URL时出错: {nav_error}")
                            return ToolResult(
                                output=f"无法导航到URL，但搜索结果如下:\n\n{search_response.output}"
                            )
                    except Exception as e:
                        error_msg = f"Web search failed: {str(e)}"
                        logger.error(error_msg)
                        return ToolResult(error=error_msg)

                # Element interaction actions
                elif action == "click_element":
                    if index is None:
                        return ToolResult(
                            error="Index is required for 'click_element' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    download_path = await context._click_element_node(element)
                    output = f"Clicked element at index {index}"
                    if download_path:
                        output += f" - Downloaded file to {download_path}"
                    return ToolResult(output=output)

                elif action == "input_text":
                    if index is None or not text:
                        return ToolResult(
                            error="Index and text are required for 'input_text' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    await context._input_text_element_node(element, text)
                    return ToolResult(
                        output=f"Input '{text}' into element at index {index}"
                    )

                elif action == "scroll_down" or action == "scroll_up":
                    direction = 1 if action == "scroll_down" else -1
                    amount = (
                        scroll_amount
                        if scroll_amount is not None
                        else context.config.browser_window_size["height"]
                    )
                    await context.execute_javascript(
                        f"window.scrollBy(0, {direction * amount});"
                    )
                    return ToolResult(
                        output=f"Scrolled {'down' if direction > 0 else 'up'} by {amount} pixels"
                    )

                elif action == "scroll_to_text":
                    if not text:
                        return ToolResult(
                            error="Text is required for 'scroll_to_text' action"
                        )
                    page = await context.get_current_page()
                    try:
                        locator = page.get_by_text(text, exact=False)
                        await locator.scroll_into_view_if_needed(
                            timeout=DEFAULT_TIMEOUT_MS
                        )
                        return ToolResult(output=f"Scrolled to text: '{text}'")
                    except Exception as e:
                        return ToolResult(error=f"Failed to scroll to text: {str(e)}")

                elif action == "send_keys":
                    if not keys:
                        return ToolResult(
                            error="Keys are required for 'send_keys' action"
                        )
                    page = await context.get_current_page()
                    await page.keyboard.press(keys)
                    return ToolResult(output=f"Sent keys: {keys}")

                elif action == "get_dropdown_options":
                    if index is None:
                        return ToolResult(
                            error="Index is required for 'get_dropdown_options' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    page = await context.get_current_page()
                    options = await page.evaluate(
                        """
                        (xpath) => {
                            const select = document.evaluate(xpath, document, null,
                                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            if (!select) return null;
                            return Array.from(select.options).map(opt => ({
                                text: opt.text,
                                value: opt.value,
                                index: opt.index
                            }));
                        }
                    """,
                        element.xpath,
                    )
                    return ToolResult(output=f"Dropdown options: {options}")

                elif action == "select_dropdown_option":
                    if index is None or not text:
                        return ToolResult(
                            error="Index and text are required for 'select_dropdown_option' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    page = await context.get_current_page()
                    await page.select_option(element.xpath, label=text)
                    return ToolResult(
                        output=f"Selected option '{text}' from dropdown at index {index}"
                    )

                # Content extraction actions
                elif action == "extract_content":
                    if not goal:
                        return ToolResult(
                            error="Goal is required for 'extract_content' action"
                        )

                    page = await context.get_current_page()

                    # 优化: 使用更高效的内容提取方法，先尝试提取关键内容
                    # 1. 先尝试只提取可见文本内容，而不是整个HTML文档
                    try:
                        # 使用JS提取页面可见文本内容
                        visible_text = await page.evaluate(
                            """
                            () => {
                                // 函数来判断元素是否可见
                                function isVisible(elem) {
                                    if (!elem) return false;
                                    const style = window.getComputedStyle(elem);
                                    return style.display !== 'none' &&
                                           style.visibility !== 'hidden' &&
                                           style.opacity !== '0';
                                }

                                // 收集页面所有可见文本
                                const textElements = [];
                                const walker = document.createTreeWalker(
                                    document.body,
                                    NodeFilter.SHOW_TEXT,
                                    { acceptNode: node => isVisible(node.parentElement) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT }
                                );

                                while(walker.nextNode()) {
                                    const text = walker.currentNode.textContent.trim();
                                    if (text) textElements.push(text);
                                }

                                return textElements.join('\\n');
                            }
                        """
                        )

                        # 2. 根据目标智能提取相关内容
                        # 使用关键词匹配来获取与goal相关的段落
                        import re

                        # 分析goal中的关键词
                        goal_keywords = re.findall(r"\w+", goal.lower())
                        goal_keywords = [
                            kw for kw in goal_keywords if len(kw) > 3
                        ]  # 过滤短词

                        # 将文本分成段落并计算每段与目标的相关性
                        paragraphs = visible_text.split("\n\n")
                        relevant_paragraphs = []

                        for para in paragraphs:
                            if not para.strip():
                                continue

                            # 计算段落与目标的相关性得分
                            para_words = re.findall(r"\w+", para.lower())
                            matches = sum(1 for kw in goal_keywords if kw in para_words)

                            if matches > 0 or len(paragraphs) <= 5:  # 相关段落或总段落数少
                                relevant_paragraphs.append(para)

                        # 如果没找到相关段落，则使用前几段加标题
                        if not relevant_paragraphs and paragraphs:
                            # 尝试获取页面标题
                            title = await page.title()
                            relevant_paragraphs = [title] + paragraphs[:3]

                        # 合并提取的内容，确保不超过最大长度
                        content = "\n\n".join(relevant_paragraphs)

                    except Exception as extract_error:
                        logger.warning(f"优化内容提取失败，回退到标准方法: {extract_error}")
                        # 回退到原始方法
                        import markdownify

                        content = markdownify.markdownify(await page.content())

                    # 确保内容不超过最大长度限制
                    content = content[:max_content_length]

                    prompt = f"""\
Your task is to extract the content of the page. You will be given a page and a goal, and you should extract all relevant information around this goal from the page. Be concise and focused. Respond in json format.
Extraction goal: {goal}

Page content:
{content}
"""
                    messages = [{"role": "system", "content": prompt}]

                    # Define extraction function schema
                    extraction_function = {
                        "type": "function",
                        "function": {
                            "name": "extract_content",
                            "description": "Extract specific information from a webpage based on a goal",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "extracted_content": {
                                        "type": "object",
                                        "description": "The content extracted from the page according to the goal",
                                        "properties": {
                                            "text": {
                                                "type": "string",
                                                "description": "Text content extracted from the page",
                                            },
                                            "metadata": {
                                                "type": "object",
                                                "description": "Additional metadata about the extracted content",
                                                "properties": {
                                                    "source": {
                                                        "type": "string",
                                                        "description": "Source of the extracted content",
                                                    }
                                                },
                                            },
                                        },
                                    }
                                },
                                "required": ["extracted_content"],
                            },
                        },
                    }

                    # Use LLM to extract content with required function calling
                    response = await self.llm.ask_tool(
                        messages,
                        tools=[extraction_function],
                        tool_choice="required",
                    )

                    if response and response.tool_calls:
                        args = json.loads(response.tool_calls[0].function.arguments)
                        extracted_content = args.get("extracted_content", {})
                        return ToolResult(
                            output=f"Extracted from page:\n{extracted_content}\n"
                        )

                    return ToolResult(output="No content was extracted from the page.")

                # Tab management actions
                elif action == "switch_tab":
                    if tab_id is None:
                        return ToolResult(
                            error="Tab ID is required for 'switch_tab' action"
                        )
                    await context.switch_to_tab(tab_id)
                    page = await context.get_current_page()
                    await page.wait_for_load_state(timeout=DEFAULT_TIMEOUT_MS)
                    return ToolResult(output=f"Switched to tab {tab_id}")

                elif action == "open_tab":
                    if not url:
                        return ToolResult(error="URL is required for 'open_tab' action")
                    await context.create_new_tab(url)
                    # 添加页面加载等待超时
                    page = await context.get_current_page()
                    await page.wait_for_load_state(timeout=DEFAULT_TIMEOUT_MS)
                    return ToolResult(output=f"Opened new tab with {url}")

                elif action == "close_tab":
                    await context.close_current_tab()
                    return ToolResult(output="Closed current tab")

                # Utility actions
                elif action == "wait":
                    seconds_to_wait = seconds if seconds is not None else 3
                    await asyncio.sleep(seconds_to_wait)
                    return ToolResult(output=f"Waited for {seconds_to_wait} seconds")

                else:
                    return ToolResult(error=f"Unknown action: {action}")

            except Exception as e:
                return ToolResult(error=f"Browser action '{action}' failed: {str(e)}")

    async def get_current_state(
        self, context: Optional[BrowserContext] = None
    ) -> ToolResult:
        """
        Get the current browser state as a ToolResult.
        If context is not provided, uses self.context.
        """
        async with self.locks["state"]:
            try:
                # Use provided context or fall back to self.context
                ctx = context or self.context
                if not ctx:
                    return ToolResult(error="Browser context not initialized")

                state = await ctx.get_state()

                # Create a viewport_info dictionary if it doesn't exist
                viewport_height = 0
                if hasattr(state, "viewport_info") and state.viewport_info:
                    viewport_height = state.viewport_info.height
                elif hasattr(ctx, "config") and hasattr(
                    ctx.config, "browser_window_size"
                ):
                    viewport_height = ctx.config.browser_window_size.get("height", 0)

                # Take a screenshot for the state
                page = await ctx.get_current_page()

                await page.bring_to_front()
                await page.wait_for_load_state(timeout=DEFAULT_TIMEOUT_MS)

                # 降低截图质量以提高性能
                screenshot = await page.screenshot(
                    full_page=True,
                    animations="disabled",
                    type="jpeg",
                    quality=SCREENSHOT_QUALITY,
                )

                screenshot = base64.b64encode(screenshot).decode("utf-8")

                # Build the state info with all required fields
                state_info = {
                    "url": state.url,
                    "title": state.title,
                    "tabs": [tab.model_dump() for tab in state.tabs],
                    "help": "[0], [1], [2], etc., represent clickable indices corresponding to the elements listed. Clicking on these indices will navigate to or interact with the respective content behind them.",
                    "interactive_elements": (
                        state.element_tree.clickable_elements_to_string()
                        if state.element_tree
                        else ""
                    ),
                    "scroll_info": {
                        "pixels_above": getattr(state, "pixels_above", 0),
                        "pixels_below": getattr(state, "pixels_below", 0),
                        "total_height": getattr(state, "pixels_above", 0)
                        + getattr(state, "pixels_below", 0)
                        + viewport_height,
                    },
                    "viewport_height": viewport_height,
                }

                return ToolResult(
                    output=json.dumps(state_info, indent=4, ensure_ascii=False),
                    base64_image=screenshot,
                )
            except Exception as e:
                return ToolResult(error=f"Failed to get browser state: {str(e)}")

    async def cleanup(self):
        """Clean up browser resources."""
        async with self.locks["cleanup"]:
            try:
                if self.context is not None:
                    logger.info("正在清理浏览器上下文资源...")
                    await self.context.close()
                    self.context = None
                    self.dom_service = None
                if self.browser is not None:
                    logger.info("正在关闭浏览器...")
                    await self.browser.close()
                    self.browser = None
                logger.info("浏览器资源清理完成")
            except Exception as e:
                logger.error(f"清理浏览器资源时出错: {str(e)}")

    def __del__(self):
        """Ensure cleanup when object is destroyed."""
        if self.browser is not None or self.context is not None:
            try:
                # 不要使用asyncio.run，它可能导致运行时错误
                logger.info("对象被销毁，尝试清理浏览器资源...")
                loop = (
                    asyncio.get_event_loop()
                    if asyncio.get_event_loop().is_running()
                    else asyncio.new_event_loop()
                )
                if not loop.is_closed():
                    loop.create_task(self.cleanup())
            except Exception as e:
                logger.error(f"析构函数中清理资源时出错: {str(e)}")

    @classmethod
    def create_with_context(cls, context: Context) -> "BrowserUseTool[Context]":
        """Factory method to create a BrowserUseTool with a specific context."""
        tool = cls()
        tool.tool_context = context
        return tool
