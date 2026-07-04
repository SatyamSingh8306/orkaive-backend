/**
 * Modern Floating Bubble Widget
 * Clean design with bubble animation
 */

(function () {
    'use strict';

    // Get configuration from script tag
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
    .bubble-chat-container {
      position: fixed;
      bottom: 100px;
      right: 25px;
      width: 380px;
      max-height: 500px;
      background: ${theme === 'dark' ? '#1f2937' : 'white'};
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
      z-index: 99999;
      display: none;
      flex-direction: column;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      overflow: hidden;
      border: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
    }

    .bubble-chat-open {
      display: flex;
      animation: slideUp 0.3s ease;
    }

    @keyframes slideUp {
      from {
        opacity: 0;
        transform: translateY(20px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .bubble-chat-header {
      padding: 18px 20px;
      background: ${theme === 'dark' ? '#111827' : '#4f46e5'};
      color: white;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .bubble-chat-title {
      font-size: 16px;
      font-weight: 600;
    }

    .bubble-chat-subtitle {
      font-size: 12px;
      opacity: 0.9;
      margin-top: 2px;
    }

    .bubble-chat-close {
      background: rgba(255, 255, 255, 0.2);
      border: none;
      width: 30px;
      height: 30px;
      border-radius: 50%;
      color: white;
      font-size: 18px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .bubble-chat-messages {
      flex: 1;
      padding: 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      min-height: 300px;
    }

    .bubble-message {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 14px;
      font-size: 14px;
      line-height: 1.4;
      animation: fadeIn 0.2s ease;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(5px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .bubble-message.user {
      background: #4f46e5;
      color: white;
      align-self: flex-end;
      border-bottom-right-radius: 4px;
    }

    .bubble-message.bot {
      background: ${theme === 'dark' ? '#374151' : '#f3f4f6'};
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      align-self: flex-start;
      border-bottom-left-radius: 4px;
    }

    .bubble-typing {
      display: flex;
      gap: 4px;
      padding: 12px;
      background: ${theme === 'dark' ? '#374151' : '#f3f4f6'};
      border-radius: 14px;
      width: fit-content;
      border-bottom-left-radius: 4px;
    }

    .bubble-dot {
      width: 6px;
      height: 6px;
      background: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
      border-radius: 50%;
      animation: bubbleTyping 1.4s infinite ease-in-out;
    }

    .bubble-dot:nth-child(2) { animation-delay: 0.2s; }
    .bubble-dot:nth-child(3) { animation-delay: 0.4s; }

    @keyframes bubbleTyping {
      0%, 60%, 100% { transform: translateY(0); }
      30% { transform: translateY(-4px); }
    }

    .bubble-chat-footer {
      padding: 15px 20px;
      border-top: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
      background: ${theme === 'dark' ? '#111827' : '#f9fafb'};
    }

    .bubble-input-container {
      display: flex;
      gap: 10px;
      margin-bottom: 8px;
    }

    #bubble-chat-input {
      flex: 1;
      padding: 10px 14px;
      border: 1px solid ${theme === 'dark' ? '#4b5563' : '#d1d5db'};
      border-radius: 10px;
      background: ${theme === 'dark' ? '#1f2937' : 'white'};
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      font-size: 14px;
      outline: none;
    }

    #bubble-chat-input:focus {
      border-color: #4f46e5;
    }

    #bubble-chat-send {
      padding: 10px 20px;
      background: #4f46e5;
      color: white;
      border: none;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.2s;
    }

    #bubble-chat-send:hover {
      background: #4338ca;
    }

    #bubble-chat-send:disabled {
      background: ${theme === 'dark' ? '#4b5563' : '#d1d5db'};
      cursor: not-allowed;
    }

    .bubble-powered-by {
      text-align: center;
      font-size: 11px;
      color: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
      padding-top: 8px;
      border-top: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
      margin-top: 8px;
    }

    .bubble-chat-button {
      position: fixed;
      bottom: 25px;
      right: 25px;
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border: none;
      color: white;
      font-size: 24px;
      cursor: pointer;
      z-index: 99998;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.3s ease;
    }

    .bubble-chat-button:hover {
      transform: scale(1.1);
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
    }

    .bubble-chat-button.pulse {
      animation: pulse 2s infinite;
    }

    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 rgba(102, 126, 234, 0.7); }
      70% { box-shadow: 0 0 0 10px rgba(102, 126, 234, 0); }
      100% { box-shadow: 0 0 0 0 rgba(102, 126, 234, 0); }
    }

    @media (max-width: 480px) {
      .bubble-chat-container {
        width: calc(100vw - 50px);
        right: 15px;
        bottom: 90px;
        max-height: 70vh;
      }
      
      .bubble-chat-button {
        right: 15px;
        bottom: 15px;
      }
    }
  `;

    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    // Create bubble button
    const bubbleButton = document.createElement('button');
    bubbleButton.className = 'bubble-chat-button pulse';
    bubbleButton.innerHTML = '💬';
    bubbleButton.title = 'Open AI Chat';
    document.body.appendChild(bubbleButton);

    // Create chat container
    const chatHTML = `
    <div class="bubble-chat-header">
      <div>
        <div class="bubble-chat-title">AI Assistant</div>
        <div class="bubble-chat-subtitle">Ask me anything</div>
      </div>
      <button class="bubble-chat-close" aria-label="Close chat">×</button>
    </div>
    
    <div class="bubble-chat-messages">
      <div class="bubble-message bot">
        Hi there! 👋 I'm your AI assistant. How can I help you today?
      </div>
    </div>
    
    <div class="bubble-chat-footer">
      <div class="bubble-input-container">
        <input 
          type="text" 
          id="bubble-chat-input" 
          placeholder="Type your message..."
          autocomplete="off"
        />
        <button id="bubble-chat-send">Send</button>
      </div>
      <div class="bubble-powered-by">Powered by Sasefied</div>
    </div>
  `;

    const chatContainer = document.createElement('div');
    chatContainer.className = 'bubble-chat-container';
    chatContainer.innerHTML = chatHTML;
    document.body.appendChild(chatContainer);

    // Get DOM elements
    const messagesContainer = chatContainer.querySelector('.bubble-chat-messages');
    const input = chatContainer.querySelector('#bubble-chat-input');
    const sendButton = chatContainer.querySelector('#bubble-chat-send');
    const closeButton = chatContainer.querySelector('.bubble-chat-close');

    let messages = [];
    let isLoading = false;

    // Add initial message
    messages.push({
        text: "Hi there! 👋 I'm your AI assistant. How can I help you today?",
        sender: 'bot'
    });

    function addMessage(text, sender, isTyping = false) {
        if (isTyping) {
            const typingDiv = document.createElement('div');
            typingDiv.className = 'bubble-typing';
            typingDiv.innerHTML = `
        <div class="bubble-dot"></div>
        <div class="bubble-dot"></div>
        <div class="bubble-dot"></div>
      `;
            messagesContainer.appendChild(typingDiv);
        } else {
            const typingIndicator = messagesContainer.querySelector('.bubble-typing');
            if (typingIndicator) typingIndicator.remove();

            const messageDiv = document.createElement('div');
            messageDiv.className = `bubble-message ${sender}`;
            messageDiv.textContent = text;
            messagesContainer.appendChild(messageDiv);

            messages.push({ text, sender });
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
                data.choices?.[0]?.message?.content || "Got it!";

            addMessage(reply, 'bot');

        } catch (error) {
            console.error('API Error:', error);
            addMessage('Sorry, I encountered an error. Please try again.', 'bot');
        } finally {
            isLoading = false;
            sendButton.disabled = false;
            input.focus();
        }
    }

    // Toggle chat visibility
    function toggleChat() {
        chatContainer.classList.toggle('bubble-chat-open');
        bubbleButton.classList.toggle('pulse');
        if (chatContainer.classList.contains('bubble-chat-open')) {
            input.focus();
        }
    }

    // Event Listeners
    bubbleButton.addEventListener('click', toggleChat);
    sendButton.addEventListener('click', sendMessage);
    closeButton.addEventListener('click', toggleChat);

    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    input.addEventListener('input', () => {
        sendButton.disabled = !input.value.trim();
    });

    // Export to window
    window.bubbleChat = {
        open: () => {
            chatContainer.classList.add('bubble-chat-open');
            bubbleButton.classList.remove('pulse');
            input.focus();
        },
        close: () => {
            chatContainer.classList.remove('bubble-chat-open');
            bubbleButton.classList.add('pulse');
        },
        sendMessage,
        addMessage
    };

})();