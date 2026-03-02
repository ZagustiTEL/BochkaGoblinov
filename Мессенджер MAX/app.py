from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory
from database import Database
from functools import wraps
import os
from werkzeug.utils import secure_filename
import uuid
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['ALLOWED_STICKER_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

db = Database()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        db.update_last_seen(session['user_id'])
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename, file_type='image'):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if file_type == 'image':
        return ext in app.config['ALLOWED_IMAGE_EXTENSIONS']
    elif file_type == 'sticker':
        return ext in app.config['ALLOWED_STICKER_EXTENSIONS']
    return False

@app.route('/policy')
def policy():
    """Страница пользовательского соглашения"""
    return render_template('pol.html')

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('chat'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        terms = request.form.get('terms')  # Получаем значение чекбокса
        
        # Проверяем, принято ли соглашение
        if not terms:
            return render_template('register.html', error='Необходимо принять Пользовательское соглашение')
        
        if db.register_user(username, password):
            flash('Регистрация успешна! Теперь вы можете войти.', 'success')
            return redirect(url_for('login'))
        else:
            return render_template('register.html', error='Пользователь уже существует')
    
    return render_template('register.html')
    
@app.route('/user-agreement')
def user_agreement():
    return render_template('user_agreement.html')  # или p1.html

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = db.authenticate_user(username, password)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['unique_nickname'] = user['unique_nickname']
            flash('Вход выполнен успешно!', 'success')
            return redirect(url_for('chat'))
        else:
            return render_template('login.html', error='Неверные данные')
    
    return render_template('login.html')

@app.route('/profile')
@login_required
def profile():
    user = db.get_user_by_id(session['user_id'])
    friend_requests = db.get_friend_requests(session['user_id'])
    friends = db.get_friends_with_status(session['user_id'])
    
    return render_template('profile.html', 
                         user=user, 
                         friend_requests=friend_requests,
                         friends=friends)

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    nickname = request.form.get('nickname', '').strip()
    
    if not nickname:
        flash('Введите ник пользователя', 'error')
        return redirect(url_for('profile'))
    
    if not nickname.startswith('@'):
        nickname = f"@{nickname}"
    
    result = db.add_friend_request(session['user_id'], nickname)
    
    if result['success']:
        flash(result['message'], 'success')
    else:
        flash(result['error'], 'error')
    
    return redirect(url_for('profile'))

@app.route('/respond_friend_request/<int:request_id>/<action>')
@login_required
def respond_friend_request(request_id, action):
    if action not in ['accept', 'reject']:
        flash('Неверное действие', 'error')
        return redirect(url_for('profile'))
    
    result = db.respond_to_friend_request(request_id, session['user_id'], action)
    
    if result['success']:
        flash(result['message'], 'success')
    else:
        flash(result['error'], 'error')
    
    return redirect(url_for('profile'))

@app.route('/remove_friend/<int:friend_id>')
@login_required
def remove_friend(friend_id):
    success = db.remove_friend(session['user_id'], friend_id)
    
    if success:
        flash('Пользователь удален из друзей', 'success')
    else:
        flash('Ошибка при удалении', 'error')
    
    return redirect(url_for('profile'))

@app.route('/search_users')
@login_required
def search_users():
    query = request.args.get('q', '').strip()
    users = []
    
    if query:
        users = db.get_all_users(exclude_id=session['user_id'])
        users = [user for user in users if query.lower() in user['username'].lower() or query.lower() in user['unique_nickname'].lower()]
    
    return render_template('search_users.html', users=users, query=query)

@app.route('/chat')
@login_required
def chat():
    friends = db.get_friends_with_status(session['user_id'])
    
    for friend in friends:
        friend['unread_count'] = db.get_unread_count(session['user_id'], friend['id'])
        last_msg = db.get_last_message_preview(session['user_id'], friend['id'])
        friend['last_message'] = last_msg
    
    # Упрощенная сортировка без ошибок
    def get_sort_key(friend):
        unread = -friend.get('unread_count', 0)
        
        if friend.get('status') == 'online':
            status = 0
        elif friend.get('status') == 'recently':
            status = 1
        else:
            status = 2
        
        return (unread, status)
    
    friends.sort(key=get_sort_key)
    
    stickers = db.get_stickers()
    
    return render_template('chat.html', friends=friends, stickers=stickers)

@app.route('/chat/<int:receiver_id>')
@login_required
def chat_with(receiver_id):
    receiver = db.get_user_by_id(receiver_id)
    if not receiver:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('chat'))
    
    friends = db.get_friends_with_status(session['user_id'])
    is_friend = any(friend['id'] == receiver_id for friend in friends)
    
    if not is_friend:
        flash('Вы можете писать только друзьям', 'error')
        return redirect(url_for('chat'))
    
    db.mark_messages_as_read(session['user_id'], receiver_id)
    
    messages = db.get_messages(session['user_id'], receiver_id)
    
    for friend in friends:
        friend['unread_count'] = db.get_unread_count(session['user_id'], friend['id'])
        last_msg = db.get_last_message_preview(session['user_id'], friend['id'])
        friend['last_message'] = last_msg
        friend['active'] = (friend['id'] == receiver_id)
    
    # Упрощенная сортировка для списка друзей в чате
    def get_sort_key(friend):
        unread = -friend.get('unread_count', 0)
        
        if friend.get('status') == 'online':
            status = 0
        elif friend.get('status') == 'recently':
            status = 1
        else:
            status = 2
        
        return (unread, status)
    
    friends.sort(key=get_sort_key)
    
    stickers = db.get_stickers()
    
    return render_template('chat.html', 
                         receiver=receiver,
                         messages=messages,
                         friends=friends,
                         stickers=stickers)

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    receiver_id = request.form['receiver_id']
    message = request.form.get('message', '').strip()
    
    # Обработка стикеров
    sticker_id = request.form.get('sticker_id', '')
    
    # Обработка изображений
    image_file = request.files.get('image')
    
    if sticker_id:
        # Отправка стикера
        db.save_message(session['user_id'], receiver_id, f"sticker:{sticker_id}", 'sticker')
    elif image_file and image_file.filename:
        # Отправка изображения
        if allowed_file(image_file.filename, 'image'):
            filename = secure_filename(image_file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            file_path = os.path.join('images', unique_filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], 'images', unique_filename)
            image_file.save(save_path)
            
            db.save_message(session['user_id'], receiver_id, 'Изображение', 'image', file_path)
        else:
            flash('Недопустимый формат изображения', 'error')
    elif message:
        # Отправка текстового сообщения
        db.save_message(session['user_id'], receiver_id, message, 'text')
    
    return redirect(url_for('chat_with', receiver_id=receiver_id))

@app.route('/upload_image', methods=['POST'])
@login_required
def upload_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['image']
    receiver_id = request.form.get('receiver_id')
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file and allowed_file(file.filename, 'image'):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join('images', unique_filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], 'images', unique_filename)
        file.save(save_path)
        
        db.save_message(session['user_id'], receiver_id, 'Изображение', 'image', file_path)
        
        return jsonify({
            'success': True,
            'file_path': file_path,
            'message': 'Изображение отправлено'
        })
    
    return jsonify({'error': 'Invalid file format'}), 400

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/get_stickers')
@login_required
def get_stickers():
    stickers = db.get_stickers()
    return jsonify({'stickers': stickers})

@app.route('/api/check_updates')
@login_required
def check_updates():
    receiver_id = request.args.get('receiver_id', type=int)
    last_message_id = request.args.get('last_message_id', 0, type=int)
    
    if not receiver_id:
        return jsonify({'new_messages': [], 'user_status': 'offline'})
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Получаем только новые сообщения с ID больше last_message_id
    cursor.execute('''
        SELECT m.id, m.sender_id, m.receiver_id, m.message, m.message_type, m.file_path, 
               strftime('%Y-%m-%d %H:%M:%S', m.timestamp) as timestamp, u.username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE ((m.sender_id = ? AND m.receiver_id = ?) 
           OR (m.sender_id = ? AND m.receiver_id = ?))
           AND m.id > ?
        ORDER BY m.timestamp
    ''', (session['user_id'], receiver_id, receiver_id, session['user_id'], last_message_id))
    
    new_messages = cursor.fetchall()
    conn.close()
    
    formatted_messages = []
    for msg in new_messages:
        formatted_messages.append({
            'id': msg[0],
            'sender_id': msg[1],
            'receiver_id': msg[2],
            'message': msg[3],
            'message_type': msg[4],
            'file_path': msg[5],
            'timestamp': msg[6],
            'sender_name': msg[7],
            'is_own': msg[1] == session['user_id']
        })
    
    status = db.get_user_status(receiver_id)
    
    return jsonify({
        'new_messages': formatted_messages,
        'user_status': status
    })

@app.route('/faq')
def faq():
    """Страница часто задаваемых вопросов"""
    return render_template('faq.html')

@app.route('/api/get_last_message_id')
@login_required
def get_last_message_id():
    receiver_id = request.args.get('receiver_id', type=int)
    
    if not receiver_id:
        return jsonify({'last_message_id': 0})
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT MAX(id) FROM messages 
        WHERE (sender_id = ? AND receiver_id = ?) 
           OR (sender_id = ? AND receiver_id = ?)
    ''', (session['user_id'], receiver_id, receiver_id, session['user_id']))
    
    result = cursor.fetchone()
    conn.close()
    
    last_message_id = result[0] if result[0] else 0
    
    return jsonify({'last_message_id': last_message_id})

@app.route('/update_online_status')
@login_required
def update_online_status():
    db.update_last_seen(session['user_id'])
    return jsonify({'status': 'ok'})

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Создаем необходимые папки
    os.makedirs('static/uploads/stickers/demo', exist_ok=True)
    
    # Проверяем и добавляем демо-стикеры при первом запуске
    if not os.path.exists('static/uploads/stickers/demo/initialized.txt'):
        # Создаем демо стикеры
        demo_stickers = [
            ('like', '👍', 'Лайк', 'reactions'),
            ('heart', '❤️', 'Сердечко', 'reactions'),
            ('laugh', '😂', 'Смех', 'reactions'),
            ('wow', '😮', 'Удивление', 'reactions'),
            ('sad', '😢', 'Грусть', 'reactions'),
            ('fire', '🔥', 'Огонь', 'reactions'),
            ('party', '🎉', 'Праздник', 'reactions'),
            ('poop', '💩', 'Какашка', 'funny'),
            ('hi', '👋', 'Привет', 'greetings'),
            ('ok', '✅', 'Готово', 'actions'),
            ('no', '❌', 'Отмена', 'actions'),
            ('message', '💬', 'Сообщение', 'actions'),
            ('eyes', '👀', 'Смотрю', 'reactions'),
            ('think', '🤔', 'Думаю', 'reactions'),
            ('celebration', '🥳', 'Веселье', 'reactions')
        ]
        
        for emoji, emoji_char, name, category in demo_stickers:
            # В реальном проекте здесь должен быть код для сохранения изображений стикеров
            # Пока используем эмодзи как file_path
            pass
        
        # Создаем файл-маркер, что демо-стикеры добавлены
        with open('static/uploads/stickers/demo/initialized.txt', 'w') as f:
            f.write('Демо-стикеры инициализированы\n')
    
    app.run(host="0.0.0.0", debug=True, port=5000)
