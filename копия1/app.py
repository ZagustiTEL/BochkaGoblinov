from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
import random
import string
import os
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet

app = Flask(__name__)
# Для локальной разработки используем простой ключ
app.secret_key = 'local_secret_key_2025'

# Ключ для шифрования (Fernet требует 32 байта в base64)
# ВАЖНО: Если вы его измените, старые сообщения в базе не прочитаются!
ENCRYPTION_KEY = b'uX6-f1vE0zP_kYQ-jD2pL_9a_N3b_C4d_E5f_G6h_I7='
cipher = Fernet(ENCRYPTION_KEY)

# Локальный путь к базе данных
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'data1.db')

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, code TEXT UNIQUE NOT NULL, creator_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id INTEGER NOT NULL, username TEXT NOT NULL,
        text TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS online_users (
        room_id INTEGER, username TEXT, last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (room_id, username))''')
    conn.commit()
    conn.close()

# Инициализируем базу при старте
init_db()

# --- ЛОГИКА ШИФРОВАНИЯ ---
def encrypt_text(text):
    return cipher.encrypt(text.encode()).decode()

def decrypt_text(encrypted_text):
    try:
        return cipher.decrypt(encrypted_text.encode()).decode()
    except:
        return "[Ошибка расшифровки]"

# --- МАРШРУТЫ ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        try:
            conn = get_db()
            conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except:
            flash('Имя пользователя занято')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        flash('Неверный вход')
    return render_template('login.html')

@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('index.html', username=session['username'])

@app.route('/create_room', methods=['POST'])
def create_room():
    name = request.form.get('room_name')
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    conn = get_db()
    conn.execute('INSERT INTO rooms (name, code, creator_id) VALUES (?, ?, ?)', (name, code, session['user_id']))
    conn.commit()
    conn.close()
    flash(f'Комната создана! Код: {code}')
    return redirect(url_for('index'))

@app.route('/join_room', methods=['POST'])
def join_room():
    code = request.form.get('room_code').strip().upper()
    conn = get_db()
    room = conn.execute('SELECT id FROM rooms WHERE code = ?', (code,)).fetchone()
    conn.close()
    if room: return redirect(url_for('chat', room_id=room['id']))
    flash('Код не найден')
    return redirect(url_for('index'))

@app.route('/chat/<int:room_id>')
def chat(room_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    room = conn.execute('SELECT * FROM rooms WHERE id = ?', (room_id,)).fetchone()
    conn.close()
    return render_template('chat.html', room=room, user_id=session['user_id'])

# --- API ---

@app.route('/api/messages/<int:room_id>')
def get_messages(room_id):
    conn = get_db()
    conn.execute('REPLACE INTO online_users (room_id, username) VALUES (?, ?)', (room_id, session['username']))
    conn.commit()
    rows = conn.execute('SELECT username, text, strftime("%H:%M", timestamp) as time FROM messages WHERE room_id = ? ORDER BY timestamp ASC', (room_id,)).fetchall()
    users_rows = conn.execute('SELECT username FROM online_users WHERE room_id = ?', (room_id,)).fetchall()
    conn.close()

    messages = []
    for r in rows:
        messages.append({'username': r['username'], 'text': decrypt_text(r['text']), 'time': r['time']})

    return jsonify({
        'messages': messages,
        'users': [u['username'] for u in users_rows]
    })

@app.route('/api/send', methods=['POST'])
def send_message():
    data = request.json
    if not data or not data.get('text'): return jsonify({'status': 'error'})
    encrypted = encrypt_text(data['text'])
    conn = get_db()
    conn.execute('INSERT INTO messages (room_id, username, text) VALUES (?, ?, ?)', (data['room_id'], session['username'], encrypted))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- ИЗМЕНЕНИЕ ДЛЯ ЛОКАЛЬНОГО ЗАПУСКА ---
if __name__ == '__main__':
    # debug=True позволит серверу перезагружаться при изменении кода
    app.run(host='127.0.0.1', port=5000, debug=True)