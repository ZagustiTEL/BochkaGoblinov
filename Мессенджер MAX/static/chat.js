// static/chat.js

let lastMessageId = 0;
let currentReceiverId = null;
let isPolling = false;

function scrollToBottom() {
    const container = document.getElementById('messages-container');
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) {
        // Если timestamp уже в формате времени
        if (typeof timestamp === 'string' && timestamp.includes(':')) {
            return timestamp.length > 5 ? timestamp.substring(11, 16) : timestamp;
        }
        return timestamp;
    }
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function loadNewMessages(receiverId) {
    if (!receiverId || receiverId !== currentReceiverId || isPolling) {
        return;
    }
    
    isPolling = true;
    
    fetch('/api/check_updates?receiver_id=' + receiverId + '&last_message_id=' + lastMessageId)
        .then(function(response) {
            return response.json();
        })
        .then(function(data) {
            if (data.new_messages && data.new_messages.length > 0) {
                const container = document.getElementById('messages-container');
                
                // Удаляем сообщение "Нет сообщений" если оно есть
                const noMessages = container.querySelector('.no-messages');
                if (noMessages) {
                    container.removeChild(noMessages);
                }
                
                let hasNewMessages = false;
                
                data.new_messages.forEach(function(msg) {
                    // Проверяем, есть ли уже такое сообщение
                    const existingMsg = container.querySelector(`[data-message-id="${msg.id}"]`);
                    if (existingMsg) {
                        return; // Пропускаем уже существующие сообщения
                    }
                    
                    hasNewMessages = true;
                    
                    const messageWrapper = document.createElement('div');
                    messageWrapper.className = 'message-wrapper ' + (msg.is_own ? 'own-message' : 'other-message');
                    messageWrapper.setAttribute('data-message-id', msg.id);
                    
                    const messageDiv = document.createElement('div');
                    messageDiv.className = 'message ' + (msg.is_own ? 'own' : 'other');
                    
                    let content = '';
                    if (msg.message_type === 'image' && msg.file_path) {
                        content = `<div class="message-image"><img src="/uploads/${msg.file_path}" alt="Изображение" style="max-width: 300px; border-radius: 10px;"></div>`;
                    } else if (msg.message_type === 'sticker') {
                        content = `<div class="message-sticker">${msg.message}</div>`;
                    } else {
                        content = `<div class="message-text">${msg.message}</div>`;
                    }
                    
                    messageDiv.innerHTML = `
                        ${!msg.is_own ? `<div class="message-sender">${msg.sender_name}</div>` : ''}
                        <div class="message-content">${content}</div>
                        <div class="message-time">
                            ${formatTime(msg.timestamp)}
                            ${msg.is_own ? '<span class="read-status">✓</span>' : ''}
                        </div>
                    `;
                    
                    messageWrapper.appendChild(messageDiv);
                    container.appendChild(messageWrapper);
                    
                    // Обновляем lastMessageId
                    if (msg.id > lastMessageId) {
                        lastMessageId = msg.id;
                    }
                });
                
                if (hasNewMessages) {
                    scrollToBottom();
                }
            }
            
            // Обновляем статус пользователя
            if (data.user_status) {
                updateUserStatus(data.user_status);
            }
            
            isPolling = false;
        })
        .catch(function(error) {
            console.error('Error:', error);
            isPolling = false;
        });
}

function updateUserStatus(status) {
    const statusBadge = document.getElementById('partner-status-badge');
    const statusText = document.getElementById('partner-status-text');
    
    if (statusBadge && statusText) {
        // Обновляем класс статуса
        statusBadge.className = 'status-badge status-' + status;
        
        // Обновляем текст статуса
        let statusHTML = '';
        if (status === 'online') {
            statusHTML = '<span class="online-dot"></span> В сети';
        } else if (status === 'recently') {
            statusHTML = '<span class="recently-dot"></span> Был(а) недавно';
        } else {
            statusHTML = '<span class="offline-dot"></span> Не в сети';
        }
        
        statusText.innerHTML = statusHTML;
    }
}

function updateOnlineStatus() {
    fetch('/update_online_status')
        .then(function(response) {
            return response.json();
        })
        .catch(function(error) {
            console.error('Error:', error);
        });
}

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
    scrollToBottom();
    
    // Получаем receiver_id из data-атрибута
    const chatContainer = document.querySelector('.chat-container');
    const receiverId = chatContainer ? parseInt(chatContainer.dataset.receiverId) : null;
    
    // Находим последнее сообщение и получаем его ID
    const lastMessage = document.querySelector('.message-wrapper:last-child');
    if (lastMessage) {
        const messageId = lastMessage.getAttribute('data-message-id');
        if (messageId) {
            lastMessageId = parseInt(messageId);
        } else {
            // Если нет data-message-id, получаем ID из базы данных через AJAX
            fetch('/api/get_last_message_id?receiver_id=' + receiverId)
                .then(response => response.json())
                .then(data => {
                    if (data.last_message_id) {
                        lastMessageId = data.last_message_id;
                    }
                });
        }
    }
    
    if (receiverId) {
        currentReceiverId = receiverId;
        
        // Проверяем новые сообщения каждые 3 секунды
        const checkInterval = setInterval(function() {
            if (currentReceiverId === receiverId && !isPolling) {
                loadNewMessages(receiverId);
            }
        }, 3000);
        
        // Фокус на поле ввода
        const messageInput = document.getElementById('message-input');
        if (messageInput) {
            messageInput.focus();
            
            // Отправка формы по Enter (но Shift+Enter для новой строки)
            const messageForm = document.getElementById('message-form');
            if (messageForm) {
                messageInput.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        messageForm.requestSubmit();
                    }
                });
            }
        }
        
        // При смене страницы останавливаем polling
        window.addEventListener('beforeunload', function() {
            clearInterval(checkInterval);
        });
    }
    
    // Обновляем статус каждую минуту
    setInterval(updateOnlineStatus, 60000);
    
    // При переходе на другой чат
    document.querySelectorAll('.friend-item').forEach(item => {
        item.addEventListener('click', function() {
            lastMessageId = 0;
            currentReceiverId = null;
            isPolling = false;
        });
    });
});

// Дополнительная функция для предотвращения двойной отправки
document.addEventListener('DOMContentLoaded', function() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const submitButton = form.querySelector('button[type="submit"]');
            if (submitButton) {
                submitButton.disabled = true;
                setTimeout(() => {
                    submitButton.disabled = false;
                }, 2000);
            }
        });
    });
});