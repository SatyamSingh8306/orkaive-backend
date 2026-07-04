/**
 * Sidebar Widget
 * Sleek sidebar design with minimal aesthetics
 */

(function () {
    'use strict';

    const script = document.currentScript;
    const workflowId = script.getAttribute('data-workflow');
    const theme = script.getAttribute('data-theme') || 'light';

    if (!workflowId) {
        console.error('WorkflowChat: Missing data-workflow attribute');
        return;
    }

    const apiUrl = 'http://localhost:8000';

    // Inject CSS
    const css = `
    .sidebar-chat-container {
      position: fixed;
      top: 0;
      right: -400px;
      width: 400px;
      height: 100vh;
      background: ${theme === 'dark' ? '#111827' : 'white'};
      box-shadow: -5px 0 30px rgba(0, 0, 0, 0.1);
      z-index: 99999;
      display: flex;
      flex-direction: column;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      transition: right 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      border-left: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
    }

    .sidebar-chat-open {
      right: 0;
    }

    .sidebar-chat-overlay {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.5);
      z-index: 99998;
      display: none;
      animation: fadeIn 0.2s ease;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    .sidebar-chat-overlay.visible {
      display: block;
    }

    .sidebar-chat-header {
      padding: 24px;
      background: ${theme === 'dark' ? '#1f2937' : '#f8fafc'};
      border-bottom: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .sidebar-chat-title-container {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .sidebar-chat-icon {
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: 18px;
    }

    .sidebar-chat-title {
      font-size: 18px;
      font-weight: 600;
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      margin-bottom: 4px;
    }

    .sidebar-chat-status {
      font-size: 12px;
      color: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
    }

    .sidebar-chat-close {
      background: none;
      border: none;
      font-size: 24px;
      color: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
      cursor: pointer;
      padding: 8px;
      border-radius: 8px;
      transition: background 0.2s;
    }

    .sidebar-chat-close:hover {
      background: ${theme === 'dark' ? '#374151' : '#f1f5f9'};
    }

    .sidebar-chat-messages {
      flex: 1;
      padding: 24px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .sidebar-message {
      max-width: 85%;
      padding: 12px 16px;
      border-radius: 12px;
      line-height: 1.5;
      position: relative;
    }

    .sidebar-message.user {
      background: #4f46e5;
      color: white;
      align-self: flex-end;
      border-bottom-right-radius: 4px;
    }

    .sidebar-message.bot {
      background: ${theme === 'dark' ? '#374151' : '#f1f5f9'};
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      align-self: flex-start;
      border-bottom-left-radius: 4px;
    }

    .sidebar-message-time {
      font-size: 11px;
      opacity: 0.6;
      margin-top: 4px;
      text-align: right;
    }

    .sidebar-message.user .sidebar-message-time {
      color: rgba(255, 255, 255, 0.8);
    }

    .sidebar-message.bot .sidebar-message-time {
      color: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
    }

    .sidebar-typing {
      display: flex;
      gap: 6px;
      padding: 16px;
      background: ${theme === 'dark' ? '#374151' : '#f1f5f9'};
      border-radius: 12px;
      width: fit-content;
      align-self: flex-start;
      border-bottom-left-radius: 4px;
    }

    .sidebar-dot {
      width: 8px;
      height: 8px;
      background: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
      border-radius: 50%;
      animation: sidebarTyping 1.4s infinite ease-in-out;
    }

    .sidebar-dot:nth-child(2) { animation-delay: 0.2s; }
    .sidebar-dot:nth-child(3) { animation-delay: 0.4s; }

    @keyframes sidebarTyping {
      0%, 60%, 100% { transform: translateY(0); }
      30% { transform: translateY(-5px); }
    }

    .sidebar-chat-input-area {
      padding: 20px 24px;
      border-top: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
      background: ${theme === 'dark' ? '#1f2937' : '#f8fafc'};
    }

    .sidebar-input-container {
      position: relative;
      margin-bottom: 12px;
    }

    #sidebar-chat-input {
      width: 100%;
      padding: 14px 50px 14px 16px;
      border: 1px solid ${theme === 'dark' ? '#4b5563' : '#cbd5e1'};
      border-radius: 12px;
      background: ${theme === 'dark' ? '#111827' : 'white'};
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      font-size: 14px;
      outline: none;
      transition: border 0.2s, box-shadow 0.2s;
    }

    #sidebar-chat-input:focus {
      border-color: #4f46e5;
      box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
    }

    #sidebar-chat-send {
      position: absolute;
      right: 8px;
      top: 50%;
      transform: translateY(-50%);
      width: 36px;
      height: 36px;
      background: #4f46e5;
      color: white;
      border: none;
      border-radius: 10px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s;
    }

    #sidebar-chat-send:hover {
      background: #4338ca;
    }

    #sidebar-chat-send:disabled {
      background: ${theme === 'dark' ? '#4b5563' : '#cbd5e1'};
      cursor: not-allowed;
    }

    .sidebar-powered-by {
      text-align: center;
      font-size: 12px;
      color: ${theme === 'dark' ? '#9ca3af' : '#94a3b8'};
      padding-top: 12px;
      border-top: 1px solid ${theme === 'dark' ? '#374151' : '#e2e8f0'};
    }

    .sidebar-powered-by strong {
      color: ${theme === 'dark' ? '#818cf8' : '#4f46e5'};
      font-weight: 600;
    }

    .sidebar-chat-button {
      position: fixed;
      bottom: 30px;
      right: 30px;
      width: 56px;
      height: 56px;
      border-radius: 16px;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border: none;
      color: white;
      font-size: 22px;
      cursor: pointer;
      z-index: 99997;
      box-shadow: 0 8px 25px rgba(102, 126, 234, 0.3);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.3s ease;
    }

    .sidebar-chat-button:hover {
      transform: translateY(-2px);
      box-shadow: 0 12px 30px rgba(102, 126, 234, 0.4);
    }

    .sidebar-chat-button.open {
      right: 430px;
    }

    @media (max-width: 480px) {
      .sidebar-chat-container {
        width: 100%;
        right: -100%;
      }
      
      .sidebar-chat-open {
        right: 0;
      }
      
      .sidebar-chat-button.open {
        right: calc(100% + 30px);
      }
      
      .sidebar-message {
        max-width: 90%;
      }
    }
  `;

    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'sidebar-chat-overlay';
    document.body.appendChild(overlay);

    // Create chat container
    const chatHTML = `
    <div class="sidebar-chat-header">
      <div class="sidebar-chat-title-container">
        <div class="sidebar-chat-icon">🤖</div>
        <div>
          <div class="sidebar-chat-title">AI Assistant</div>
          <div class="sidebar-chat-status">Online • Ready to help</div>
        </div>
      </div>
      <button class="sidebar-chat-close" aria-label="Close chat">×</button>
    </div>
    
    <div class="sidebar-chat-messages">
      <div class="sidebar-message bot">
        Welcome! I'm here to assist you with your questions.
        <div class="sidebar-message-time">Just now</div>
      </div>
    </div>
    
    <div class="sidebar-chat-input-area">
      <div class="sidebar-input-container">
        <input 
          type="text" 
          id="sidebar-chat-input" 
          placeholder="Ask a question..."
          autocomplete="off"
        />
        <button id="sidebar-chat-send" aria-label="Send message">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
      <div class="sidebar-powered-by">
        Powered by <strong>Sasefied</strong>
      </div>
    </div>
  `;

    const chatContainer = document.createElement('div');
    chatContainer.className = 'sidebar-chat-container';
    chatContainer.innerHTML = chatHTML;
    document.body.appendChild(chatContainer);

    // Create sidebar button
    const sidebarButton = document.createElement('button');
    sidebarButton.className = 'sidebar-chat-button';
    sidebarButton.innerHTML = '💬';
    sidebarButton.title = 'Open AI Chat';
    document.body.appendChild(sidebarButton);

    // Get DOM elements
    const messagesContainer = chatContainer.querySelector('.sidebar-chat-messages');
    const input = chatContainer.querySelector('#sidebar-chat-input');
    const sendButton = chatContainer.querySelector('#sidebar-chat-send');
    const closeButton = chatContainer.querySelector('.sidebar-chat-close');

    let messages = [];
    let isLoading = false;

    function getCurrentTime() {
        return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function addMessage(text, sender, isTyping = false) {
        if (isTyping) {
            const typingDiv = document.createElement('div');
            typingDiv.className = 'sidebar-typing';
            typingDiv.innerHTML = `
        <div class="sidebar-dot"></div>
        <div class="sidebar-dot"></div>
        <div class="sidebar-dot"></div>
      `;
            messagesContainer.appendChild(typingDiv);
        } else {
            const typingIndicator = messagesContainer.querySelector('.sidebar-typing');
            if (typingIndicator) typingIndicator.remove();

            const messageDiv = document.createElement('div');
            messageDiv.className = `sidebar-message ${sender}`;

            const messageText = document.createElement('div');
            messageText.textContent = text;
            messageDiv.appendChild(messageText);

            const timeDiv = document.createElement('div');
            timeDiv.className = 'sidebar-message-time';
            timeDiv.textContent = getCurrentTime();
            messageDiv.appendChild(timeDiv);

            messagesContainer.appendChild(messageDiv);

            messages.push({ text, sender, time: getCurrentTime() });
        }

        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    async function sendMessage() {
        const message = input.value.trim();
        if (!message || isLoading) return;

        addMessage(message, 'user');
        input.value = '';
        sendButton.disabled = true;

        addMessage('', 'bot', true);
        isLoading = true;

        try {
            const response = await fetch(`${apiUrl}/api/workflows/${workflowId}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    workflow_id: workflowId,
                    messages: [{
                        role: 'user',
                        content: message,
                        timestamp: Date.now()
                    }],
                    stream: false,
                    temperature: 0.7
                })
            });

            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

            const data = await response.json();
            const reply = data.reply || data.response || data.content ||
                data.choices?.[0]?.message?.content || "I understand. Let me think about that.";

            addMessage(reply, 'bot');

        } catch (error) {
            console.error('API Error:', error);
            addMessage('Sorry, something went wrong. Please try again.', 'bot');
        } finally {
            isLoading = false;
            sendButton.disabled = false;
            input.focus();
        }
    }

    function toggleChat() {
        chatContainer.classList.toggle('sidebar-chat-open');
        overlay.classList.toggle('visible');
        sidebarButton.classList.toggle('open');
        if (chatContainer.classList.contains('sidebar-chat-open')) {
            input.focus();
        }
    }

    // Event Listeners
    sidebarButton.addEventListener('click', toggleChat);
    sendButton.addEventListener('click', sendMessage);
    closeButton.addEventListener('click', toggleChat);
    overlay.addEventListener('click', toggleChat);

    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    input.addEventListener('input', () => {
        sendButton.disabled = !input.value.trim();
    });

    // Add initial message
    addMessage('Welcome! I\'m here to assist you with your questions.', 'bot');

    // Export to window
    window.sidebarChat = {
        open: () => {
            chatContainer.classList.add('sidebar-chat-open');
            overlay.classList.add('visible');
            sidebarButton.classList.add('open');
            input.focus();
        },
        close: () => {
            chatContainer.classList.remove('sidebar-chat-open');
            overlay.classList.remove('visible');
            sidebarButton.classList.remove('open');
        },
        sendMessage,
        addMessage
    };

})();