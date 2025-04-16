// Configure the default URL for axios
axios.defaults.baseURL = window.location.origin;

// Vue application
const { createApp } = Vue;
const app = createApp({
    delimiters: ['${', '}'],  // Custom delimiters to avoid conflicts with Flask template syntax

    data() {
        return {
            // History list
            historyList: [],

            // Selected session ID and details
            selectedSession: null,
            sessionDetail: {
                session_id: '',
                created_at: '',
                completed_at: '',
                prompts: [],
                messages: []
            },

            // Theme settings
            isDarkTheme: true,

            // Loading state
            isLoading: false,

            // Error message
            errorMessage: '',
            hasError: false,

            // Confirmation dialog
            showConfirmDialog: false,
            confirmTitle: '',
            confirmMessage: '',
            confirmCallback: null,
            confirmData: null,

            // Print options
            usePrintToPdf: false
        };
    },

    mounted() {
        // Load saved theme preference
        this.loadThemePreference();

        // Fetch history record list
        this.fetchHistoryList();

        // Hide loading animation
        this.hideLoader();
    },

    methods: {
        // Load saved theme preference
        loadThemePreference() {
            const savedTheme = localStorage.getItem('theme');
            if (savedTheme) {
                this.isDarkTheme = savedTheme === 'dark';
            } else {
                // Check system preference
                const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                this.isDarkTheme = prefersDark;
            }
            this.applyTheme();
        },

        // Toggle theme
        toggleTheme() {
            this.isDarkTheme = !this.isDarkTheme;
            localStorage.setItem('theme', this.isDarkTheme ? 'dark' : 'light');
            this.applyTheme();
        },

        // Apply theme
        applyTheme() {
            if (this.isDarkTheme) {
                document.documentElement.classList.add('dark-theme');
                document.documentElement.classList.remove('light-theme');
            } else {
                document.documentElement.classList.add('light-theme');
                document.documentElement.classList.remove('dark-theme');
            }
        },

        // Fetch history record list
        async fetchHistoryList() {
            this.isLoading = true;
            this.hasError = false;
            this.errorMessage = '';

            try {
                const response = await axios.get('/api/history');

                if (response.data && Array.isArray(response.data.history)) {
                    this.historyList = response.data.history;
                    console.log('历史记录数量:', this.historyList.length);
                } else {
                    console.warn('加载历史记录失败，数据格式不正确:', response.data);
                    this.errorMessage = '加载历史记录失败，数据格式不正确';
                    this.hasError = true;
                }
            } catch (error) {
                console.error('加载历史记录失败:', error);
                this.errorMessage = '加载历史记录失败: ' + (error.response?.data?.error || error.message || '未知错误');
                this.hasError = true;
            } finally {
                this.isLoading = false;
            }
        },

        // Refresh history record list
        refreshHistory() {
            this.fetchHistoryList();
        },

        // View session details
        async viewSessionDetail(sessionId) {
            this.isLoading = true;
            this.hasError = false;
            this.errorMessage = '';

            try {
                const response = await axios.get(`/api/history/${sessionId}`);

                if (response.data) {
                    this.sessionDetail = response.data;
                    this.selectedSession = sessionId;

                    // Apply code highlighting
                    this.$nextTick(() => {
                        this.applyCodeHighlighting();
                    });
                } else {
                    console.warn('获取会话详情失败，数据格式不正确:', response.data);
                    this.errorMessage = '加载会话详情失败，数据格式不正确';
                    this.hasError = true;
                }
            } catch (error) {
                console.error('获取会话详情失败:', error);
                this.errorMessage = '获取会话详情失败: ' + (error.response?.data?.error || error.message || '未知错误');
                this.hasError = true;
            } finally {
                this.isLoading = false;
            }
        },

        // Back to list
        backToList() {
            this.selectedSession = null;
            this.hasError = false;
            this.errorMessage = '';
        },

        // Delete single session
        confirmDeleteSession(sessionId) {
            this.createConfirmDialog(
                '删除会话',
                '确定要删除此会话记录吗？此操作无法撤消。',
                () => this.deleteSession(sessionId)
            );
        },

        async deleteSession(sessionId) {
            this.isLoading = true;
            try {
                const response = await axios.delete(`/api/history/${sessionId}`);
                if (response.data && response.data.success) {
                    // Remove from list
                    this.historyList = this.historyList.filter(item => item.session_id !== sessionId);
                    this.showNotification('会话记录删除成功');
                } else {
                    this.showNotification('删除会话记录失败: ' + (response.data.error || '未知错误'), 'error');
                }
            } catch (error) {
                console.error('删除会话失败:', error);
                this.showNotification('删除会话失败: ' + (error.response?.data?.error || error.message || '未知错误'), 'error');
            } finally {
                this.isLoading = false;
            }
        },

        // Clear all history records
        confirmClearHistory() {
            this.createConfirmDialog(
                '清空所有历史记录',
                '确定要清空所有历史记录吗？此操作无法撤消。',
                () => this.clearHistory()
            );
        },

        async clearHistory() {
            this.isLoading = true;
            try {
                const response = await axios.delete('/api/history');
                if (response.data && response.data.success) {
                    this.historyList = [];
                    this.showNotification('所有历史记录已成功清空');
                } else {
                    this.showNotification('清空历史记录失败: ' + (response.data.error || '未知错误'), 'error');
                }
            } catch (error) {
                console.error('清空历史记录失败:', error);
                this.showNotification('清空历史记录失败: ' + (error.response?.data?.error || error.message || '未知错误'), 'error');
            } finally {
                this.isLoading = false;
            }
        },

        // Export single session record
        async exportSession(sessionId, format) {
            if (!sessionId) {
                this.showNotification('无效的会话ID', 'error');
                return;
            }

            // Handle PDF format (use system printing feature)
            if (format === 'pdf') {
                this.isLoading = true;
                try {
                    // Get session details
                    const response = await axios.get(`/api/history/${sessionId}`);
                    const sessionData = response.data;

                    // Create print window
                    const printWindow = window.open('', '_blank');
                    if (!printWindow) {
                        this.showNotification('无法打开打印窗口。请检查浏览器是否阻止了弹出窗口。', 'error');
                        this.isLoading = false;
                        return;
                    }

                    // Generate HTML content
                    let htmlContent = `
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="UTF-8">
                        <title>OpenManus 会话记录 - ${sessionId.substring(0, 8)}</title>
                        <style>
                            body { font-family: Arial, sans-serif; margin: 20px; }
                            h1 { color: #4361ee; }
                            h2 { color: #6f3ff5; border-bottom: 1px solid #ddd; padding-bottom: 5px; }
                            .user-message { background: #f0f5ff; padding: 10px; border-radius: 5px; margin: 10px 0; }
                            .assistant-message { background: #f5f0ff; padding: 10px; border-radius: 5px; margin: 10px 0; }
                            .tool-message { background: #f0fff5; padding: 10px; border-radius: 5px; margin: 10px 0; font-family: monospace; }
                            pre { background: #f5f5f5; padding: 10px; border-radius: 5px; overflow-x: auto; }
                            .message-header { font-weight: bold; margin-bottom: 5px; }
                            .tool-calls { margin-top: 10px; border-top: 1px dashed #ccc; padding-top: 10px; }
                            .tool-call { background: rgba(79, 209, 197, 0.1); border-radius: 5px; margin: 8px 0; overflow: hidden; }
                            .tool-call-header { padding: 5px 10px; background: rgba(79, 209, 197, 0.2); color: #2c7a7b; font-weight: bold; }
                            .tool-call-args { margin: 0; padding: 10px; background: #f8f8f8; max-height: 300px; overflow: auto; font-family: monospace; font-size: 0.9em; }
                            @media print {
                                body { font-size: 12pt; }
                                h1 { font-size: 18pt; }
                                h2 { font-size: 14pt; }
                                .tool-calls { page-break-inside: avoid; }
                            }
                        </style>
                    </head>
                    <body>
                        <h1>OpenManus 会话记录</h1>
                        <p><strong>会话ID:</strong> ${sessionData.session_id}</p>
                        <p><strong>创建时间:</strong> ${sessionData.created_at}</p>
                        <hr>
                    `;

                    // Add message content
                    const messages = sessionData.messages || [];
                    messages.forEach(msg => {
                        const role = msg.role || '';
                        const content = msg.content || '';

                        if (role === 'user') {
                            htmlContent += `
                            <div class="user-message">
                                <div class="message-header">用户:</div>
                                <div>${this.formatContent(content)}</div>
                            </div>`;
                        } else if (role === 'assistant') {
                            htmlContent += `
                            <div class="assistant-message">
                                <div class="message-header">助手:</div>
                                <div>${this.formatContent(content)}</div>
                            </div>`;

                            // Add tool call arguments in assistant messages
                            if (msg.tool_calls && msg.tool_calls.length > 0) {
                                htmlContent += `<div class="tool-calls">`;
                                for (const toolCall of msg.tool_calls) {
                                    if (toolCall.function && toolCall.function.name) {
                                        htmlContent += `
                                        <div class="tool-call">
                                            <div class="tool-call-header">工具调用: ${toolCall.function.name}</div>
                                            <pre class="tool-call-args">${this.formatJson(toolCall.function.arguments)}</pre>
                                        </div>`;
                                    }
                                }
                                htmlContent += `</div>`;
                            }
                        } else if (role === 'tool') {
                            const toolName = msg.name || '未知工具';
                            htmlContent += `
                            <div class="tool-message">
                                <div class="message-header">工具 (${toolName}):</div>
                                <pre>${content}</pre>
                            </div>`;

                            // Add tool call arguments in tool messages
                            if (msg.tool_calls && msg.tool_calls.length > 0) {
                                htmlContent += `<div class="tool-calls">`;
                                for (const toolCall of msg.tool_calls) {
                                    if (toolCall.function && toolCall.function.name) {
                                        htmlContent += `
                                        <div class="tool-call">
                                            <div class="tool-call-header">工具调用: ${toolCall.function.name}</div>
                                            <pre class="tool-call-args">${this.formatJson(toolCall.function.arguments)}</pre>
                                        </div>`;
                                    }
                                }
                                htmlContent += `</div>`;
                            }
                        }
                    });

                    htmlContent += `
                        <script>
                            window.onload = function() {
                                setTimeout(function() {
                                    window.print();
                                    setTimeout(function() {
                                        window.close();
                                    }, 500);
                                }, 500);
                            }
                        </script>
                    </body>
                    </html>`;

                    // Write HTML content and trigger print
                    printWindow.document.write(htmlContent);
                    printWindow.document.close();

                    this.showNotification('准备打印，请选择"Microsoft打印为PDF"作为打印机');
                } catch (error) {
                    console.error('导出会话记录失败:', error);
                    this.showNotification('导出失败: ' + (error.response?.data?.error || error.message || '未知错误'), 'error');
                } finally {
                    this.isLoading = false;
                }
                return;
            }

            // Handle other formats (JSON/TXT/MD)
            this.isLoading = true;
            try {
                let mimeType, fileExt;
                switch (format) {
                    case 'json':
                        mimeType = 'application/json';
                        fileExt = 'json';
                        break;
                    case 'txt':
                        mimeType = 'text/plain';
                        fileExt = 'txt';
                        break;
                    case 'md':
                        mimeType = 'text/markdown';
                        fileExt = 'md';
                        break;
                    default:
                        mimeType = 'application/json';
                        fileExt = 'json';
                }

                // Call backend API to export session
                const response = await axios.get(`/api/history/${sessionId}/export/${format}`, {
                    responseType: 'blob'
                });

                // Create download link
                const blob = new Blob([response.data], { type: mimeType });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                const sessionIdShort = sessionId.substring(0, 8);
                const now = new Date();
                const timestamp = now.toISOString().replace(/[:.]/g, '-').substring(0, 19);
                a.href = url;
                a.download = `openmanus-session-${sessionIdShort}-${timestamp}.${fileExt}`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);

                this.showNotification(`会话记录已成功导出为${format.toUpperCase()}格式`);
            } catch (error) {
                console.error('导出会话记录失败:', error);
                this.showNotification('导出失败: ' + (error.response?.data?.error || error.message || '未知错误'), 'error');
            } finally {
                this.isLoading = false;
            }
        },

        // Helper function: Format content, convert pure text to HTML (preserve line breaks, etc.)
        formatContent(text) {
            if (!text) return '';

            // Escape HTML special characters
            let escaped = text.replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');

            // Convert line breaks to <br> tags
            return escaped.replace(/\n/g, '<br>');
        },

        // Show notification message
        showNotification(message, type = 'success') {
            const notification = document.createElement('div');
            notification.className = `center-notification ${type}`;

            // Create notification content
            const content = document.createElement('div');
            content.className = 'center-notification-content';

            // Add icon
            const icon = document.createElement('i');
            const iconClass = type === 'success' ? 'fa-check-circle' :
                type === 'error' ? 'fa-exclamation-circle' : 'fa-exclamation-triangle';
            icon.className = `notification-icon fas ${iconClass}`;

            // Add message
            const text = document.createElement('span');
            text.className = 'notification-message';
            text.textContent = message;

            // Assemble notification
            content.appendChild(icon);
            content.appendChild(text);
            notification.appendChild(content);

            // Add to page
            document.body.appendChild(notification);

            // Remove after 3 seconds
            setTimeout(() => {
                notification.style.opacity = '0';
                notification.style.transform = 'translate(-50%, -20px)';
                setTimeout(() => {
                    document.body.removeChild(notification);
                }, 300);
            }, 3000);
        },

        // Create confirm dialog
        createConfirmDialog(title, message, confirmCallback) {
            // Remove existing dialog
            const existingDialog = document.querySelector('.confirm-dialog-overlay');
            if (existingDialog) {
                document.body.removeChild(existingDialog);
            }

            // Create dialog container
            const overlay = document.createElement('div');
            overlay.className = 'confirm-dialog-overlay';

            // Create dialog
            const dialog = document.createElement('div');
            dialog.className = 'confirm-dialog';

            // Header
            const header = document.createElement('div');
            header.className = 'confirm-dialog-header';

            const titleSpan = document.createElement('span');
            titleSpan.textContent = title;

            const closeBtn = document.createElement('button');
            closeBtn.className = 'close-dialog-btn';
            closeBtn.innerHTML = '<i class="fas fa-times"></i>';
            closeBtn.onclick = () => document.body.removeChild(overlay);

            header.appendChild(titleSpan);
            header.appendChild(closeBtn);

            // Content
            const content = document.createElement('div');
            content.className = 'confirm-dialog-content';

            const messageP = document.createElement('p');
            messageP.textContent = message;
            content.appendChild(messageP);

            // Bottom buttons
            const footer = document.createElement('div');
            footer.className = 'confirm-dialog-footer';

            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'secondary-btn';
            cancelBtn.textContent = '取消';
            cancelBtn.onclick = () => document.body.removeChild(overlay);

            const confirmBtn = document.createElement('button');
            confirmBtn.className = 'secondary-btn danger-btn';
            confirmBtn.textContent = '确认';
            confirmBtn.onclick = () => {
                document.body.removeChild(overlay);
                if (confirmCallback) confirmCallback();
            };

            footer.appendChild(cancelBtn);
            footer.appendChild(confirmBtn);

            // Assemble dialog
            dialog.appendChild(header);
            dialog.appendChild(content);
            dialog.appendChild(footer);
            overlay.appendChild(dialog);

            // Add to page
            document.body.appendChild(overlay);
        },

        // Format date
        formatDate(dateString) {
            if (!dateString) return '';

            const date = new Date(dateString);
            if (isNaN(date.getTime())) {
                return dateString; // If date cannot be parsed, return original string
            }

            return date.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        },

        // Format time
        formatTime(timestamp) {
            if (!timestamp) return '';

            // Check if it's a numeric timestamp
            if (typeof timestamp === 'number') {
                const date = new Date(timestamp * 1000);
                return date.toLocaleTimeString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
            } else if (typeof timestamp === 'string') {
                // Try to parse date string
                try {
                    const date = new Date(timestamp);
                    if (!isNaN(date.getTime())) {
                        return date.toLocaleTimeString('zh-CN', {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit'
                        });
                    }
                } catch (e) {
                    console.warn('解析时间失败:', timestamp);
                }
            }

            // If all processing fails, return the original value
            return timestamp;
        },

        // Format message content
        formatMessage(content) {
            if (!content) return '';

            // Escape HTML
            let formattedContent = this.escapeHTML(content);

            // Add code highlighting
            formattedContent = this.formatCodeBlocks(formattedContent);

            // Convert URL to link
            formattedContent = this.formatLinks(formattedContent);

            return formattedContent;
        },

        // Escape HTML
        escapeHTML(html) {
            if (typeof html !== 'string') {
                return String(html);
            }
            const div = document.createElement('div');
            div.textContent = html;
            return div.innerHTML;
        },

        // Format code blocks
        formatCodeBlocks(text) {
            if (typeof text !== 'string') {
                return String(text);
            }

            // Regex matches code blocks ```language code ```
            const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g;

            return text.replace(codeBlockRegex, (match, language, code) => {
                language = language || 'plaintext';
                // Create highlighted code blocks
                return `<pre><code class="language-${language}">${this.escapeHTML(code)}</code></pre>`;
            });
        },

        // Format links
        formatLinks(text) {
            if (typeof text !== 'string') {
                return String(text);
            }

            const urlRegex = /(https?:\/\/[^\s]+)/g;
            return text.replace(urlRegex, url => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`);
        },

        // Format JSON data
        formatJson(jsonData) {
            if (!jsonData) return '';

            try {
                // If it's a string, try to parse
                if (typeof jsonData === 'string') {
                    const obj = JSON.parse(jsonData);
                    return JSON.stringify(obj, null, 2);
                } else {
                    // If already an object, format directly
                    return JSON.stringify(jsonData, null, 2);
                }
            } catch (e) {
                // If parsing fails, return original string
                console.warn('JSON解析失败:', e);
                return jsonData;
            }
        },

        // Apply code highlighting
        applyCodeHighlighting() {
            if (window.Prism) {
                Prism.highlightAll();
            }
        },

        // Hide loading animation
        hideLoader() {
            const loader = document.getElementById('page-loader');
            if (loader) {
                loader.classList.add('fade-out');
                setTimeout(() => {
                    loader.style.display = 'none';
                }, 500);
            }
        }
    }
});

// Mount Vue application
app.mount('#app');
