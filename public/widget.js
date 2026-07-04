/**
 * Full-Screen Workflow Chat Widget
 * Simple implementation with automatic opening
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

  // API URL - adjust this to your server URL
  const apiUrl = 'http://localhost:8000'; // Change this to your API URL

  // Inject CSS
  const css = `
    #workflow-chat-overlay {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: ${theme === 'dark' ? '#111827' : '#ffffff'};
      z-index: 99999;
      display: flex;
      flex-direction: column;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    .workflow-chat-header {
      padding: 20px;
      background: ${theme === 'dark' ? '#1f2937' : '#f3f4f6'};
      border-bottom: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .workflow-chat-title {
      font-size: 20px;
      font-weight: 600;
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
    }

    .workflow-chat-close {
      background: none;
      border: none;
      font-size: 24px;
      color: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
      cursor: pointer;
      padding: 5px 10px;
      border-radius: 5px;
    }

    .workflow-chat-close:hover {
      background: ${theme === 'dark' ? '#374151' : '#e5e7eb'};
    }

    .workflow-chat-messages {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 15px;
    }

    .workflow-message {
      max-width: 80%;
      padding: 12px 16px;
      border-radius: 12px;
      word-wrap: break-word;
    }

    .workflow-message.user {
      background: #4f46e5;
      color: white;
      align-self: flex-end;
      border-bottom-right-radius: 4px;
    }

    .workflow-message.bot {
      background: ${theme === 'dark' ? '#374151' : '#f3f4f6'};
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      align-self: flex-start;
      border-bottom-left-radius: 4px;
    }

    .workflow-message.error {
      background: #fee2e2;
      color: #991b1b;
      align-self: center;
      text-align: center;
      max-width: 90%;
    }

    .typing-indicator {
      display: flex;
      gap: 5px;
      padding: 12px 16px;
      background: ${theme === 'dark' ? '#374151' : '#f3f4f6'};
      border-radius: 12px;
      width: fit-content;
      border-bottom-left-radius: 4px;
    }

    .typing-dot {
      width: 8px;
      height: 8px;
      background: ${theme === 'dark' ? '#9ca3af' : '#6b7280'};
      border-radius: 50%;
      animation: typing 1.4s infinite ease-in-out;
    }

    .typing-dot:nth-child(2) { animation-delay: 0.2s; }
    .typing-dot:nth-child(3) { animation-delay: 0.4s; }

    @keyframes typing {
      0%, 60%, 100% { transform: translateY(0); }
      30% { transform: translateY(-6px); }
    }

    .workflow-chat-input-area {
      padding: 20px;
      background: ${theme === 'dark' ? '#1f2937' : '#f3f4f6'};
      border-top: 1px solid ${theme === 'dark' ? '#374151' : '#e5e7eb'};
    }

    .workflow-chat-input-container {
      display: flex;
      gap: 10px;
      max-width: 800px;
      margin: 0 auto;
    }

    #workflow-chat-input {
      flex: 1;
      padding: 12px 16px;
      border: 1px solid ${theme === 'dark' ? '#4b5563' : '#d1d5db'};
      border-radius: 8px;
      background: ${theme === 'dark' ? '#111827' : 'white'};
      color: ${theme === 'dark' ? 'white' : '#1f2937'};
      font-size: 16px;
      outline: none;
    }

    #workflow-chat-input:focus {
      border-color: #4f46e5;
      box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
    }

    #workflow-chat-send {
      padding: 12px 24px;
      background: #4f46e5;
      color: white;
      border: none;
      border-radius: 8px;
      font-size: 16px;
      font-weight: 500;
      cursor: pointer;
    }

    #workflow-chat-send:hover {
      background: #4338ca;
    }

    #workflow-chat-send:disabled {
      background: #9ca3af;
      cursor: not-allowed;
    }

    @media (max-width: 768px) {
      .workflow-chat-messages {
        padding: 15px;
      }
      
      .workflow-chat-input-area {
        padding: 15px;
      }
      
      .workflow-message {
        max-width: 90%;
      }
    }
  `;

  // Create and inject styles
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  // Create HTML structure
  const chatHTML = `
    <div class="workflow-chat-header">
      <div class="workflow-chat-title">AI Assistant</div>
      <button class="workflow-chat-close" aria-label="Close chat">✕</button>
    </div>
    
    <div class="workflow-chat-messages">
      <div class="workflow-message bot">
        Hello! I'm your AI assistant. How can I help you today?
      </div>
    </div>
    
    <div class="workflow-chat-input-area">
      <div class="workflow-chat-input-container">
        <input 
          type="text" 
          id="workflow-chat-input" 
          placeholder="Type your message here..."
          autocomplete="off"
        />
        <button id="workflow-chat-send">Send</button>
      </div>
    </div>
  `;

  // Create overlay container
  const overlay = document.createElement('div');
  overlay.id = 'workflow-chat-overlay';
  overlay.innerHTML = chatHTML;
  document.body.appendChild(overlay);

  // Get DOM elements
  const messagesContainer = overlay.querySelector('.workflow-chat-messages');
  const input = overlay.querySelector('#workflow-chat-input');
  const sendButton = overlay.querySelector('#workflow-chat-send');
  const closeButton = overlay.querySelector('.workflow-chat-close');

  // Chat state
  let messages = [];
  let isLoading = false;

  // Add initial message
  messages.push({
    text: "Hello! I'm your AI assistant. How can I help you today?",
    sender: 'bot'
  });

  // Helper function to add message
  function addMessage(text, sender, isTyping = false) {
    if (isTyping) {
      // Add typing indicator
      const typingDiv = document.createElement('div');
      typingDiv.className = 'typing-indicator';
      typingDiv.innerHTML = `
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      `;
      messagesContainer.appendChild(typingDiv);
    } else {
      // Remove typing indicator if exists
      const typingIndicator = messagesContainer.querySelector('.typing-indicator');
      if (typingIndicator) {
        typingIndicator.remove();
      }

      // Add message
      const messageDiv = document.createElement('div');
      messageDiv.className = `workflow-message ${sender}`;
      messageDiv.textContent = text;
      messagesContainer.appendChild(messageDiv);

      // Save to messages array
      messages.push({ text, sender });
    }

    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // Helper function to show error
  function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'workflow-message error';
    errorDiv.textContent = message;
    messagesContainer.appendChild(errorDiv);
    console.error('Chat Error:', message);

    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // Send message to API
  async function sendMessage() {
    const message = input.value.trim();

    if (!message || isLoading) return;

    // Add user message
    addMessage(message, 'user');
    input.value = '';
    sendButton.disabled = true;

    // Show typing indicator
    addMessage('', 'bot', true);
    isLoading = true;

    try {
      const response = await fetch(`${apiUrl}/api/workflows/${workflowId}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
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

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      // Get response text (adjust based on your API response structure)
      const reply = data.reply ||
        data.response ||
        data.content ||
        data.choices?.[0]?.message?.content ||
        "I received your message but couldn't generate a proper response.";

      // Add bot response
      addMessage(reply, 'bot');

    } catch (error) {
      console.error('API Error:', error);
      showError(error.name === 'TypeError' ?
        'Network error. Please check your connection.' :
        'Sorry, something went wrong. Please try again.');
    } finally {
      isLoading = false;
      sendButton.disabled = false;
      input.focus();
    }
  }

  // Event Listeners
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

  closeButton.addEventListener('click', () => {
    overlay.style.display = 'none';
    document.body.style.overflow = ''; // Restore scrolling
  });

  // Focus input on load
  setTimeout(() => {
    input.focus();
  }, 100);

  // Prevent body scrolling when chat is open
  document.body.style.overflow = 'hidden';

  // Add escape key to close
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      overlay.style.display = 'none';
      document.body.style.overflow = '';
    }
  });

  // Export chat instance to window
  window.workflowChat = {
    close: () => {
      overlay.style.display = 'none';
      document.body.style.overflow = '';
    },
    open: () => {
      overlay.style.display = 'flex';
      document.body.style.overflow = 'hidden';
      input.focus();
    },
    sendMessage,
    addMessage
  };

})();