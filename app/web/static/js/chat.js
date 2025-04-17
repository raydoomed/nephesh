// Configure axios default URL
axios.defaults.baseURL = window.location.origin;  // Use the current page's origin as the base URL

// 使用ES模块语法导入mathProcessor
import mathProcessor from '../../utils/mathProcessor.js';

// 导入必要的Vue API
const { shallowRef } = Vue;

// 创建消息处理器模块
const messageHandler = {
    // 开始打字效果
    startTypingEffect(app, message) {
        // 如果有正在进行的打字效果，停止它
        if (app.typingTimer) {
            clearInterval(app.typingTimer);
            app.typingTimer = null;
        }

        // 初始化打字效果
        app.typingInProgress = true;
        app.currentTypingMessage = message;
        app.typingText = '';
        app.typingIndex = 0;

        const content = message.content || '';

        // 开始打字效果
        app.typingTimer = setInterval(() => {
            if (app.typingIndex < content.length) {
                app.typingText += content[app.typingIndex];
                app.typingIndex++;

                // 每次添加新字符后，立即应用渲染和代码高亮
                app.$nextTick(() => {
                    // 在每个字符添加后应用代码高亮
                    this.applyCodeHighlighting();
                    // 滚动到底部以显示最新内容
                    app.scrollToBottom();
                });
            } else {
                this.completeTypingEffect(app);
            }
        }, app.typingSpeed);
    },

    // 完成打字效果
    completeTypingEffect(app) {
        if (app.typingTimer) {
            clearInterval(app.typingTimer);
            app.typingTimer = null;
        }

        if (app.currentTypingMessage) {
            app.currentTypingMessage.content = app.currentTypingMessage.content || '';
            app.typingText = app.currentTypingMessage.content;
        }

        app.typingInProgress = false;
        app.currentTypingMessage = null;

        // 最终滚动确保所有内容都可见
        app.$nextTick(() => {
            // 滚动两个面板到底部
            app.scrollToBottom();

            // 确保工具消息容器滚动到底部
            if (app.$refs.toolMessagesContainer) {
                const container = app.$refs.toolMessagesContainer.querySelector('.column-content');
                if (container) {
                    container.scrollTop = container.scrollHeight;
                }
            }
        });
    },

    // 处理接收到的消息
    processMessages(app, newMessages, completed = false) {
        for (const msg of newMessages) {
            // 检查错误
            if (msg.error) {
                this.showError(app, msg.error);
                continue;
            }

            // 跳过用户消息，因为我们已经在顶部区域显示了用户消息
            if (msg.role === 'user') {
                continue;
            }

            // 确保消息对象包含必要的属性
            const messageObj = {
                ...msg,
                time: new Date()
            };

            // 根据后端的角色和类型进行处理
            if (messageObj.role === 'assistant') {
                // 如果是助手消息，删除任何潜在的工具名称
                delete messageObj.name;

                // 如果助手消息包含工具调用，创建一个新的工具消息以在工具输出区域显示
                if (messageObj.tool_calls && messageObj.tool_calls.length > 0) {
                    for (const toolCall of messageObj.tool_calls) {
                        if (toolCall.function && toolCall.function.name) {
                            // 创建新的工具调用消息
                            const toolCallMsg = {
                                role: 'tool',
                                name: toolCall.function.name,
                                content: `工具调用参数:\n\`\`\`json\n${this.formatJson(toolCall.function.arguments)}\n\`\`\``,
                                time: new Date(),
                                class: 'tool-arguments'
                            };
                            // 直接推送到数组
                            app.messages.push(toolCallMsg);

                            // 更新已使用工具列表
                            this.updateUsedTools(app, toolCallMsg);

                            // 添加打字效果
                            this.startTypingEffect(app, toolCallMsg);
                        }
                    }
                }
            } else if (messageObj.role === 'tool') {
                // 如果是工具消息，确保正确的工具名称
                if (messageObj.base64_image) {
                    // 如果包含截图，将浏览器截图用作工具名称
                    messageObj.name = messageObj.name || '浏览器截图';
                    messageObj.class = (messageObj.class || '') + ' browser-screenshot';
                } else if (messageObj.tool_calls && messageObj.tool_calls.length > 0) {
                    // 使用工具调用中的名称
                    if (!messageObj.name && messageObj.tool_calls[0].function) {
                        messageObj.name = messageObj.tool_calls[0].function.name;
                    }
                }
            }

            // 直接推送到数组
            app.messages.push(messageObj);

            // 更新已使用工具列表
            this.updateUsedTools(app, messageObj);

            // 如果是带有内容的助手消息，应用打字机效果
            if (messageObj.role === 'assistant' && messageObj.content) {
                this.startTypingEffect(app, messageObj);
            } else if (messageObj.role === 'tool' && messageObj.content && !messageObj.base64_image && messageObj.class === 'tool-arguments') {
                // 为工具调用参数消息添加打字机效果，但排除截图消息
                this.startTypingEffect(app, messageObj);
            } else {
                // 如果不是需要打字效果的消息，直接应用渲染
                this.applyCodeHighlighting();

                // 滚动到合适的位置
                // 如果是工具消息，只滚动右侧工具消息容器
                if (messageObj.role === 'tool' && app.$refs.toolMessagesContainer) {
                    const container = app.$refs.toolMessagesContainer.querySelector('.column-content');
                    if (container) {
                        container.scrollTop = container.scrollHeight;
                    }
                } else {
                    // 否则，滚动所有消息容器
                    app.scrollToBottom();
                }
            }
        }

        // 处理完所有消息后，再次滚动到底部
        // 仅在没有打字效果时滚动
        if (!app.typingInProgress) {
            app.scrollToBottom();
        }

        // 检查是否完成
        if (app.isProcessing && completed === true) {
            app.isProcessing = false;
            app.statusText = '已连接';
            app.connectionStatus = 'connected';
            app.stopPolling(); // 这也会停止状态轮询

            // 保持步骤状态显示(不重置)
        }
    },

    // 更新已使用工具列表
    updateUsedTools(app, message) {
        // 只处理工具消息
        if (message.role === 'tool' && message.name) {
            // 检查工具是否在可用工具列表中
            const tool = app.availableTools.find(t => t.name === message.name);
            if (tool) {
                // 添加到已使用工具集合
                app.usedTools.add(message.name);

                // 更新当前使用的工具
                app.currentToolInUse = message.name;

                // 如果是终止工具，显示通知卡
                if (message.name.toLowerCase() === 'terminate' && tool.is_special) {
                    // 检查执行是否成功
                    const isSuccess = message.content && message.content.toLowerCase().includes('success');
                    // 显示任务完成通知卡
                    app.showTaskCompletionCard(isSuccess);
                }

                // 检测文件编辑工具，并自动刷新文件列表
                if (message.name === 'str_replace_editor') {
                    // 延迟刷新文件列表，确保文件写入已完成
                    setTimeout(() => {
                        app.refreshFiles();
                    }, 500);
                }
            }
        }

        // 检查工具调用中的工具
        if (message.tool_calls && message.tool_calls.length > 0) {
            for (const toolCall of message.tool_calls) {
                if (toolCall.function && toolCall.function.name) {
                    // 检查工具是否在可用工具列表中
                    const tool = app.availableTools.find(t => t.name === toolCall.function.name);
                    if (tool) {
                        // 添加到已使用工具集合
                        app.usedTools.add(toolCall.function.name);

                        // 更新当前使用的工具
                        app.currentToolInUse = toolCall.function.name;

                        // 如果是终止工具，显示通知卡
                        if (toolCall.function.name.toLowerCase() === 'terminate' && tool.is_special) {
                            // 在工具调用阶段直接显示成功通知卡，因为无法确定结果
                            app.showTaskCompletionCard(true);
                        }

                        // 检测文件编辑工具，并自动刷新文件列表
                        if (toolCall.function.name === 'str_replace_editor') {
                            // 工具调用阶段标记需要刷新文件列表，等待工具执行完毕后再刷新
                            app.needRefreshFiles = true;
                        }
                    }
                }
            }
        }

        // 如果之前标记了需要刷新文件，且当前收到了str_replace_editor的响应，则刷新文件列表
        if (app.needRefreshFiles && message.role === 'tool' && message.name === 'str_replace_editor') {
            // 延迟刷新文件列表，确保文件写入已完成
            setTimeout(() => {
                app.refreshFiles();
                app.needRefreshFiles = false;
            }, 500);
        }
    },

    // 格式化消息内容
    formatMessage(app, content) {
        if (!content) return '';

        // 获取要格式化的文本 - 要么是完整内容，要么是部分输入文本
        let textToFormat = content;
        if (app.typingInProgress &&
            app.currentTypingMessage &&
            app.currentTypingMessage.content === content) {
            // 使用当前打字文本而不是完整消息
            textToFormat = app.typingText;
        }

        // 预处理：将[...]格式的数学公式转换为$$...$$格式
        // 修改为使用ES模块导入的mathProcessor
        try {
            // 使用导入的mathProcessor模块
            textToFormat = mathProcessor.preprocessMathFormulas(textToFormat);
        } catch (error) {
            console.error('处理数学公式时出错:', error);
        }

        // 使用markdown-it将Markdown转换为HTML，并添加优化配置
        const md = window.markdownit({
            html: true,          // 允许HTML标签
            linkify: true,       // 自动转换URL为链接
            typographer: true,   // 启用一些语言中立的替换和引号
            highlight: function (str, lang) {
                // 使用Prism进行代码高亮
                if (lang && Prism.languages[lang]) {
                    try {
                        return Prism.highlight(str, Prism.languages[lang], lang);
                    } catch (__) { }
                }
                return ''; // 使用默认的外部高亮工具
            }
        });

        // 渲染Markdown为HTML
        const html = md.render(textToFormat);
        return html;
    },

    // 应用代码高亮
    applyCodeHighlighting() {
        // 使用Prism.js重新应用代码高亮
        Prism.highlightAll();

        // 使用MathJax渲染数学公式
        try {
            // 如果MathJax已加载，则执行公式处理
            if (window.MathJax) {
                // 判断MathJax版本并使用正确的API
                if (window.MathJax.version && window.MathJax.version[0] === '3') {
                    // MathJax v3 API
                    window.MathJax.typeset && window.MathJax.typeset();
                } else {
                    // MathJax v2 API
                    window.MathJax.Hub && window.MathJax.Hub.Queue(["Typeset", window.MathJax.Hub]);
                }
            }
        } catch (e) {
            console.warn('渲染数学公式时出错:', e);
        }
    },

    // 格式化JSON字符串
    formatJson(jsonString) {
        try {
            if (typeof jsonString === 'string') {
                // 解析JSON字符串并美化格式
                const obj = JSON.parse(jsonString);
                return JSON.stringify(obj, null, 2);
            } else if (jsonString !== null && jsonString !== undefined) {
                // 如果已经是对象，只需美化
                return JSON.stringify(jsonString, null, 2);
            } else {
                // 如果为null或undefined，返回空字符串
                return '';
            }
        } catch (e) {
            // 如果解析失败，返回原始字符串
            console.warn('JSON解析失败:', e, jsonString);
            return jsonString || '';
        }
    },

    // 显示错误消息
    showError(app, errorMessage) {
        // 直接推送到数组
        app.messages.push({
            role: 'assistant',
            content: `发生错误: ${errorMessage}`,
            time: new Date(),
            class: 'error-message'
        });

        // 滚动到底部
        app.$nextTick(() => {
            app.scrollToBottom();
        });
    }
};

// Vue application
const app = Vue.createApp({
    delimiters: ['${', '}'],  // Custom delimiters to avoid conflicts with Flask template syntax

    // 添加配置，告诉Vue哪些标签是MathJax的自定义元素
    compilerOptions: {
        isCustomElement: tag => tag.startsWith('mjx-') || tag === 'math' || tag === 'mrow' || tag === 'mfrac' || tag === 'mi' || tag === 'mo'
    },

    data() {
        return {
            // Session state
            sessionId: null,
            isConnected: false,
            isProcessing: false,
            statusText: '未连接',
            connectionStatus: 'disconnected',

            // Gradient effect toggle
            gradientEffectEnabled: true,

            // Current tool in use
            currentToolInUse: null,

            // 标记是否需要刷新文件列表
            needRefreshFiles: false,

            // Message data - 恢复为普通响应式数组
            messages: [],
            userInput: '',

            // Polling control
            pollingInterval: null,
            pollRate: 300, // Polling interval (milliseconds)
            maxRetries: 3, // 最大重试次数
            retryCount: 0, // 重试计数器

            // Tool data
            availableTools: [],
            usedTools: new Set(),
            specialTools: [], // Empty array, will fetch special tools from the backend

            // Panel control
            isAvailableToolsOpen: false,
            isUsedToolsOpen: false,

            // File upload related
            showUploadOptions: false,
            uploadTarget: 'workspace', // 'workspace' or 'input'
            showUploadModal: false,

            // Notification related
            navbarNotification: {
                show: false,
                message: '',
                type: 'info',
                timer: null
            },

            // Central notification card
            centerNotification: {
                show: false,
                message: '',
                type: 'info',
                timer: null,
                showAction: false,
                actionType: null
            },

            // Mouse position tracking
            mouseX: 0,
            mouseY: 0,

            // Typewriter effect
            typingSpeed: 10, // Typing speed per character (ms)
            currentTypingMessage: null,
            typingInProgress: false,
            typingText: '',
            typingIndex: 0,
            typingTimer: null,

            // Image modal window
            showImageModal: false,
            modalImage: '',

            // Theme settings
            isDarkTheme: true, // Default dark theme

            // Currently active tool tab
            activeToolTab: 'available',

            // Configuration related
            showConfigPanel: false,
            currentConfigTab: 'llm',
            config: {
                llm: {
                    model: '',
                    base_url: '',
                    api_key: '',
                    max_tokens: 4096,
                    temperature: 0.0,
                    vision: {
                        model: '',
                        base_url: '',
                        api_key: '',
                        max_tokens: 4096,
                        temperature: 0.0
                    }
                },
                browser: {
                    headless: false,
                    disable_security: true,
                    extra_chromium_args: [],
                    chrome_instance_path: '',
                    wss_url: '',
                    cdp_url: '',
                    proxy: {
                        server: '',
                        username: '',
                        password: ''
                    }
                },
                search: {
                    engine: 'Google',
                    fallback_engines: ['DuckDuckGo', 'Baidu'],
                    retry_delay: 60,
                    max_retries: 3
                },
                sandbox: {
                    use_sandbox: false,
                    image: 'python:3.12-slim',
                    work_dir: '/workspace',
                    memory_limit: '1g',
                    cpu_limit: 2.0,
                    timeout: 300,
                    network_enabled: true
                },
                server: {
                    host: '127.0.0.1',
                    port: 5172
                }
            },
            configSections: {
                llm: { name: '大语言模型', icon: 'fa-comment-dots' },
                browser: { name: '浏览器', icon: 'fa-globe' },
                search: { name: '搜索引擎', icon: 'fa-search' },
                sandbox: { name: '沙箱环境', icon: 'fa-cube' },
                server: { name: '服务器', icon: 'fa-server' }
            },
            originalConfig: null,

            // Proxy settings helper variables
            proxyServerConfig: '',
            proxyUsernameConfig: '',
            proxyPasswordConfig: '',

            // Workspace files
            workspaceFiles: [],

            messagesColumnMode: 'normal',  // 'normal' or 'split'
            thoughtsVisible: false,
            currentThought: "",

            // User scroll flags
            userScrolledToolMessages: false,
            userScrolledAgentMessages: false,

            // Agent status properties
            agentStatus: {
                currentStep: 0,
                maxSteps: 0,
                status: ''
            },
            statusPollingInterval: null,

            // Event listener references
            eventListeners: {
                mouseMoveHandler: null,
                keydownHandler: null
            },

            // 添加侧边栏显示状态控制
            showSidebar: true,
        };
    },

    computed: {
        // Get the last user message
        lastUserMessage() {
            // Find the last user message
            const userMessages = this.messages.filter(msg => msg.role === 'user');
            return userMessages.length > 0 ? userMessages[userMessages.length - 1] : null;
        },

        // Filtered message list (excluding user messages)
        filteredMessages() {
            // Only return non-user messages, i.e., agent and tool messages
            return this.messages.filter(msg => msg.role !== 'user');
        },

        // Get agent message list - 使用计算属性缓存优化
        agentMessages() {
            // 使用计算缓存来减少重复计算
            return this.messages.filter(msg =>
                msg.role === 'assistant' &&
                !(msg.content === '' || msg.content === null || msg.content === undefined)
            );
        },

        // Get tool message list
        toolMessages() {
            return this.messages.filter(msg => msg.role === 'tool');
        }
    },

    mounted() {
        // Load saved theme preference
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme) {
            this.isDarkTheme = savedTheme === 'dark';
        } else {
            // Check system preference
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            this.isDarkTheme = prefersDark;
        }
        this.applyTheme();

        // Load gradient effect preference
        const savedGradientEffect = localStorage.getItem('gradientEffect');
        if (savedGradientEffect !== null) {
            this.gradientEffectEnabled = savedGradientEffect === 'true';
        }
        this.applyGradientEffectSettings();

        // Initialize session on page load
        this.createNewSession();

        // Get workspace files list
        this.refreshFiles();

        // Setup poll for messages
        this.setupMessagePolling();

        // Scroll to the bottom of the message container functionality
        this.$nextTick(() => {
            this.scrollToBottom();
        });

        // Add mouse movement tracking
        this.initMouseTracking();

        // Add keyboard shortcuts
        this.setupKeyboardShortcuts();

        // Listen for page resize, update message container scrolling
        window.addEventListener('resize', this.scrollToBottom);

        // Add message animation observer
        this.setupMessageAnimations();

        // Listen for message list changes, ensure auto-scrolling
        this.$watch('messages', () => {
            this.scrollToBottom();
        }, { deep: true }); // 改回深度监听，确保所有变化都被捕获

        // Add scroll event listener for the tool messages container
        this.$nextTick(() => {
            if (this.$refs.toolMessagesContainer) {
                const container = this.$refs.toolMessagesContainer.querySelector('.column-content');
                if (container) {
                    container.addEventListener('scroll', this.handleToolMessagesScroll);
                }
            }

            // Add scroll event listener for the agent messages container
            if (this.$refs.agentMessagesContainer) {
                const container = this.$refs.agentMessagesContainer.querySelector('.column-content');
                if (container) {
                    container.addEventListener('scroll', this.handleAgentMessagesScroll);
                }
            }
        });

        // Initialize the drag functionality for the gradient toggle button
        this.initGradientToggleDrag();

        // 添加对示例任务点击的处理
        this.$nextTick(() => {
            this.setupExampleTasksListener();
        });

        // 从本地存储加载侧边栏状态
        const savedSidebarState = localStorage.getItem('nephesh_sidebar_visible');
        if (savedSidebarState !== null) {
            this.showSidebar = savedSidebarState === 'true';
        }
    },

    methods: {
        // 使用新的消息处理模块
        startTypingEffect(message) {
            messageHandler.startTypingEffect(this, message);
        },

        completeTypingEffect() {
            messageHandler.completeTypingEffect(this);
        },

        processMessages(newMessages, completed = false) {
            messageHandler.processMessages(this, newMessages, completed);
        },

        formatMessage(content) {
            return messageHandler.formatMessage(this, content);
        },

        applyCodeHighlighting() {
            messageHandler.applyCodeHighlighting();
        },

        formatJson(jsonString) {
            return messageHandler.formatJson(jsonString);
        },

        showError(errorMessage) {
            messageHandler.showError(this, errorMessage);
        },

        updateUsedTools(message) {
            messageHandler.updateUsedTools(this, message);
        },

        // Image preview functionality
        expandImage(event) {
            this.modalImage = event.target.src;
            this.showImageModal = true;
            // Prevent scrolling
            document.body.style.overflow = 'hidden';
        },

        // Close modal window
        closeModal() {
            this.showImageModal = false;
            // Restore scrolling
            document.body.style.overflow = '';
        },

        // Theme toggle
        toggleTheme() {
            this.isDarkTheme = !this.isDarkTheme;
            this.applyTheme();

            // Update the display status of the gradient effect button
            const gradientBtn = document.getElementById('gradient-toggle-btn');
            if (gradientBtn) {
                gradientBtn.style.display = this.isDarkTheme ? 'flex' : 'none';
            }

            // Save preference to localStorage
            localStorage.setItem('theme', this.isDarkTheme ? 'dark' : 'light');
        },

        // Apply theme
        applyTheme() {
            const root = document.documentElement;
            if (this.isDarkTheme) {
                // Dark mode
                root.style.setProperty('--background-color', '#1a202c');
                root.style.setProperty('--surface-color', '#2d3748');
                root.style.setProperty('--card-color', '#2d3748');
                root.style.setProperty('--text-color', '#f7fafc');
                root.style.setProperty('--text-secondary', '#a0aec0');
                root.style.setProperty('--border-color', '#4a5568');
                document.body.classList.add('dark-theme');
                // Use logo.png in dark mode
                const logoElement = document.querySelector('.logo');
                if (logoElement) {
                    logoElement.src = '/static/images/nephesh.png';
                }

                // 检查用户偏好再应用渐变效果设置
                const savedGradientEffect = localStorage.getItem('gradientEffect');
                if (savedGradientEffect === null || savedGradientEffect === 'true') {
                    // 只有当用户未明确禁用渐变效果时才应用
                    this.applyGradientEffectSettings();
                }
            } else {
                // Light mode
                root.style.setProperty('--background-color', '#f8f9fa');
                root.style.setProperty('--surface-color', '#ffffff');
                root.style.setProperty('--card-color', '#ffffff');
                root.style.setProperty('--text-color', '#2d3748');
                root.style.setProperty('--text-secondary', '#718096');
                root.style.setProperty('--border-color', '#e2e8f0');
                document.body.classList.remove('dark-theme');
                document.body.classList.remove('gradient-disabled');

                // Use logo_black.png in light mode
                const logoElement = document.querySelector('.logo');
                if (logoElement) {
                    logoElement.src = '/static/images/nephesh.png';
                }
            }

            // Update Meta theme color
            const metaThemeColor = document.querySelector('meta[name="theme-color"]');
            if (metaThemeColor) {
                metaThemeColor.setAttribute('content', this.isDarkTheme ? '#0c1426' : '#ffffff');
            }
        },

        // Initialize mouse tracking functionality
        initMouseTracking() {
            // Create handler function and save reference
            this.eventListeners.mouseMoveHandler = (e) => {
                this.mouseX = e.clientX;
                this.mouseY = e.clientY;

                // Update card radiation gradient position
                const panels = document.querySelectorAll('.tools-panel, .session-panel, .info-panel');
                panels.forEach(panel => {
                    const rect = panel.getBoundingClientRect();
                    const x = Math.floor(((e.clientX - rect.left) / rect.width) * 100);
                    const y = Math.floor(((e.clientY - rect.top) / rect.height) * 100);

                    if (x >= 0 && x <= 100 && y >= 0 && y <= 100) {
                        panel.style.setProperty('--x', `${x}%`);
                        panel.style.setProperty('--y', `${y}%`);
                    }
                });
            };

            // Add event listener
            document.addEventListener('mousemove', this.eventListeners.mouseMoveHandler);
        },

        // Set up keyboard shortcuts
        setupKeyboardShortcuts() {
            // Create handler function and save reference
            this.eventListeners.keydownHandler = (e) => {
                // Escape key: stop typewriter effect or close image modal
                if (e.key === 'Escape') {
                    if (this.typingInProgress) {
                        this.completeTypingEffect();
                    }
                    if (this.showImageModal) {
                        this.closeModal();
                    }
                }

                // Press Ctrl+Enter to send message
                if (e.key === 'Enter' && e.ctrlKey) {
                    this.sendMessage();
                }

                // Press T key to toggle theme (when not in input area)
                if (e.key === 't' && document.activeElement.tagName !== 'TEXTAREA' && document.activeElement.tagName !== 'INPUT') {
                    this.toggleTheme();
                }
            };

            // Add event listener
            document.addEventListener('keydown', this.eventListeners.keydownHandler);
        },

        // Create a new session
        async createNewSession() {
            try {
                // If there's an active session, terminate it first
                if (this.sessionId) {
                    await this.terminateSession();
                }

                // Reset state
                this.stopPolling();
                this.isProcessing = false;
                // Reset user scroll flags
                this.userScrolledToolMessages = false;
                this.userScrolledAgentMessages = false;

                // Reset step status
                this.agentStatus = {
                    currentStep: 0,
                    maxSteps: 0,
                    status: ''
                };

                console.log('创建新会话...');
                const response = await axios.post('/api/session');
                console.log('会话创建响应:', response.data);

                this.sessionId = response.data.session_id;
                this.isConnected = true;
                this.statusText = '已连接';
                this.connectionStatus = 'connected';
                this.messages = [];
                this.usedTools = new Set(); // Reset used tools list

                // Reset panel state
                this.isAvailableToolsOpen = false;
                this.isUsedToolsOpen = false;
                this.currentToolInUse = null;

                // Get available tools list
                this.fetchAvailableTools();

                // 添加welcome message和工具箱
                const welcomeMessage = {
                    role: 'assistant',
                    content: `<div class="welcome-header">
<div class="nephesh-header-bg"></div>
<img src="/static/images/nephesh.png" alt="Nephesh Logo" class="welcome-logo">
<h1 class="welcome-title">你好！我是 Nephesh</h1>

<p style="position: relative; z-index: 2;">我可以帮助你完成各种任务。以下是我的一些核心能力：</p>
</div>

<style>
.welcome-header {
  text-align: center;
  margin-bottom: 20px;
  max-width: 100%;
  position: relative;
  overflow: hidden;
  border-radius: 12px;
  padding: 20px;
}

/* 深色模式样式 */
.dark-theme .welcome-header {
  background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%);
  box-shadow: 0 10px 25px rgba(0,0,0,0.15);
  animation: darkPulseShadow 5s infinite alternate;
}

@keyframes darkPulseShadow {
  0% { box-shadow: 0 10px 25px rgba(0,0,0,0.15); }
  100% { box-shadow: 0 15px 35px rgba(66, 153, 225, 0.2); }
}

/* 浅色模式样式 */
body:not(.dark-theme) .welcome-header {
  background: linear-gradient(135deg, #f8f9fa 0%, #e2e8f0 100%);
  box-shadow: 0 10px 25px rgba(0,0,0,0.07);
  animation: lightPulseShadow 5s infinite alternate;
}

@keyframes lightPulseShadow {
  0% { box-shadow: 0 10px 25px rgba(0,0,0,0.07); }
  100% { box-shadow: 0 15px 35px rgba(66, 153, 225, 0.15); }
}

.nephesh-header-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1;
  animation: moveBg 15s infinite alternate ease-in-out;
}

/* 深色模式背景 */
.dark-theme .nephesh-header-bg {
  background:
    radial-gradient(circle at 20% 30%, rgba(66, 153, 225, 0.15) 0%, transparent 50%),
    radial-gradient(circle at 80% 70%, rgba(237, 100, 166, 0.1) 0%, transparent 50%);
}

/* 浅色模式背景 */
body:not(.dark-theme) .nephesh-header-bg {
  background:
    radial-gradient(circle at 20% 30%, rgba(66, 153, 225, 0.25) 0%, transparent 60%),
    radial-gradient(circle at 80% 70%, rgba(237, 100, 166, 0.15) 0%, transparent 60%);
}

@keyframes moveBg {
  0% { transform: scale(1) rotate(0deg); opacity: 0.7; }
  100% { transform: scale(1.2) rotate(5deg); opacity: 1; }
}

.welcome-logo {
  width: 80px;
  height: 80px;
  margin-bottom: 0;
  position: relative;
  z-index: 2;
}

/* 深色模式Logo */
.dark-theme .welcome-logo {
  filter: drop-shadow(0 0 8px rgba(66, 153, 225, 0.5));
}

/* 浅色模式Logo */
body:not(.dark-theme) .welcome-logo {
  filter: drop-shadow(0 0 10px rgba(66, 153, 225, 0.3));
}

.welcome-title {
  margin-top: 5px;
  font-size: 2em;
  margin-bottom: 12px;
  font-weight: 600;
  position: relative;
  z-index: 2;
}

/* 深色模式标题 */
.dark-theme .welcome-title {
  background: linear-gradient(90deg, #63b3ed 0%, #ed64a6 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  text-shadow: 0 2px 10px rgba(0,0,0,0.1);
}

/* 浅色模式标题 */
body:not(.dark-theme) .welcome-title {
  background: linear-gradient(90deg, #3182ce 0%, #d53f8c 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  text-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.welcome-subtitle {
  font-size: 1.1em;
  margin-top: 10px;
  position: relative;
  z-index: 2;
}

/* 深色模式副标题 */
.dark-theme .welcome-subtitle {
  color: var(--text-secondary);
}

/* 浅色模式副标题 */
body:not(.dark-theme) .welcome-subtitle {
  color: #4a5568;
}
</style>

<div class="welcome-tools-container">
  <div class="welcome-tools-wrapper">
    <div class="welcome-tool-item"><span class="welcome-tool-icon">📊</span> <strong>数据分析</strong> - 处理Excel、CSV等表格数据，生成各类图表，数据可视化，提供深度分析报告</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">📝</span> <strong>文档创建</strong> - 生成专业报告，撰写文章，编辑各类文本内容，支持多种格式输出</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">🖼️</span> <strong>图像生成</strong> - 根据描述创建高质量图像，编辑照片，设计图形，生成图表和信息图</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">📑</span> <strong>PDF处理</strong> - 创建专业PDF报告，提取PDF内容，格式转换，添加水印和注释</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">🎯</span> <strong>PPT制作</strong> - 创建精美演示文稿，设计专业幻灯片，生成图表和动画效果</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">💻</span> <strong>代码编写</strong> - 编写Python、JavaScript等多种语言代码，调试问题，优化性能</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">🔍</span> <strong>网络搜索</strong> - 查询最新信息，搜索学术资料，寻找解决方案，获取实时数据</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">🌐</span> <strong>网页浏览</strong> - 访问网站，获取信息，分析网页内容，提取关键数据</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">📧</span> <strong>邮件助手</strong> - 起草专业邮件，回复消息，管理邮件模板，生成回复建议</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">🧮</span> <strong>数学计算</strong> - 解决复杂数学问题，进行高级计算，绘制函数图像，统计分析</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">📊</span> <strong>数据分析</strong> - 处理Excel、CSV等表格数据，生成各类图表，数据可视化，提供深度分析报告</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">📝</span> <strong>文档创建</strong> - 生成专业报告，撰写文章，编辑各类文本内容，支持多种格式输出</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">🖼️</span> <strong>图像生成</strong> - 根据描述创建高质量图像，编辑照片，设计图形，生成图表和信息图</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">📑</span> <strong>PDF处理</strong> - 创建专业PDF报告，提取PDF内容，格式转换，添加水印和注释</div>
    <div class="welcome-tool-item"><span class="welcome-tool-icon">🎯</span> <strong>PPT制作</strong> - 创建精美演示文稿，设计专业幻灯片，生成图表和动画效果</div>
  </div>
</div>

<style>
.welcome-tools-container {
  height: 34px;
  overflow: hidden;
  margin: 10px 0;
  white-space: nowrap;
  border-radius: 6px;
  position: relative;
  mask-image: linear-gradient(to right, transparent, black 5%, black 95%, transparent);
  -webkit-mask-image: linear-gradient(to right, transparent, black 5%, black 95%, transparent);
}

.welcome-tools-wrapper {
  display: flex;
  flex-wrap: nowrap;
  height: 34px;
  animation: welcomeScrollLeftContinuous 30s linear infinite;
}

@keyframes welcomeScrollLeftContinuous {
  0% { transform: translateX(0); }
  100% { transform: translateX(-200%); }
}

.welcome-tool-item {
  flex: 0 0 auto;
  background-color: rgba(230, 235, 250, 0.3);
  border-radius: 6px;
  padding: 5px 10px;
  margin-right: 10px;
  transition: transform 0.2s ease;
  display: inline-flex;
  align-items: center;
  font-size: 0.9em;
  height: 24px;
  line-height: 24px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.dark-theme .welcome-tool-item {
  background-color: #1A202C;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  color: rgba(255, 255, 255, 0.9);
}

.dark-theme .welcome-tool-item:hover {
  transform: translateY(-2px);
  background-color: #2D3748;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
}

.welcome-tool-icon {
  margin-right: 5px;
}

.welcome-tool-item:hover {
  transform: translateY(-2px);
  background-color: rgba(230, 235, 250, 0.5);
}

.welcome-tools-examples {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  list-style-type: none;
  padding: 0;
  margin: 15px 0;
}

.welcome-tools-examples li {
  background-color: rgba(240, 240, 250, 0.5);
  padding: 8px 12px;
  border-radius: 16px;
  display: inline-block;
  font-size: 0.8em;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  cursor: pointer;
}

.dark-theme .welcome-tools-examples li {
  background-color: #1A202C;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  color: rgba(255, 255, 255, 0.9);
}

.dark-theme .welcome-tools-examples li:hover {
  background-color: #2D3748;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
}

.welcome-tools-examples li:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
  background-color: rgba(240, 240, 250, 0.8);
}
</style>

<h5 style="font-size: 0.85rem; margin-top: 15px; margin-bottom: 10px; font-weight: 600; display: flex; align-items: center;">
  <span style="font-size: 0.85rem;">💡</span>
  <span style="margin-left: 5px;">示例任务</span>
</h5>

<ul class="welcome-tools-examples">
  <li>📈 帮我分析这个Excel数据并生成趋势图表</li>
  <li>📄 创建一个关于气候变化的详细PDF报告</li>
  <li>🎨 为我的产品演示设计专业PPT，要有动画效果</li>
  <li>⚙️ 编写一个Python爬虫程序获取新闻数据</li>
  <li>🎭 生成一张未来城市科技风格的高清图像</li>
  <li>🔢 帮我解决这个微积分方程：$\\frac{d}{dx}(x^2\\sin(x))$</li>
  <li>✉️ 帮我写一封商务邮件给客户</li>
  <li>🔎 查询最近关于人工智能的学术研究</li>
</ul>

<div class="welcome-message-footer">
你可以直接告诉我你需要什么帮助，或者上传文件让我协助处理。
<div class="welcome-message-tips">提示：点击右上角的"上传"按钮可以上传文件给我处理</div>
</div>

<style>
.welcome-message-footer {
  margin-top: 20px;
  padding: 10px;
  border-radius: 8px;
  background-color: rgba(220, 230, 250, 0.5);
  text-align: center;
}

/* 深色模式下的welcome-message-footer样式 */
.dark-theme .welcome-message-footer {
  background-color: #1A202C;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.welcome-message-tips {
  margin-top: 5px;
  font-size: 0.85em;
  opacity: 0.8;
}
</style>`,
                    time: new Date()
                };

                this.messages.push(welcomeMessage);

                // 不使用打字效果，直接显示完整的欢迎消息
                // 原来的代码：
                // this.$nextTick(() => {
                //     this.startTypingEffect(welcomeMessage);
                // });

                // 更新DOM并滚动到底部
                this.$nextTick(() => {
                    this.scrollToBottom();
                    this.applyCodeHighlighting();
                });

                console.log(`新会话创建成功，ID: ${this.sessionId}`);
            } catch (error) {
                console.error('创建会话失败:', error);

                // Display more detailed error information
                let errorMsg = '无法创建新会话，请稍后重试。';
                if (error.response) {
                    errorMsg += ` 状态码: ${error.response.status}`;
                    if (error.response.data && error.response.data.error) {
                        errorMsg += ` - ${error.response.data.error}`;
                    }
                } else if (error.request) {
                    errorMsg += ' 服务器没有响应，请检查您的网络连接。';
                } else {
                    errorMsg += ` 错误信息: ${error.message}`;
                }

                this.showError(errorMsg);
            }
        },

        // Get available tools list
        async fetchAvailableTools() {
            try {
                const response = await axios.get(`/api/tools/${this.sessionId}`);
                if (response.data && response.data.tools) {
                    this.availableTools = response.data.tools;

                    // Get special tools list from backend
                    this.specialTools = this.availableTools
                        .filter(tool => tool.is_special)
                        .map(tool => tool.name);

                    console.log('特殊工具:', this.specialTools);

                    // Add tool loading animation
                    this.animateToolsAppearance();
                }
            } catch (error) {
                console.error('获取工具列表失败:', error);
                // Don't set default tools list, completely rely on backend data
                this.availableTools = [];
                this.specialTools = [];
            }
        },

        // Tools list loading animation
        animateToolsAppearance() {
            this.$nextTick(() => {
                const toolItems = document.querySelectorAll('.tool-item');
                toolItems.forEach((item, index) => {
                    item.style.opacity = '0';
                    item.style.transform = 'translateY(10px)';
                    item.style.transition = 'opacity 0.3s ease, transform 0.3s ease';

                    setTimeout(() => {
                        item.style.opacity = '1';
                        item.style.transform = 'translateY(0)';
                    }, 100 + (index * 50));
                });
            });
        },

        // Send message to the server
        async sendMessage() {
            if (!this.userInput.trim() || !this.sessionId || this.isProcessing) {
                return;
            }

            const userMessage = this.userInput.trim();

            // Clear all previous user messages, only keep the last one
            this.messages = this.messages.filter(msg => msg.role !== 'user');

            // Add new user message
            const userMessageObj = {
                role: 'user',
                content: userMessage,
                time: new Date()
            };

            // Save as last user message for task display
            this.lastUserMessage = userMessageObj;

            // Add message to array
            this.messages.push(userMessageObj);

            // Reset input
            this.userInput = '';

            // Reset user scroll flags, allowing the containers to start auto-scrolling
            this.userScrolledToolMessages = false;
            this.userScrolledAgentMessages = false;

            // Scroll to the bottom
            this.$nextTick(() => {
                this.scrollToBottom();
            });

            // Reset step status and start polling
            this.agentStatus = {
                currentStep: 0,
                maxSteps: 0,
                status: ''
            };
            this.startStatusPolling();

            try {
                // Start processing state
                this.isProcessing = true;
                this.statusText = '处理中...';
                this.connectionStatus = 'processing';

                // Send message to server
                console.log(`发送消息到: ${axios.defaults.baseURL}/api/chat`);
                console.log(`会话 ID: ${this.sessionId}`);
                const response = await axios.post('/api/chat', {
                    session_id: this.sessionId,
                    message: userMessage
                });

                console.log('服务器响应:', response.data);

                // Start message polling
                this.startPolling();
            } catch (error) {
                console.error('发送消息时出错:', error);
                this.isProcessing = false;
                this.statusText = '错误';
                this.connectionStatus = 'error';

                // Display more detailed error information
                let errorMsg = '发送消息失败，请重试。';
                if (error.response) {
                    // Server returned an error status code
                    errorMsg += ` 状态码: ${error.response.status}`;
                    if (error.response.data && error.response.data.error) {
                        errorMsg += ` - ${error.response.data.error}`;
                    }
                } else if (error.request) {
                    // Request was sent but no response received
                    errorMsg += ' 服务器没有响应，请检查您的网络连接。';
                } else {
                    // Error during request setup
                    errorMsg += ` 错误信息: ${error.message}`;
                }

                this.showError(errorMsg);

                // Stop polling
                this.stopPolling();
            }
        },

        // Initialize message polling system
        setupMessagePolling() {
            // If polling is already set up, stop it first
            if (this.pollingInterval) {
                this.stopPolling();
            }

            // 重置重试计数器
            this.retryCount = 0;

            // Only start polling if we have a valid session and are in processing state
            if (this.sessionId && this.isProcessing) {
                this.startPolling();
            }
        },

        // Start polling for messages
        startPolling() {
            if (this.pollingInterval) {
                clearInterval(this.pollingInterval);
            }

            // 使用实例属性而不是局部变量，以便在多次调用间保持状态
            this.retryCount = 0;

            this.pollingInterval = setInterval(async () => {
                try {
                    if (!this.sessionId) {
                        this.stopPolling();
                        return;
                    }

                    const response = await axios.get(`/api/messages/${this.sessionId}`);

                    // Reset retry counter
                    this.retryCount = 0;

                    // Process new messages
                    if (response.data.messages && response.data.messages.length > 0) {
                        this.processMessages(response.data.messages, response.data.completed);
                    }

                    // If processing is complete, stop polling
                    if (response.data.completed) {
                        this.stopPolling();
                        this.isProcessing = false;
                        this.statusText = '已连接';
                        this.connectionStatus = 'connected';
                    }
                } catch (error) {
                    console.error('获取消息失败:', error);
                    this.retryCount++;

                    if (this.retryCount >= this.maxRetries) {
                        this.stopPolling();
                        this.isProcessing = false;
                        this.statusText = '已连接';
                        this.connectionStatus = 'connected';

                        // Display more detailed error information
                        let errorMsg = `轮询消息失败 (已重试 ${this.retryCount} 次)`;
                        if (error.response) {
                            errorMsg += ` 状态码: ${error.response.status}`;
                            if (error.response.data && error.response.data.error) {
                                errorMsg += ` - ${error.response.data.error}`;
                            }
                        } else if (error.request) {
                            errorMsg += ' 服务器没有响应';
                        } else {
                            errorMsg += ` 错误: ${error.message}`;
                        }

                        this.showError(errorMsg);
                    }
                }
            }, this.pollRate);
        },

        // Stop polling
        stopPolling() {
            if (this.pollingInterval) {
                clearInterval(this.pollingInterval);
                this.pollingInterval = null;
            }

            // Also stop status polling
            this.stopStatusPolling();
        },

        // Show task completion notification card (with eye animation)
        showTaskCompletionCard(isSuccess) {
            // Create notification message for the terminate tool
            const message = isSuccess ?
                '会话成功终止！<br>您现在可以创建一个新会话' :
                '会话终止失败<br>请重试';

            // Show notification card
            this.showCenterNotification(
                `<div class="task-completion-card">
                    <div class="eyes-animation">
                        <div class="eye left-eye"></div>
                        <div class="eye right-eye"></div>
                    </div>
                    <div class="task-message">${message}</div>
                </div>`,
                isSuccess ? 'success' : 'error',
                { duration: 5000 }
            );
        },

        // Format time
        formatTime(time) {
            if (!time) return '';

            const date = new Date(time);
            const hours = date.getHours().toString().padStart(2, '0');
            const minutes = date.getMinutes().toString().padStart(2, '0');
            const seconds = date.getSeconds().toString().padStart(2, '0');

            return `${hours}:${minutes}:${seconds}`;
        },

        // Scroll to bottom of message container
        scrollToBottom() {
            this.$nextTick(() => {
                // Scroll the agent messages container
                if (this.$refs.agentMessagesContainer) {
                    const container = this.$refs.agentMessagesContainer.querySelector('.column-content');
                    if (!container) return;

                    // Only auto-scroll if there's no streaming in progress or user hasn't manually scrolled
                    if (!this.typingInProgress || !this.userScrolledAgentMessages) {
                        // Use more reliable scrolling method
                        container.scrollTop = container.scrollHeight;
                    }
                }

                // Scroll the tool messages container
                if (this.$refs.toolMessagesContainer && !this.typingInProgress && !this.userScrolledToolMessages) {
                    const container = this.$refs.toolMessagesContainer.querySelector('.column-content');
                    if (!container) return;

                    // Use more reliable scrolling method
                    container.scrollTop = container.scrollHeight;
                }
            });
        },

        // Handle tool messages container scroll event
        handleToolMessagesScroll(event) {
            if (!this.$refs.toolMessagesContainer) return;

            const container = this.$refs.toolMessagesContainer.querySelector('.column-content');
            if (!container) return;

            // Calculate if at the bottom (allow for some tolerance)
            const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 10;

            // If not at the bottom, mark as user has manually scrolled
            // Only change the flag when we're actively streaming content
            if (!atBottom && this.typingInProgress) {
                this.userScrolledToolMessages = true;
            }

            // When user scrolls back to the bottom, reset the flag
            if (atBottom) {
                this.userScrolledToolMessages = false;
            }
        },

        // Handle agent messages container scroll event
        handleAgentMessagesScroll(event) {
            if (!this.$refs.agentMessagesContainer) return;

            const container = this.$refs.agentMessagesContainer.querySelector('.column-content');
            if (!container) return;

            // Calculate if at the bottom (allow for some tolerance)
            const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 10;

            // If not at the bottom, mark as user has manually scrolled
            // Only change the flag when we're actively streaming content
            if (!atBottom && this.typingInProgress) {
                this.userScrolledAgentMessages = true;
            }

            // When user scrolls back to the bottom, reset the flag
            if (atBottom) {
                this.userScrolledAgentMessages = false;
            }
        },

        // Set up message animations
        setupMessageAnimations() {
            // Use IntersectionObserver to watch for elements entering viewport
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        // When element enters viewport, add display animation
                        entry.target.classList.add('visible');
                        // Element is displayed, no longer needs observing
                        observer.unobserve(entry.target);
                    }
                });
            }, {
                threshold: 0.1 // Trigger when 10% of element is visible
            });

            // Update agent message animations
            this.$watch('agentMessages', () => {
                this.$nextTick(() => {
                    if (this.$refs.agentMessagesContainer) {
                        const messages = this.$refs.agentMessagesContainer.querySelectorAll('.message');
                        if (messages.length > 0) {
                            const lastMessage = messages[messages.length - 1];
                            observer.observe(lastMessage);
                        }
                    }
                });
            }, { deep: true });

            // Update tool message animations
            this.$watch('toolMessages', () => {
                this.$nextTick(() => {
                    if (this.$refs.toolMessagesContainer) {
                        const messages = this.$refs.toolMessagesContainer.querySelectorAll('.message');
                        if (messages.length > 0) {
                            const lastMessage = messages[messages.length - 1];
                            observer.observe(lastMessage);
                        }
                    }
                });
            }, { deep: true });
        },

        // Open/close config panel
        toggleConfigPanel() {
            if (!this.showConfigPanel) {
                // Load configuration before opening
                this.fetchConfig();
            }
            this.showConfigPanel = !this.showConfigPanel;
        },

        // Get configuration from server
        async fetchConfig() {
            try {
                const response = await axios.get('/api/config');
                if (response.data && response.data.config) {
                    this.config = response.data.config;

                    // Set proxy-related helper variables
                    if (this.config.browser && this.config.browser.proxy) {
                        this.proxyServerConfig = this.config.browser.proxy.server || '';
                        this.proxyUsernameConfig = this.config.browser.proxy.username || '';
                        this.proxyPasswordConfig = this.config.browser.proxy.password || '';
                    }

                    // Save original configuration for reset
                    this.originalConfig = JSON.parse(JSON.stringify(this.config));
                }
            } catch (error) {
                console.error('获取配置失败:', error);
                this.showError('获取配置信息失败，请检查网络连接或服务器状态');
            }
        },

        // Save configuration to server
        async saveConfig() {
            try {
                // Process proxy configuration
                if (this.config.browser) {
                    if (!this.config.browser.proxy) {
                        this.config.browser.proxy = {};
                    }

                    this.config.browser.proxy.server = this.proxyServerConfig;
                    this.config.browser.proxy.username = this.proxyUsernameConfig;
                    this.config.browser.proxy.password = this.proxyPasswordConfig;
                }

                const response = await axios.post('/api/config', {
                    config: this.config
                });

                if (response.data && response.data.status === 'success') {
                    // Update original configuration
                    this.originalConfig = JSON.parse(JSON.stringify(this.config));

                    // Display different messages based on hot reload status
                    const reloadSuccess = response.data.reload_success === true;
                    const serverConfigChanged = response.data.server_config_changed === true;

                    // Close config panel
                    this.showConfigPanel = false;

                    let messageContent = '';
                    let notificationType = '';
                    let notificationOptions = { duration: 5000 };

                    if (reloadSuccess) {
                        if (serverConfigChanged) {
                            messageContent = `配置已成功保存！但是，服务器地址或端口已更改，需要重启才能生效。`;
                            notificationType = 'warning';
                            notificationOptions.showAction = true;
                            notificationOptions.actionType = 'restart';
                            notificationOptions.duration = null; // Not automatically closed
                        } else {
                            messageContent = `配置已成功更新，将自动创建新会话以应用新配置...`;
                            notificationType = 'success';
                        }
                    } else {
                        messageContent = `配置已成功保存，但热重载失败。某些更改可能需要重启服务器才能生效。`;
                        notificationType = 'warning';
                        notificationOptions.showAction = true;
                        notificationOptions.actionType = 'restart';
                        notificationOptions.duration = null; // Not automatically closed
                    }

                    // Show central notification card
                    this.showCenterNotification(messageContent, notificationType, notificationOptions);

                    // Show message
                    this.messages.push({
                        role: 'system',
                        content: messageContent,
                        time: Date.now()
                    });

                    // If configuration is successfully reloaded and server configuration is not changed, automatically create a new session
                    if (reloadSuccess && !serverConfigChanged) {
                        // Automatically create a new session
                        this.$nextTick(() => {
                            this.createNewSession();
                        });
                    }

                    this.scrollToBottom();
                }
            } catch (error) {
                console.error('保存配置失败:', error);
                this.showError('保存配置失败: ' + (error.response?.data?.error || error.message));
            }
        },

        // Show central notification card
        showCenterNotification(message, type = 'info', options = {}) {
            // Clear previous timer
            if (this.centerNotification.timer) {
                clearTimeout(this.centerNotification.timer);
            }

            // Set new notification
            this.centerNotification.message = message;
            this.centerNotification.type = type;
            this.centerNotification.show = true;

            // Set action button
            this.centerNotification.showAction = !!options.showAction;
            this.centerNotification.actionType = options.actionType || null;

            // Set auto-hide (if specified)
            if (options.duration) {
                this.centerNotification.timer = setTimeout(() => {
                    this.closeCenterNotification();
                }, options.duration);
            }
        },

        // Close central notification card
        closeCenterNotification() {
            this.centerNotification.show = false;
        },

        // Restart server (placeholder method)
        restartServer() {
            this.closeCenterNotification();
            // This is a placeholder, the actual implementation may need to call the backend API
            this.showCenterNotification('服务器重启命令已发送，请等待服务恢复...', 'info', { duration: 3000 });
        },

        // Show notification (adapter method for backward compatibility)
        showNotification(message, type = 'info') {
            this.showCenterNotification(message, type, { duration: 3000 });
        },

        // Reset configuration to state at load time
        resetConfig() {
            if (this.originalConfig) {
                this.config = JSON.parse(JSON.stringify(this.originalConfig));

                // Reset proxy-related helper variables
                if (this.config.browser && this.config.browser.proxy) {
                    this.proxyServerConfig = this.config.browser.proxy.server || '';
                    this.proxyUsernameConfig = this.config.browser.proxy.username || '';
                    this.proxyPasswordConfig = this.config.browser.proxy.password || '';
                }
            }
        },

        // Workspace files related methods
        async refreshFiles() {
            try {
                const response = await axios.get('/api/files');
                if (response.data && response.data.files) {
                    this.workspaceFiles = response.data.files;
                    this.showNotification('文件列表已更新', 'success');
                }
            } catch (error) {
                console.error('获取工作区文件失败:', error);
                this.showError('获取文件列表失败，请检查网络连接或服务器状态');
            }
        },

        downloadFile(filePath) {
            // Create a hidden a tag for download
            const downloadLink = document.createElement('a');
            downloadLink.href = `/api/files/${filePath}`;
            downloadLink.target = '_blank';
            downloadLink.download = filePath.split('/').pop();

            // Add to DOM, trigger click, then remove
            document.body.appendChild(downloadLink);
            downloadLink.click();
            document.body.removeChild(downloadLink);

            this.showNotification(`正在下载: ${filePath}`, 'info');
        },

        // Delete file
        async deleteFile(filePath) {
            try {
                if (!confirm(`确定要删除文件"${filePath}"吗？此操作无法撤销。`)) {
                    return;
                }

                const response = await axios.delete(`/api/files/${filePath}`);

                if (response.data && response.data.message) {
                    this.showNotification(response.data.message, 'success');
                    // Refresh file list
                    this.refreshFiles();
                }
            } catch (error) {
                console.error('删除文件失败:', error);
                this.showError(error.response?.data?.error || '删除文件失败，请稍后重试');
            }
        },

        formatFileSize(bytes) {
            if (bytes === 0) return '0 B';

            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(1024));

            return parseFloat((bytes / Math.pow(1024, i)).toFixed(2)) + ' ' + sizes[i];
        },

        // Trigger file selection dialog
        triggerFileUpload(target) {
            this.uploadTarget = target || 'workspace';
            this.showUploadModal = false; // Close modal
            this.$refs.fileInput.click();
        },

        // Toggle upload options menu
        toggleUploadOptions(event) {
            // Prevent event bubbling
            if (event) {
                event.stopPropagation();
            }

            this.showUploadOptions = !this.showUploadOptions;

            // Click outside to close menu
            if (this.showUploadOptions) {
                this.$nextTick(() => {
                    const closeMenu = (e) => {
                        if (!e.target.closest('.file-upload-dropdown')) {
                            this.showUploadOptions = false;
                            document.removeEventListener('click', closeMenu);
                        }
                    };

                    // Use setTimeout to ensure event is not triggered immediately
                    setTimeout(() => {
                        document.addEventListener('click', closeMenu);
                    }, 100);
                });
            }
        },

        // Open file upload modal
        openUploadModal() {
            this.showUploadModal = true;
            // Prevent background scrolling
            document.body.style.overflow = 'hidden';
        },

        // Close file upload modal
        closeUploadModal() {
            this.showUploadModal = false;
            // Restore background scrolling
            document.body.style.overflow = '';
        },

        // Handle file upload
        async handleFileUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            if (this.uploadTarget === 'input') {
                // Load to input
                this.loadFileToInput(file);
            } else {
                // Upload to workspace
                await this.uploadFileToWorkspace(file);
            }

            // Clear file input, allow uploading same file again
            this.$refs.fileInput.value = '';
        },

        // Load file content to input
        loadFileToInput(file) {
            // Check file type
            if (!file.type.match('text.*') && !file.name.match(/\.(txt|md|json|csv|py|js|html|css|xml)$/i)) {
                this.showNotification('只能将文本文件加载到输入框', 'warning');
                return;
            }

            const reader = new FileReader();
            reader.onload = (e) => {
                const content = e.target.result;
                // If file is too large, only load part of it
                const maxChars = 5000;
                if (content.length > maxChars) {
                    this.userInput = content.substring(0, maxChars) +
                        `\n\n[注意: 文件 ${file.name} 太大，只加载了前 ${maxChars} 个字符]`;
                    this.showNotification(`文件 ${file.name} 太大，只加载了部分内容`, 'warning');
                } else {
                    this.userInput = content;
                    this.showNotification(`文件 ${file.name} 已加载到输入框`, 'success');
                }

                // Automatically focus input
                this.$nextTick(() => {
                    this.$refs.userInputArea.focus();
                });
            };

            reader.onerror = () => {
                this.showError(`读取文件 ${file.name} 失败`);
            };

            reader.readAsText(file);
        },

        // Upload file to workspace
        async uploadFileToWorkspace(file) {
            try {
                // Create FormData object
                const formData = new FormData();
                formData.append('file', file);

                this.showNotification(`正在上传文件: ${file.name}...`, 'info');

                // Send file to server
                const response = await axios.post('/api/files', formData, {
                    headers: {
                        'Content-Type': 'multipart/form-data'
                    }
                });

                if (response.data && response.data.file) {
                    this.showNotification(`文件 ${file.name} 已成功上传`, 'success');
                    // Refresh file list
                    this.refreshFiles();
                }
            } catch (error) {
                console.error('上传文件失败:', error);
                this.showError(error.response?.data?.error || '上传文件失败，请稍后重试');
            }
        },

        // Disable auto-adjusting input box height, maintain initial height
        autoResizeTextarea() {
            this.$nextTick(() => {
                const textarea = this.$refs.userInputArea;
                if (!textarea) return;

                // Save current scroll position
                const scrollTop = textarea.scrollTop;

                // Only restore scroll position if needed
                if (textarea.scrollHeight > textarea.clientHeight) {
                    textarea.scrollTop = scrollTop;
                }

                // Adjust message container scroll position, ensure latest message is visible
                if (this.$refs.agentMessagesContainer) {
                    const container = this.$refs.agentMessagesContainer.querySelector('.column-content');
                    if (container) {
                        container.scrollTop = container.scrollHeight;
                    }
                }
            });
        },

        // Toggle gradient effect
        toggleGradientEffect() {
            this.gradientEffectEnabled = !this.gradientEffectEnabled;
            this.applyGradientEffectSettings();

            // Save preference to localStorage
            localStorage.setItem('gradientEffect', this.gradientEffectEnabled.toString());

            // Show notification about toggled status
            this.showNotification(
                this.gradientEffectEnabled ? '蓝红渐变效果已启用' : '蓝红渐变效果已禁用',
                'info'
            );
        },

        // Apply gradient effect settings
        applyGradientEffectSettings() {
            const body = document.body;
            if (this.gradientEffectEnabled) {
                body.classList.remove('gradient-disabled');
            } else {
                body.classList.add('gradient-disabled');
            }
        },

        // Initialize the drag functionality for the gradient toggle button
        initGradientToggleDrag() {
            const gradientToggle = document.getElementById('gradient-toggle-btn');
            if (!gradientToggle) return;

            let isDragging = false;
            let startY = 0;
            let startBottom = 0;

            gradientToggle.addEventListener('mousedown', (e) => {
                isDragging = true;
                startY = e.clientY;
                startBottom = parseInt(getComputedStyle(gradientToggle).bottom);

                // Prevent text selection
                e.preventDefault();

                // Disable transition effect during dragging
                gradientToggle.style.transition = 'none';
            });

            document.addEventListener('mousemove', (e) => {
                if (!isDragging) return;

                const deltaY = startY - e.clientY;
                const newBottom = startBottom + deltaY;

                // Limit the drag range within the viewport
                const maxBottom = window.innerHeight - gradientToggle.offsetHeight;
                const minBottom = 0;
                const clampedBottom = Math.min(Math.max(newBottom, minBottom), maxBottom);

                // Set position directly, without using transform to avoid inertia
                gradientToggle.style.bottom = `${clampedBottom}px`;
            });

            document.addEventListener('mouseup', () => {
                if (!isDragging) return;

                isDragging = false;

                // Restore transition effect
                gradientToggle.style.transition = 'right 0.3s ease';
            });
        },

        // Start polling for agent status
        startStatusPolling() {
            // Stop previous polling if it exists
            this.stopStatusPolling();

            this.statusPollingInterval = setInterval(async () => {
                try {
                    if (!this.sessionId || !this.isProcessing) {
                        this.stopStatusPolling();
                        return;
                    }

                    await this.fetchAgentStatus();
                } catch (error) {
                    console.error('轮询代理状态时出错:', error);
                }
            }, 1000); // Poll every second
        },

        // Stop polling for agent status
        stopStatusPolling() {
            if (this.statusPollingInterval) {
                clearInterval(this.statusPollingInterval);
                this.statusPollingInterval = null;
            }
        },

        // Fetch agent status
        async fetchAgentStatus() {
            try {
                const response = await axios.get(`/api/status/${this.sessionId}`);
                this.agentStatus.currentStep = response.data.current_step;
                this.agentStatus.maxSteps = response.data.max_steps;
                this.agentStatus.status = response.data.status;
            } catch (error) {
                console.error('获取代理状态失败:', error);
            }
        },

        // Terminate session
        async terminateSession() {
            if (!this.sessionId) {
                return;
            }

            // Update UI status
            const wasProcessing = this.isProcessing;
            this.isProcessing = false;
            this.isConnected = false;
            this.statusText = '正在终止...';
            this.connectionStatus = 'disconnected';

            // Reset step status
            this.agentStatus = {
                currentStep: 0,
                maxSteps: 0,
                status: ''
            };

            // Ensure status polling is stopped
            this.stopStatusPolling();

            // Add terminating message prompt
            if (wasProcessing) {
                this.messages.push({
                    role: 'assistant',
                    content: '正在终止会话...',
                    time: new Date(),
                    class: 'terminating-message'
                });

                // Scroll to bottom
                this.$nextTick(() => {
                    this.scrollToBottom();
                });
            }

            try {
                // Stop polling
                this.stopPolling();

                // Send termination request
                const response = await axios.post(`/api/terminate/${this.sessionId}`);

                // Check if the tool output message contains "terminate"
                const isTerminateSuccess = response.data &&
                    (response.data.status === 'success' ||
                        (response.data.message && response.data.message.toLowerCase().includes('success')));

                // Add termination success message
                this.messages.push({
                    role: 'assistant',
                    content: '会话已成功终止。要继续对话，请创建一个新会话。',
                    time: new Date(),
                    class: 'terminated-message'
                });

                // Reset session state
                this.sessionId = null;
                this.statusText = '未连接';

                // Scroll to bottom
                this.$nextTick(() => {
                    this.scrollToBottom();
                });
            } catch (error) {
                console.error('终止会话失败:', error);

                // If termination fails but was previously processing, show error and restore state
                if (wasProcessing) {
                    this.showError('终止会话失败，请重试。');
                    this.isProcessing = true;
                    this.isConnected = true;
                    this.statusText = '处理中...';
                    this.connectionStatus = 'processing';
                } else {
                    // If in idle state and termination fails, just show error
                    this.showError('终止会话失败，请重试。');
                    this.isConnected = true;
                    this.statusText = '已连接';
                    this.connectionStatus = 'connected';
                }
            }
        },

        // 设置示例任务点击事件
        setupExampleTasksListener() {
            // 使用事件委托来处理当前和将来的示例任务点击
            document.addEventListener('click', (event) => {
                // 检查点击的元素是否是示例任务
                if (event.target && event.target.closest('.welcome-tools-examples li')) {
                    const taskElement = event.target.closest('.welcome-tools-examples li');
                    // 提取任务文本
                    const taskText = taskElement.innerText.trim();
                    // 设置到输入框
                    this.userInput = taskText;
                    // 聚焦输入框
                    this.$nextTick(() => {
                        if (this.$refs.userInputArea) {
                            this.$refs.userInputArea.focus();
                        }
                    });
                }
            });
        },

        // 添加或更新侧边栏切换方法
        toggleSidebar() {
            this.showSidebar = !this.showSidebar;

            // 保存侧边栏状态到本地存储
            localStorage.setItem('nephesh_sidebar_visible', this.showSidebar);

            // 确保DOM更新后进行布局调整
            this.$nextTick(() => {
                // 手动触发窗口调整事件以确保布局正确响应
                window.dispatchEvent(new Event('resize'));

                // 调整聊天容器的布局
                const chatSection = document.querySelector('.chat-section');
                if (chatSection) {
                    if (this.showSidebar) {
                        chatSection.style.width = 'calc(100% - 300px)';
                    } else {
                        chatSection.style.width = '100%';
                    }
                }

                // 如果有消息，确保滚动到正确位置
                this.scrollToBottom();
            });
        },
    },

    beforeUnmount() {
        // Clean up resources before component unmounts
        this.stopPolling();

        // Clear typewriter effect timer
        if (this.typingTimer) {
            clearInterval(this.typingTimer);
            this.typingTimer = null;
        }

        // Remove event listeners correctly
        if (this.eventListeners.mouseMoveHandler) {
            document.removeEventListener('mousemove', this.eventListeners.mouseMoveHandler);
            this.eventListeners.mouseMoveHandler = null;
        }

        if (this.eventListeners.keydownHandler) {
            document.removeEventListener('keydown', this.eventListeners.keydownHandler);
            this.eventListeners.keydownHandler = null;
        }

        // Remove window resize event listener
        window.removeEventListener('resize', this.scrollToBottom);

        // Remove scroll event listeners from message containers
        if (this.$refs.toolMessagesContainer) {
            const container = this.$refs.toolMessagesContainer.querySelector('.column-content');
            if (container) {
                container.removeEventListener('scroll', this.handleToolMessagesScroll);
            }
        }

        if (this.$refs.agentMessagesContainer) {
            const container = this.$refs.agentMessagesContainer.querySelector('.column-content');
            if (container) {
                container.removeEventListener('scroll', this.handleAgentMessagesScroll);
            }
        }
    },

    // Add CSS transition hooks
    updated() {
        // Add animation effects when DOM updates
        this.$nextTick(() => {
            // Add animation for newly added messages
            const messages = document.querySelectorAll('.message');
            messages.forEach(msg => {
                if (!msg.dataset.animated) {
                    msg.dataset.animated = 'true';
                    msg.style.opacity = '0';
                    msg.style.transform = 'translateY(20px)';

                    setTimeout(() => {
                        msg.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
                        msg.style.opacity = '1';
                        msg.style.transform = 'translateY(0)';
                    }, 10);
                }
            });
        });
    }
});

// Register global custom directive v-ripple ripple effect
app.directive('ripple', {
    mounted(el) {
        el.style.position = 'relative';
        el.style.overflow = 'hidden';

        el.addEventListener('click', (e) => {
            const rect = el.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            const ripple = document.createElement('span');
            ripple.className = 'ripple-effect';
            ripple.style.position = 'absolute';
            ripple.style.width = '0';
            ripple.style.height = '0';
            ripple.style.borderRadius = '50%';
            ripple.style.backgroundColor = 'rgba(255, 255, 255, 0.3)';
            ripple.style.transform = 'translate(-50%, -50%)';
            ripple.style.left = `${x}px`;
            ripple.style.top = `${y}px`;

            el.appendChild(ripple);

            setTimeout(() => {
                ripple.style.transition = 'all 0.6s ease-out';
                ripple.style.width = `${Math.max(rect.width, rect.height) * 2}px`;
                ripple.style.height = `${Math.max(rect.width, rect.height) * 2}px`;
                ripple.style.opacity = '0';

                setTimeout(() => {
                    ripple.remove();
                }, 600);
            }, 10);
        });
    }
});

// Register global custom component - Smooth tooltip
app.component('smooth-tooltip', {
    template: `
        <div class="tooltip-container" @mouseenter="show" @mouseleave="hide">
            <slot></slot>
            <div class="tooltip" :class="{ active: isVisible }">
                <div class="tooltip-content">{{ text }}</div>
                <div class="tooltip-arrow"></div>
            </div>
        </div>
    `,
    props: {
        text: {
            type: String,
            required: true
        },
        position: {
            type: String,
            default: 'top',
            validator: (value) => ['top', 'bottom', 'left', 'right'].includes(value)
        }
    },
    data() {
        return {
            isVisible: false
        }
    },
    methods: {
        show() {
            this.isVisible = true;
        },
        hide() {
            this.isVisible = false;
        }
    }
});

// Mount application
app.mount('#app');

// Add global styles
const style = document.createElement('style');
style.textContent = `
    .ripple-effect {
        position: absolute;
        border-radius: 50%;
        background-color: rgba(255, 255, 255, 0.3);
        pointer-events: none;
        z-index: 10;
    }

    .tooltip-container {
        position: relative;
        display: inline-block;
    }

    .tooltip {
        position: absolute;
        background-color: rgba(60, 60, 60, 0.9);
        color: white;
        padding: 5px 10px;
        border-radius: 4px;
        font-size: 12px;
        white-space: nowrap;
        pointer-events: none;
        opacity: 0;
        transition: opacity 0.3s, transform 0.3s;
        z-index: 1000;
        top: -30px;
        left: 50%;
        transform: translateX(-50%) translateY(-10px);
    }

    .tooltip.active {
        opacity: 1;
        transform: translateY(0);
    }

    .tooltip-arrow {
        position: absolute;
        bottom: -5px;
        left: 50%;
        transform: translateX(-50%);
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid rgba(60, 60, 60, 0.9);
    }
`;
document.head.appendChild(style);
