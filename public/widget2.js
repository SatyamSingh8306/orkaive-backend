/**
 * Minimal Bottom Bar Widget
 * Ultra-minimal design that expands from bottom
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
    .minimal-chat-container {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      height: 60px;
      background: ${theme === 'dark' ? '#1f2937' : 'white'};
      border-top: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
      z-index: 99999;
      display: flex;
      align-items: center;
      padding: 0 20px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      transition: height 0.3s ease;
      overflow: hidden;
    }

    .minimal-chat-expanded {
      height: 70vh;
      flex-direction: column;
    }

    .minimal-chat-input-row {
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      height: 60px;
      flex-shrink: 0;
    }

    .minimal-chat-trigger {
      background: none;
      border: none;
      font-size: 20px;
      color: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
      cursor: pointer;
      padding: 8px;
      border-radius: 8px;
      transition: background 0.2s;
    }

    .minimal-chat-trigger:hover {
      background: ${theme === 'dark' ? '#374151' : '#f3f4f6'};
    }

    .minimal-chat-brand {
      font-size: 14px;
      font-weight: 500;
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      margin-right: auto;
    }

    #minimal-chat-input {
      flex: 1;
      padding: 12px 16px;
      border: 1px solid ${theme === 'dark' ? '#4b5563' : '#d1d5db'};
      border-radius: 10px;
      background: ${theme === 'dark' ? '#111827' : '#f9fafb'};
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      font-size: 14px;
      outline: none;
      transition: all 0.2s;
    }

    #minimal-chat-input:focus {
      border-color: #4f46e5;
      background: ${theme === 'dark' ? '#1f2937' : 'white'};
    }

    #minimal-chat-send {
      padding: 10px 20px;
      background: #4f46e5;
      color: white;
      border: none;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.2s;
      white-space: nowrap;
    }

    #minimal-chat-send:hover {
      background: #4338ca;
    }

    #minimal-chat-send:disabled {
      background: ${theme === 'dark' ? '#4b5563' : '#d1d5db'};
      cursor: not-allowed;
    }

    .minimal-chat-messages {
      flex: 1;
      width: 100%;
      padding: 20px;
      overflow-y: auto;
      display: none;
      flex-direction: column;
      gap: 12px;
    }

    .minimal-chat-expanded .minimal-chat-messages {
      display: flex;
    }

    .minimal-message {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 14px;
      line-height: 1.4;
    }

    .minimal-message.user {
      background: #4f46e5;
      color: white;
      align-self: flex-end;
      margin-left: auto;
    }

    .minimal-message.bot {
      background: ${theme === 'dark' ? '#374151' : '#f3f4f6'};
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      align-self: flex-start;
    }

    .minimal-typing {
      display: flex;
      gap: 4px;
      padding: 12px;
      background: ${theme === 'dark' ? '#374151' : '#f3f4f6'};
      border-radius: 12px;
      width: fit-content;
    }

    .minimal-dot {
      width: 6px;
      height: 6px;
      background: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
      border-radius: 50%;
      animation: minimalTyping 1.4s infinite ease-in-out;
    }

    .minimal-dot:nth-child(2) { animation-delay: 0.2s; }
    .minimal-dot:nth-child(3) { animation-delay: 0.4s; }

    @keyframes minimalTyping {
      0%, 60%, 100% { transform: translateY(0); }
      30% { transform: translateY(-4px); }
    }

    .minimal-chat-footer {
      padding: 12px 20px;
      border-top: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
      font-size: 11px;
      color: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
      text-align: center;
      width: 100%;
      display: none;
    }

    .minimal-chat-expanded .minimal-chat-footer {
      display: block;
    }

    .minimal-chat-footer a {
      color: ${theme === 'dark' ? '#818cf8' : '#4f46e5'};
      text-decoration: none;
    }

    .minimal-chat-footer a:hover {
      text-decoration: underline;
    }

    @media (max-width: 768px) {
      .minimal-chat-container {
        height: 50px;
        padding: 0 15px;
      }
      
      .minimal-chat-expanded {
        height: 60vh;
      }
      
      .minimal-chat-brand {
        font-size: 13px;
      }
      
      #minimal-chat-input {
        padding: 10px 14px;
        font-size: 13px;
      }
      
      #minimal-chat-send {
        padding: 8px 16px;
        font-size: 13px;
      }
      
      .minimal-chat-messages {
        padding: 15px;
      }
    }

    @media (max-width: 480px) {
      .minimal-chat-trigger {
        display: none;
      }
      
      .minimal-chat-expanded {
        height: 80vh;
      }
    }
  `;

    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    // Create chat container
    const chatHTML = `
    <div class="minimal-chat-input-row">
      <button class="minimal-chat-trigger" aria-label="Toggle chat">💬</button>
      <div class="minimal-chat-brand">AI Assistant</div>
      <input 
        type="text" 
        id="minimal-chat-input" 
        placeholder="Ask me anything..."
        autocomplete="off"
      />
      <button id="minimal-chat-send">Send</button>
    </div>
    
    <div class="minimal-chat-messages">
      <div class="minimal-message bot">
        Hi! I'm here to help. Ask me anything.
      </div>
    </div>
    
    <div class="minimal-chat-footer">
      Powered by <a href="https://sasefied.com" target="_blank" rel="noopener">Sasefied</a>
    </div>
  `;

    const chatContainer = document.createElement('div');
    chatContainer.className = 'minimal-chat-container';
    chatContainer.innerHTML = chatHTML;
    document.body.appendChild(chatContainer);

    // Get DOM elements
    const messagesContainer = chatContainer.querySelector('.minimal-chat-messages');
    const input = chatContainer.querySelector('#minimal-chat-input');
    const sendButton = chatContainer.querySelector('#minimal-chat-send');
    const toggleButton = chatContainer.querySelector('.minimal-chat-trigger');

    let messages = [];
    let isLoading = false;

    function addMessage(text, sender, isTyping = false) {
        if (isTyping) {
            const typingDiv = document.createElement('div');
            typingDiv.className = 'minimal-typing';
            typingDiv.innerHTML = `
        <div class="minimal-dot"></div>
        <div class="minimal-dot"></div>
        <div class="minimal-dot"></div>
      `;
            messagesContainer.appendChild(typingDiv);
        } else {
            const typingIndicator = messagesContainer.querySelector('.minimal-typing');
            if (typingIndicator) typingIndicator.remove();

            const messageDiv = document.createElement('div');
            messageDiv.className = `minimal-message ${sender}`;
            messageDiv.textContent = text;
            messagesContainer.appendChild(messageDiv);

            messages.push({ text, sender });
        }

        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    async function sendMessage() {
        const message = input.value.trim();
        if (!message || isLoading) return;

        // Expand if not already expanded
        if (!chatContainer.classList.contains('minimal-chat-expanded')) {
            chatContainer.classList.add('minimal-chat-expanded');
        }

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
                data.choices?.[0]?.message?.content || "Thanks for your question!";

            addMessage(reply, 'bot');

        } catch (error) {
            console.error('API Error:', error);
            addMessage('Sorry, an error occurred.', 'bot');
        } finally {
            isLoading = false;
            sendButton.disabled = false;
            input.focus();
        }
    }

    function toggleChat() {
        chatContainer.classList.toggle('minimal-chat-expanded');
        if (chatContainer.classList.contains('minimal-chat-expanded')) {
            input.focus();
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    }

    // Event Listeners
    toggleButton.addEventListener('click', toggleChat);
    sendButton.addEventListener('click', sendMessage);

    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    input.addEventListener('input', () => {
        sendButton.disabled = !input.value.trim();
    });

    // Expand chat when input is focused (for mobile)
    input.addEventListener('focus', () => {
        if (!chatContainer.classList.contains('minimal-chat-expanded')) {
            chatContainer.classList.add('minimal-chat-expanded');
        }
    });

    // Add initial message
    addMessage('Hi! I\'m here to help. Ask me anything.', 'bot');

    // Export to window
    window.minimalChat = {
        expand: () => {
            chatContainer.classList.add('minimal-chat-expanded');
            input.focus();
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        },
        collapse: () => {
            chatContainer.classList.remove('minimal-chat-expanded');
        },
        sendMessage,
        addMessage
    };

})();