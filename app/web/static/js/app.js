// Configure axios default URL
axios.defaults.baseURL = window.location.origin;  // Use the current page's origin as the base URL

// Vue application
const app = Vue.createApp({
    delimiters: ['${', '}'],  // Custom delimiters to avoid conflicts with Flask template syntax

    data() {
        return {
            // Session state
            sessionId: null,
            isConnected: false,
            isProcessing: false,
            statusText: 'Not connected',
            connectionStatus: 'disconnected',

            // Message data
            messages: [],
            userInput: '',

            // Polling control
            pollingInterval: null,
            pollRate: 1000, // Polling interval (milliseconds)

            // Tool data
            availableTools: [],
            usedTools: new Set(),

            // Panel control
            isAvailableToolsOpen: false,
            isUsedToolsOpen: false,

            // Navbar notification
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
            typingSpeed: 30, // Typing speed per character (ms)
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

            // New: Currently active tool tab
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
                llm: { name: 'Large Language Model', icon: 'fa-comment-dots' },
                browser: { name: 'Browser', icon: 'fa-globe' },
                search: { name: 'Search Engine', icon: 'fa-search' },
                sandbox: { name: 'Sandbox', icon: 'fa-cube' },
                server: { name: 'Server', icon: 'fa-server' }
            },
            originalConfig: null,

            // Proxy settings helper variables
            proxyServerConfig: '',
            proxyUsernameConfig: '',
            proxyPasswordConfig: ''
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

        // Get agent message list
        agentMessages() {
            return this.messages.filter(msg => msg.role === 'assistant');
        },

        // Get tool message list
        toolMessages() {
            return this.messages.filter(msg => msg.role === 'tool');
        }
    },

    mounted() {
        // Automatically create a new session after page load
        this.createNewSession();

        // Scroll to the bottom of the message container functionality
        this.$nextTick(() => {
            this.scrollToBottom();
        });

        // Add mouse movement tracking
        this.initMouseTracking();

        // Add keyboard shortcuts
        this.setupKeyboardShortcuts();

        // Load saved theme settings
        this.loadThemePreference();

        // Add click event to theme toggle button
        this.$nextTick(() => {
            const themeButton = document.querySelector('.theme-button');
            if (themeButton) {
                themeButton.addEventListener('click', this.toggleTheme);
            }
        });

        // Listen for page resize, update message container scrolling
        window.addEventListener('resize', this.scrollToBottom);

        // Add message animation observer
        this.setupMessageAnimations();

        // Listen for message list changes, ensure auto-scrolling
        this.$watch('messages', () => {
            this.scrollToBottom();
        }, { deep: true });
    },

    methods: {
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

            // Save preference to localStorage
            localStorage.setItem('darkMode', this.isDarkTheme);
        },

        // Load theme preference
        loadThemePreference() {
            const savedPreference = localStorage.getItem('darkMode');
            if (savedPreference !== null) {
                this.isDarkTheme = savedPreference === 'true';
            }
            this.applyTheme();
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
                    logoElement.src = '/static/images/logo.png';
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

                // Use logo_black.png in light mode
                const logoElement = document.querySelector('.logo');
                if (logoElement) {
                    logoElement.src = '/static/images/logo_black.png';
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
            document.addEventListener('mousemove', (e) => {
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
            });
        },

        // Set up keyboard shortcuts
        setupKeyboardShortcuts() {
            document.addEventListener('keydown', (e) => {
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
            });
        },

        // Typewriter effect
        startTypingEffect(message) {
            // If there's a previous typing effect in progress, stop it
            if (this.typingTimer) {
                clearInterval(this.typingTimer);
                this.typingTimer = null;
            }

            // Initialize typing effect
            this.typingInProgress = true;
            this.currentTypingMessage = message;
            this.typingText = '';
            this.typingIndex = 0;

            const content = message.content || '';

            // Start typing effect
            this.typingTimer = setInterval(() => {
                if (this.typingIndex < content.length) {
                    this.typingText += content[this.typingIndex];
                    this.typingIndex++;
                    this.scrollToBottom();
                } else {
                    this.completeTypingEffect();
                }
            }, this.typingSpeed);
        },

        // Complete typing effect
        completeTypingEffect() {
            if (this.typingTimer) {
                clearInterval(this.typingTimer);
                this.typingTimer = null;
            }

            if (this.currentTypingMessage) {
                this.currentTypingMessage.content = this.currentTypingMessage.content || '';
                this.typingText = this.currentTypingMessage.content;
            }

            this.typingInProgress = false;
            this.currentTypingMessage = null;

            // Reapply code highlighting
            this.$nextTick(() => {
                this.applyCodeHighlighting();
                this.scrollToBottom(); // Scroll after typing effect ends
            });
        },

        // Toggle the collapsed state of the tools list
        toggleToolsSection(section) {
            if (section === 'availableTools') {
                this.isAvailableToolsOpen = !this.isAvailableToolsOpen;
            } else if (section === 'usedTools') {
                this.isUsedToolsOpen = !this.isUsedToolsOpen;
            }
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

                console.log('Creating new session...');
                const response = await axios.post('/api/session');
                console.log('Session creation response:', response.data);

                this.sessionId = response.data.session_id;
                this.isConnected = true;
                this.statusText = 'Connected';
                this.connectionStatus = 'connected';
                this.messages = [];
                this.usedTools = new Set(); // Reset used tools list

                // Reset panel state
                this.isAvailableToolsOpen = false;
                this.isUsedToolsOpen = false;

                // Get available tools list
                this.fetchAvailableTools();

                // Add welcome message
                const welcomeMessage = {
                    role: 'assistant',
                    content: 'Hello! I\'m Manus, a general-purpose intelligent agent. I can help you complete various tasks. Please tell me what you need help with?',
                    time: new Date()
                };

                this.messages.push(welcomeMessage);

                // Use typewriter effect to display welcome message
                this.$nextTick(() => {
                    this.startTypingEffect(welcomeMessage);
                });

                console.log(`New session created successfully, ID: ${this.sessionId}`);
            } catch (error) {
                console.error('Failed to create session:', error);

                // Display more detailed error information
                let errorMsg = 'Unable to create new session, please try again later.';
                if (error.response) {
                    errorMsg += ` Status code: ${error.response.status}`;
                    if (error.response.data && error.response.data.error) {
                        errorMsg += ` - ${error.response.data.error}`;
                    }
                } else if (error.request) {
                    errorMsg += ' Server not responding, please check your network connection.';
                } else {
                    errorMsg += ` Error message: ${error.message}`;
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

                    // Add tool loading animation
                    this.animateToolsAppearance();
                }
            } catch (error) {
                console.error('Failed to get tools list:', error);
                // Don't set default tools list, completely rely on backend data
                this.availableTools = [];
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

        // Send message
        async sendMessage() {
            if (!this.userInput.trim() || this.isProcessing || !this.isConnected) {
                return;
            }

            const userMessage = this.userInput.trim();

            // Clear all previous user messages, only keep the last one
            this.messages = this.messages.filter(msg => msg.role !== 'user');

            // Add new user message
            this.messages.push({
                role: 'user',
                content: userMessage,
                time: new Date()
            });

            this.userInput = '';
            this.isProcessing = true;
            this.statusText = 'Processing...';
            this.connectionStatus = 'processing';

            // Scroll to bottom
            this.$nextTick(() => {
                this.scrollToBottom();
            });

            try {
                // Send message to server
                console.log(`Sending message to: ${axios.defaults.baseURL}/api/chat`);
                console.log(`Session ID: ${this.sessionId}`);
                const response = await axios.post('/api/chat', {
                    session_id: this.sessionId,
                    message: userMessage
                });

                console.log('Server response:', response.data);

                // Start polling for responses
                this.startPolling();
            } catch (error) {
                console.error('Failed to send message:', error);
                this.isProcessing = false;
                this.statusText = 'Connected';
                this.connectionStatus = 'connected';

                // Display more detailed error information
                let errorMsg = 'Failed to send message, please try again.';
                if (error.response) {
                    // Server returned an error status code
                    errorMsg += ` Status code: ${error.response.status}`;
                    if (error.response.data && error.response.data.error) {
                        errorMsg += ` - ${error.response.data.error}`;
                    }
                } else if (error.request) {
                    // Request was sent but no response received
                    errorMsg += ' Server not responding, please check your network connection.';
                } else {
                    // Error during request setup
                    errorMsg += ` Error message: ${error.message}`;
                }

                this.showError(errorMsg);
            }
        },

        // Start polling for messages
        startPolling() {
            if (this.pollingInterval) {
                clearInterval(this.pollingInterval);
            }

            let retryCount = 0;
            const maxRetries = 3;

            this.pollingInterval = setInterval(async () => {
                try {
                    if (!this.sessionId) {
                        this.stopPolling();
                        return;
                    }

                    const response = await axios.get(`/api/messages/${this.sessionId}`);

                    // Reset retry counter
                    retryCount = 0;

                    // Process new messages
                    if (response.data.messages && response.data.messages.length > 0) {
                        this.processMessages(response.data.messages);
                    }

                    // If processing is complete, stop polling
                    if (response.data.completed) {
                        this.stopPolling();
                        this.isProcessing = false;
                        this.statusText = 'Connected';
                        this.connectionStatus = 'connected';
                    }
                } catch (error) {
                    console.error('Failed to get messages:', error);
                    retryCount++;

                    if (retryCount >= maxRetries) {
                        this.stopPolling();
                        this.isProcessing = false;
                        this.statusText = 'Connected';
                        this.connectionStatus = 'connected';

                        // Display more detailed error information
                        let errorMsg = `Polling for messages failed (retried ${retryCount} times)`;
                        if (error.response) {
                            errorMsg += ` Status code: ${error.response.status}`;
                            if (error.response.data && error.response.data.error) {
                                errorMsg += ` - ${error.response.data.error}`;
                            }
                        } else if (error.request) {
                            errorMsg += ' Server not responding';
                        } else {
                            errorMsg += ` Error: ${error.message}`;
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
        },

        // Process received messages
        processMessages(newMessages) {
            for (const msg of newMessages) {
                // Check for errors
                if (msg.error) {
                    this.showError(msg.error);
                    continue;
                }

                // Skip user messages, because we already have a user message displayed in the top area
                if (msg.role === 'user') {
                    continue;
                }

                // Ensure message object includes necessary properties
                const messageObj = {
                    ...msg,
                    time: new Date()
                };

                // Process based on role and type from backend
                if (messageObj.role === 'assistant') {
                    // If it's an assistant message, delete any potential tool name
                    delete messageObj.name;
                } else if (messageObj.role === 'tool') {
                    // If it's a tool message, ensure correct tool name
                    if (messageObj.base64_image) {
                        // If contains screenshot, use browser screenshot as tool name
                        messageObj.name = messageObj.name || 'Browser Screenshot';
                        messageObj.class = (messageObj.class || '') + ' browser-screenshot';
                    } else if (messageObj.tool_calls && messageObj.tool_calls.length > 0) {
                        // Use name from tool calls
                        if (!messageObj.name && messageObj.tool_calls[0].function) {
                            messageObj.name = messageObj.tool_calls[0].function.name;
                        }
                    }
                }

                this.messages.push(messageObj);

                // Update used tools list
                this.updateUsedTools(messageObj);

                // If it's an assistant message with content, apply typewriter effect
                if (messageObj.role === 'assistant' && messageObj.content) {
                    this.startTypingEffect(messageObj);
                } else {
                    // If not an assistant message, or has no content, reapply code highlighting
                    this.$nextTick(() => {
                        this.applyCodeHighlighting();
                        this.scrollToBottom();
                    });
                }
            }

            // After processing all messages, scroll to bottom again
            this.scrollToBottom();
        },

        // Update used tools list
        updateUsedTools(message) {
            // If it's a tool message, add to used tools set
            if (message.role === 'tool' && message.name) {
                this.usedTools.add(message.name);

                // If used tools panel is closed, automatically open it
                if (!this.isUsedToolsOpen && this.usedTools.size === 1) {
                    this.isUsedToolsOpen = true;
                }
            }

            // Check and add tools identified from tool calls
            if (message.tool_calls && message.tool_calls.length > 0) {
                for (const tool of message.tool_calls) {
                    if (tool.function && tool.function.name) {
                        this.usedTools.add(tool.function.name);

                        // If used tools panel is closed, automatically open it
                        if (!this.isUsedToolsOpen && this.usedTools.size === 1) {
                            this.isUsedToolsOpen = true;
                        }
                    }
                }
            }
        },

        // Show error message
        showError(errorMessage) {
            this.messages.push({
                role: 'assistant',
                content: `Error occurred: ${errorMessage}`,
                time: new Date(),
                class: 'error-message'
            });

            // Scroll to bottom
            this.$nextTick(() => {
                this.scrollToBottom();
            });
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
            this.statusText = 'Terminating...';
            this.connectionStatus = 'disconnected';

            // Add terminating message prompt
            if (wasProcessing) {
                this.messages.push({
                    role: 'assistant',
                    content: 'Terminating session...',
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
                await axios.post(`/api/terminate/${this.sessionId}`);

                // Add termination success message
                this.messages.push({
                    role: 'assistant',
                    content: 'Session has been successfully terminated. To continue conversation, please create a new session.',
                    time: new Date(),
                    class: 'terminated-message'
                });

                // Reset session state
                this.sessionId = null;
                this.statusText = 'Not connected';

                // Scroll to bottom
                this.$nextTick(() => {
                    this.scrollToBottom();

                    // Add shake animation effect
                    const terminatedMsg = document.querySelector('.terminated-message');
                    if (terminatedMsg) {
                        terminatedMsg.style.animation = 'shake 0.5s ease-in-out';
                    }
                });
            } catch (error) {
                console.error('Failed to terminate session:', error);

                // If termination fails but was previously processing, show error and restore state
                if (wasProcessing) {
                    this.showError('Failed to terminate session, please try again.');
                    this.isProcessing = true;
                    this.isConnected = true;
                    this.statusText = 'Processing...';
                    this.connectionStatus = 'processing';
                } else {
                    // If in idle state and termination fails, just show error
                    this.showError('Failed to terminate session, please try again.');
                    this.isConnected = true;
                    this.statusText = 'Connected';
                    this.connectionStatus = 'connected';
                }
            }
        },

        // Format message content
        formatMessage(content) {
            if (!content) return '';

            // If typing effect is in progress and current message is being processed
            if (this.typingInProgress &&
                this.currentTypingMessage &&
                this.currentTypingMessage.content === content) {
                // Return current typing text
                return this.typingText;
            }

            // Use marked.js to convert Markdown to HTML
            const html = marked.parse(content);
            return html;
        },

        // Apply code highlighting
        applyCodeHighlighting() {
            // Use Prism.js to reapply code highlighting
            Prism.highlightAll();
        },

        // Format JSON string
        formatJson(jsonString) {
            try {
                if (typeof jsonString === 'string') {
                    // Parse JSON string and beautify format
                    const obj = JSON.parse(jsonString);
                    return JSON.stringify(obj, null, 2);
                } else {
                    // If already an object, just beautify
                    return JSON.stringify(jsonString, null, 2);
                }
            } catch (e) {
                // If parsing fails, return original string
                return jsonString;
            }
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
                // Scroll agent messages container
                if (this.$refs.agentMessagesContainer) {
                    const container = this.$refs.agentMessagesContainer.querySelector('.column-content');
                    if (container) {
                        // Use more reliable scrolling method
                        container.scrollTop = container.scrollHeight;
                    }
                }

                // Scroll tool messages container
                if (this.$refs.toolMessagesContainer) {
                    const container = this.$refs.toolMessagesContainer.querySelector('.column-content');
                    if (container) {
                        // Use more reliable scrolling method
                        container.scrollTop = container.scrollHeight;
                    }
                }
            });
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
                console.error('Failed to get configuration:', error);
                this.showError('Failed to get configuration information, please check network connection or server status');
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

                    // 根据热重载状态显示不同的消息
                    const reloadSuccess = response.data.reload_success === true;
                    const serverConfigChanged = response.data.server_config_changed === true;

                    // Close config panel
                    this.showConfigPanel = false;

                    let messageContent = '';
                    let notificationType = '';
                    let notificationOptions = { duration: 5000 };

                    if (reloadSuccess) {
                        if (serverConfigChanged) {
                            messageContent = `Configuration has been successfully saved! However, the server address or port has been changed, and a restart is required to take effect.`;
                            notificationType = 'warning';
                            notificationOptions.showAction = true;
                            notificationOptions.actionType = 'restart';
                            notificationOptions.duration = null; // 不自动关闭
                        } else {
                            messageContent = `Configuration has been successfully updated, and a new session will be automatically created to apply the new configuration...`;
                            notificationType = 'success';
                        }
                    } else {
                        messageContent = `Configuration has been successfully saved, but the hot reload failed. Some changes may require a server restart to take effect.`;
                        notificationType = 'warning';
                        notificationOptions.showAction = true;
                        notificationOptions.actionType = 'restart';
                        notificationOptions.duration = null; // 不自动关闭
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
                console.error('Failed to save configuration:', error);
                this.showError('Failed to save configuration: ' + (error.response?.data?.error || error.message));
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
            this.showCenterNotification('Server restart command has been sent, please wait for the service to recover...', 'info', { duration: 3000 });
        },

        // Show floating notification (reserved for backward compatibility)
        showNotification(message, type = 'info') {
            // Call central notification card
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

        // Show central notification card
    },

    beforeUnmount() {
        // Clean up resources before component unmounts
        this.stopPolling();

        // Clear typewriter effect timer
        if (this.typingTimer) {
            clearInterval(this.typingTimer);
            this.typingTimer = null;
        }

        // Remove event listeners
        document.removeEventListener('mousemove', this.initMouseTracking);
        document.removeEventListener('keydown', this.setupKeyboardShortcuts);

        // Remove theme toggle button event
        const themeButton = document.querySelector('.theme-button');
        if (themeButton) {
            themeButton.removeEventListener('click', this.toggleTheme);
        }

        // Listen for page resize, update message container scrolling
        window.removeEventListener('resize', this.scrollToBottom);
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
        transform: translateY(-10px);
        transition: opacity 0.3s, transform 0.3s;
        z-index: 1000;
        top: -30px;
        left: 50%;
        transform: translateX(-50%);
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

    @keyframes shake {
        0%, 100% { transform: translateX(0); }
        10%, 30%, 50%, 70%, 90% { transform: translateX(-5px); }
        20%, 40%, 60%, 80% { transform: translateX(5px); }
    }
`;
document.head.appendChild(style);
