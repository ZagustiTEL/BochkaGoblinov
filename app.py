from flask import Flask, render_template, request, jsonify, redirect, url_for, make_response, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import time
from cryptography.fernet import Fernet
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 'your-jwt-secret-key-here'
app.config['SECRET_KEY'] = 'your-flask-secret-key-here'

app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_SECURE'] = False
app.config['JWT_COOKIE_CSRF_PROTECT'] = False
app.config['JWT_ACCESS_COOKIE_NAME'] = 'access_token'

jwt = JWTManager(app)
socketio = SocketIO(app, cors_allowed_origins="*")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'data1.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static/uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'docx', 'zip'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ENCRYPTION_KEY = b'uX6-f1vE0zP_kYQ-jD2pL_9a_N3b_C4d_E5f_G6h_I7='
cipher = Fernet(ENCRYPTION_KEY)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS

def init_db():
    conn = get_db()

    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            last_seen INTEGER,
            nickname TEXT
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS friends (
            user_id INTEGER,
            friend_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (friend_id) REFERENCES users (id)
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            text TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users (id),
            FOREIGN KEY (receiver_id) REFERENCES users (id)
        )
    ''')

    conn.commit()
    conn.close()

with app.app_context():
    init_db()

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    u, p = data['username'], data['password']
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (u,)).fetchone()
    conn.close()
    if user and check_password_hash(user['password'], p):
        token = create_access_token(identity=user['id'])
        conn = get_db()
        conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (int(time.time()), user['id']))
        conn.commit()
        conn.close()
        return jsonify({"token": token, "user_id": user['id'], "username": user['username']})
    return jsonify({"error": "Неверные логин/пароль"}), 401

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    u, p = data['username'], generate_password_hash(data['password'])
    conn = get_db()
    try:
        conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (u, p))
        uid = conn.lastrowid
        conn.execute('INSERT INTO friends (user_id, friend_id) VALUES (?, ?)', (uid, uid))
        conn.commit()
        conn.close()
        return jsonify({"message": "Пользователь создан"}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Пользователь с таким именем уже существует"}), 409

@app.route('/api/friends/<int:user_id>', methods=['GET'])
@jwt_required()
def get_friends(user_id):
    conn = get_db()
    friends_rows = conn.execute('''
        SELECT u.id, u.username FROM users u
        JOIN friends f ON u.id = f.friend_id
        WHERE f.user_id = ?
    ''', (user_id,)).fetchall()
    conn.close()
    friends = [{'id': r['id'], 'username': r['username']} for r in friends_rows]
    return jsonify({"friends": friends})

@app.route('/api/messages/<int:friend_id>', methods=['GET'])
@jwt_required()
def get_messages(friend_id):
    user_id = get_jwt_identity()
    conn = get_db()
    friend = conn.execute('SELECT username, last_seen FROM users WHERE id = ?', (friend_id,)).fetchone()
    is_online = (int(time.time()) - (friend['last_seen'] or 0)) < 60
    rows = conn.execute('''
        SELECT id, sender_id, text, timestamp FROM messages
        WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
        ORDER BY timestamp ASC
    ''', (user_id, friend_id, friend_id, user_id)).fetchall()
    conn.close()
    msgs = []
    for r in rows:
        try:
            txt = cipher.decrypt(r['text'].encode()).decode()
        except:
            txt = "[Ошибка расшифровки]"
        msgs.append({
            "id": r['id'],
            "text": txt,
            "time": r['timestamp'][11:16],
            "is_me": r['sender_id'] == user_id
        })
    return jsonify({
        "messages": msgs,
        "friend_name": friend['username'],
        "online": is_online
    })

@app.route('/api/send', methods=['POST'])
@jwt_required()
def send():
    data = request.get_json()
    enc_text = cipher.encrypt(data['text'].encode()).decode()
    user_id = get_jwt_identity()
    conn = get_db()
    conn.execute('INSERT INTO messages (sender_id, receiver_id, text) VALUES (?, ?, ?)',
                (user_id, data['receiver_id'], enc_text))
    conn.commit()
    conn.close()
    room = f"chat_{data['receiver_id']}"
    socketio.emit('new_message', {
        'sender_id': user_id,
        'receiver_id': data['receiver_id'],
        'text': data['text'],
        'timestamp': datetime.now().isoformat()
    }, room=room)
    return jsonify({"status": "ok"})


@app.route('/api/upload', methods=['POST'])
@jwt_required()
def upload():
    user_id = get_jwt_identity()
    file = request.files.get('file')
    receiver_id = request.form.get('receiver_id')

    if not file or not allowed_file(file.filename):
        return jsonify({"status": "error", "message": "Недопустимый файл"}), 400

    filename = secure_filename(f"{int(time.time())}_{file.filename}")
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    file_url = f"/static/uploads/{filename}"
    ext = filename.rsplit('.', 1)[1].lower()
    msg_type = "img" if ext in {'png', 'jpg', 'jpeg', 'gif'} else "file"

    payload = f"__file__:{msg_type}:{file_url}"
    enc_payload = cipher.encrypt(payload.encode()).decode()

    conn = get_db()
    conn.execute(
        'INSERT INTO messages (sender_id, receiver_id, text) VALUES (?, ?, ?)',
        (user_id, receiver_id, enc_payload)
    )
    conn.commit()
    conn.close()

    room = f"chat_{receiver_id}"
    socketio.emit('new_message', {
        'sender_id': user_id,
        'receiver_id': receiver_id,
        'text': payload,
        'timestamp': datetime.now().isoformat(),
        'is_file': True,
        'file_url': file_url,
        'file_type': msg_type
    }, room=room)

    return jsonify({
        "status": "ok",
        "file_url": file_url,
        "file_type": msg_type
    })


@app.route('/api/delete_message/<int:message_id>', methods=['POST'])
@jwt_required()
def delete_message(message_id):
    user_id = get_jwt_identity()
    conn = get_db()
    msg = conn.execute(
        'SELECT sender_id FROM messages WHERE id = ?', (message_id,)
    ).fetchone()

    if msg and msg['sender_id'] == user_id:
        conn.execute('DELETE FROM messages WHERE id = ?', (message_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})

    conn.close()
    return jsonify({"status": "error", "message": "Нельзя удалить чужое сообщение"}), 403


@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@socketio.on('join_room')
def handle_join_room(data):
    room = f"chat_{data['friend_id']}"
    join_room(room)
    emit('joined', {'message': f'Вы вошли в чат с {data["friend_id"]}'})


@socketio.on('send_message')
def handle_send_message(data):
    pass

@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            token = create_access_token(identity=user['id'])
            response = make_response(redirect(url_for('chat')))
            response.set_cookie(
                'access_token',
                token,
                httponly=True,
                secure=app.config['JWT_COOKIE_SECURE'],
                samesite='Lax'
            )
            return response
        else:
            return render_template('login.html', error="Неверные логин/пароль")
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nickname = request.form['nickname']
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            return render_template('register.html', error="Пароли не совпадают")

        conn = get_db()
        cursor = conn.cursor()
        existing_user = cursor.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()

        if existing_user:
            conn.close()
            return render_template('register.html', error="Пользователь с таким именем уже существует")

        hashed_password = generate_password_hash(password)
        cursor.execute(
            'INSERT INTO users (username, password, nickname) VALUES (?, ?, ?)',
            (username, hashed_password, nickname)
        )
        uid = cursor.lastrowid
        cursor.execute(
            'INSERT INTO friends (user_id, friend_id) VALUES (?, ?)',
            (uid, uid)
        )
        conn.commit()
        conn.close()
        return redirect(url_for('login'), code=302)
    return render_template('register.html')


@app.route('/chat')
@jwt_required()
def chat():
    user_id = get_jwt_identity()
    conn = get_db()
    friends = conn.execute('''
            SELECT u.id, u.username FROM users u
            JOIN friends f ON u.id = f.friend_id
            WHERE f.user_id = ?
        ''', (user_id,)).fetchall()
    conn.close()
    return render_template('chat.html', friends=friends)


@app.route('/profile')
@jwt_required()
def profile():
    user_id = get_jwt_identity()
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return render_template('profile.html', user=user)


@app.route('/friends')
@jwt_required()
def friends():
    user_id = get_jwt_identity()
    conn = get_db()
    friends = conn.execute('''
            SELECT u.id, u.username FROM users u
            JOIN friends f ON u.id = f.friend_id
            WHERE f.user_id = ?
        ''', (user_id,)).fetchall()
    conn.close()
    return render_template('friends.html', friends=friends)


@app.route('/games')
@jwt_required()
def games():
    return render_template('games.html')


@app.route('/api/logout', methods=['POST'])
def logout():
    response = make_response(jsonify({"success": True}))
    response.set_cookie(
        'access_token',
        '',
        expires=0,
        httponly=True,
        secure=app.config['JWT_COOKIE_SECURE'],
        samesite='Lax'
    )
    return response


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
