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
        terms = request.form.get('terms')
        
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
    return render_template('user_agreement.html')

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
    """Страница профиля пользователя"""
    user = db.get_user_by_id(session['user_id'])
    friends = db.get_friends_with_status(session['user_id'])
    friend_requests = db.get_friend_requests(session['user_id'])
    
    # Считаем общее количество сообщений
    total_messages = 0  # Заглушка, можно добавить реальный подсчет
    
    return render_template('profile.html', 
                         user=user, 
                         friends_count=len(friends),
                         requests_count=len(friend_requests),
                         total_messages=total_messages)

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def profile_edit():
    """Страница редактирования профиля"""
    user = db.get_user_by_id(session['user_id'])
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        display_name = request.form.get('display_name', '').strip()
        bio = request.form.get('bio', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Обработка аватара
        avatar_file = request.files.get('avatar')
        avatar_path = None
        
        if avatar_file and avatar_file.filename:
            if allowed_file(avatar_file.filename, 'image'):
                filename = secure_filename(avatar_file.filename)
                ext = filename.rsplit('.', 1)[1].lower()
                unique_filename = f"avatar_{session['user_id']}_{uuid.uuid4().hex[:8]}.{ext}"
                
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], 'avatars', unique_filename)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                avatar_file.save(save_path)
                
                avatar_path = f"avatars/{unique_filename}"
                
                # Удаляем старый аватар, если он есть
                if user.get('avatar'):
                    old_avatar_path = os.path.join(app.config['UPLOAD_FOLDER'], user['avatar'])
                    if os.path.exists(old_avatar_path):
                        try:
                            os.remove(old_avatar_path)
                        except:
                            pass
            else:
                flash('Недопустимый формат изображения. Разрешены: PNG, JPG, JPEG, GIF', 'error')
                return redirect(url_for('profile_edit'))
        
        # Проверяем, не занят ли новый логин
        if username != user['username']:
            if db.get_user_by_username(username):
                flash('Этот логин уже занят', 'error')
                return redirect(url_for('profile_edit'))
        
        # Если меняем пароль
        if current_password or new_password or confirm_password:
            if not db.check_password(session['user_id'], current_password):
                flash('Неверный текущий пароль', 'error')
                return redirect(url_for('profile_edit'))
            
            if new_password != confirm_password:
                flash('Новые пароли не совпадают', 'error')
                return redirect(url_for('profile_edit'))
            
            if len(new_password) < 6:
                flash('Пароль должен быть не менее 6 символов', 'error')
                return redirect(url_for('profile_edit'))
            
            db.update_password(session['user_id'], new_password)
            flash('Пароль успешно изменен', 'success')
        
        # Обновляем информацию профиля
        updates = []
        if username != user['username']:
            db.update_username(session['user_id'], username)
            session['username'] = username
            updates.append('логин')
        
        db.update_profile_info(
            user_id=session['user_id'],
            display_name=display_name if display_name else None,
            bio=bio if bio else None,
            avatar=avatar_path
        )
        
        if avatar_path:
            updates.append('аватар')
        if display_name and display_name != user.get('display_name'):
            updates.append('отображаемое имя')
        if bio and bio != user.get('bio'):
            updates.append('информацию о себе')
        
        if updates:
            flash(f'Профиль успешно обновлен: {", ".join(updates)}', 'success')
        else:
            flash('Изменений не было', 'info')
        
        return redirect(url_for('profile'))
    
    return render_template('edit_profile.html', user=user)

@app.route('/friends')
@login_required
def friends_list():
    """Страница со списком друзей"""
    friends = db.get_friends_with_status(session['user_id'])
    
    for friend in friends:
        last_msg = db.get_last_message_preview(session['user_id'], friend['id'])
        friend['last_message'] = last_msg
    
    online_count = sum(1 for friend in friends if friend.get('status') == 'online')
    
    # ПОЛУЧАЕМ ЗАЯВКИ В ДРУЗЬЯ
    friend_requests = db.get_friend_requests(session['user_id'])
    
    return render_template('friends.html', 
                         friends=friends, 
                         online_count=online_count,
                         friend_requests=friend_requests)  # Добавляем заявки

@app.route('/friend-requests')
@login_required
def friend_requests_page():
    """Страница с заявками в друзья"""
    friend_requests = db.get_friend_requests(session['user_id'])
    return render_template('friend_requests.html', friend_requests=friend_requests)

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
    
    return redirect(url_for('friend_requests_page'))

@app.route('/remove_friend/<int:friend_id>')
@login_required
def remove_friend(friend_id):
    success = db.remove_friend(session['user_id'], friend_id)
    
    if success:
        flash('Пользователь удален из друзей', 'success')
    else:
        flash('Ошибка при удалении', 'error')
    
    return redirect(url_for('friends_list'))

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

# В app.py, маршрут /chat/<int:receiver_id>
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
    
    # Получаем сообщения
    messages = db.get_messages(session['user_id'], receiver_id)
    print(f"Messages found: {len(messages)}")  # Отладка
    
    for friend in friends:
        friend['unread_count'] = db.get_unread_count(session['user_id'], friend['id'])
        last_msg = db.get_last_message_preview(session['user_id'], friend['id'])
        friend['last_message'] = last_msg
        friend['active'] = (friend['id'] == receiver_id)
    
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
    
    sticker_id = request.form.get('sticker_id', '')
    image_file = request.files.get('image')
    
    message_id = None
    
    if sticker_id:
        message_id = db.save_message(session['user_id'], receiver_id, f"sticker:{sticker_id}", 'sticker')
    elif image_file and image_file.filename:
        if allowed_file(image_file.filename, 'image'):
            filename = secure_filename(image_file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            file_path = os.path.join('images', unique_filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], 'images', unique_filename)
            image_file.save(save_path)
            
            message_id = db.save_message(session['user_id'], receiver_id, 'Изображение', 'image', file_path)
        else:
            return jsonify({'success': False, 'error': 'Invalid file format'}), 400
    elif message:
        message_id = db.save_message(session['user_id'], receiver_id, message, 'text')
    
    if message_id:
        # Получаем сохраненное сообщение для немедленного отображения
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT m.id, m.sender_id, m.receiver_id, m.message, m.message_type, 
                   m.file_path, strftime('%Y-%m-%d %H:%M:%S', m.timestamp) as timestamp,
                   u.username as sender_name
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.id = ?
        ''', (message_id,))
        msg = cursor.fetchone()
        conn.close()
        
        if msg:
            return jsonify({
                'success': True,
                'message': {
                    'id': msg[0],
                    'sender_id': msg[1],
                    'receiver_id': msg[2],
                    'message': msg[3],
                    'message_type': msg[4],
                    'file_path': msg[5],
                    'timestamp': msg[6],
                    'sender_name': msg[7],
                    'is_own': True
                }
            })
    
    return redirect(url_for('chat_with', receiver_id=receiver_id))

@app.route('/upload_chat_image', methods=['POST'])
@login_required
def upload_chat_image():
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
        
        message_id = db.save_message(session['user_id'], receiver_id, 'Изображение', 'image', file_path)
        
        # Получаем сохраненное сообщение
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT m.id, m.sender_id, m.receiver_id, m.message, m.message_type, 
                   m.file_path, strftime('%Y-%m-%d %H:%M:%S', m.timestamp) as timestamp,
                   u.username as sender_name
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.id = ?
        ''', (message_id,))
        msg = cursor.fetchone()
        conn.close()
        
        if msg:
            return jsonify({
                'success': True,
                'file_path': file_path,
                'message': {
                    'id': msg[0],
                    'sender_id': msg[1],
                    'receiver_id': msg[2],
                    'message': msg[3],
                    'message_type': msg[4],
                    'file_path': msg[5],
                    'timestamp': msg[6],
                    'sender_name': msg[7],
                    'is_own': True
                }
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

@app.route('/friend/<int:friend_id>')
@login_required
def friend_profile(friend_id):
    """Страница профиля друга"""
    # Проверяем, что пользователь действительно друг
    friends = db.get_friends_with_status(session['user_id'])
    is_friend = any(friend['id'] == friend_id for friend in friends)
    
    if not is_friend:
        flash('Вы можете просматривать только профили своих друзей', 'error')
        return redirect(url_for('friends_list'))
    
    # Получаем информацию о друге
    friend = db.get_user_by_id(friend_id)
    
    if not friend:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('friends_list'))
    
    # Получаем дополнительную информацию
    friends_count = len(db.get_friends_with_status(friend_id))
    messages = db.get_messages(session['user_id'], friend_id)
    messages_count = len(messages)
    
    # Получаем последнее сообщение
    last_message = db.get_last_message_preview(session['user_id'], friend_id)
    friend['last_message'] = last_message
    
    # Вычисляем количество дней в MaxUltra
    days_ago = 0
    if friend.get('created_at'):
        try:
            created = datetime.strptime(friend['created_at'], '%Y-%m-%d %H:%M:%S')
            days_ago = (datetime.now() - created).days
        except:
            pass
    
    return render_template('friend_profile.html', 
                         friend=friend,
                         friends_count=friends_count,
                         messages_count=messages_count,
                         days_ago=days_ago)

@app.route('/update_online_status')
@login_required
def update_online_status():
    db.update_last_seen(session['user_id'])
    return jsonify({'status': 'ok'})

@app.route('/delete_message', methods=['POST'])
@login_required
def delete_message():
    """Удаление сообщения"""
    data = request.get_json()
    message_id = data.get('message_id')
    receiver_id = data.get('receiver_id')
    
    if not message_id or not receiver_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Проверяем, что пользователь является отправителем сообщения
    cursor.execute('''
        SELECT id FROM messages 
        WHERE id = ? AND sender_id = ?
    ''', (message_id, session['user_id']))
    
    if not cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    
    # Помечаем сообщение как удаленное (soft delete)
    cursor.execute('''
        UPDATE messages 
        SET message = 'Сообщение удалено', 
            message_type = 'deleted',
            file_path = NULL
        WHERE id = ?
    ''', (message_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/edit_message', methods=['POST'])
@login_required
def edit_message():
    """Редактирование сообщения"""
    data = request.get_json()
    message_id = data.get('message_id')
    new_text = data.get('new_text')
    receiver_id = data.get('receiver_id')
    
    if not message_id or not new_text or not receiver_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Проверяем, что пользователь является отправителем и сообщение текстовое
    cursor.execute('''
        SELECT id FROM messages 
        WHERE id = ? AND sender_id = ? AND message_type = 'text'
    ''', (message_id, session['user_id']))
    
    if not cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'Permission denied or wrong message type'}), 403
    
    # Обновляем сообщение
    cursor.execute('''
        UPDATE messages 
        SET message = ?
        WHERE id = ?
    ''', (new_text, message_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Создаем необходимые папки
    os.makedirs('static/uploads/images', exist_ok=True)
    os.makedirs('static/uploads/stickers', exist_ok=True)
    os.makedirs('static/uploads/avatars', exist_ok=True)
    os.makedirs('static/uploads/stickers/demo', exist_ok=True)
    
    # Проверяем и добавляем демо-стикеры при первом запуске
    if not os.path.exists('static/uploads/stickers/demo/initialized.txt'):
        with open('static/uploads/stickers/demo/initialized.txt', 'w') as f:
            f.write('Демо-стикеры инициализированы\n')
    
    app.run(host="0.0.0.0", debug=True, port=5000)