from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet

app = Flask(__name__)
app.secret_key = 'local_secret_key_2025'

ENCRYPTION_KEY = b'uX6-f1vE0zP_kYQ-jD2pL_9a_N3b_C4d_E5f_G6h_I7='
cipher = Fernet(ENCRYPTION_KEY)

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

    c.execute('''CREATE TABLE IF NOT EXISTS friends (
        user_id INTEGER NOT NULL,
        friend_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, friend_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (friend_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sender_id) REFERENCES users(id),
        FOREIGN KEY (receiver_id) REFERENCES users(id)
    )''')
    conn.commit()
    conn.close()


init_db()


def encrypt_text(text):
    return cipher.encrypt(text.encode()).decode()


def decrypt_text(encrypted_text):
    try:
        return cipher.decrypt(encrypted_text.encode()).decode()
    except:
        return "[Ошибка расшифровки]"


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
            conn.commit()

            # ДОБАВЛЕНО: Добавляем пользователя самого себе в друзья для чата "Избранное"
            user_id = c.lastrowid
            c.execute('INSERT INTO friends (user_id, friend_id) VALUES (?, ?)', (user_id, user_id))
            conn.commit()

            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
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


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db()

    # Получаем список друзей, включая "Избранное" (где user_id == friend_id)
    friends_rows = conn.execute('''
        SELECT u.id, u.username FROM users u
        JOIN friends f ON u.id = f.friend_id
        WHERE f.user_id = ?
    ''', (user_id,)).fetchall()

    conn.close()

    friends = []
    favorites_chat = None
    for row in friends_rows:
        if row['id'] == user_id:
            # Отдельно выделяем чат "Избранное"
            favorites_chat = {'id': row['id'], 'username': 'Избранное'}
        else:
            friends.append({'id': row['id'], 'username': row['username']})

    # Добавляем "Избранное" в начало списка друзей
    if favorites_chat:
        friends.insert(0, favorites_chat)

    return render_template('index.html', username=session['username'], friends=friends)


@app.route('/add_friend', methods=['POST'])
def add_friend():
    if 'user_id' not in session: return redirect(url_for('login'))
    friend_username = request.form.get('friend_username')
    user_id = session['user_id']
    conn = get_db()

    friend_user = conn.execute('SELECT id FROM users WHERE username = ?', (friend_username,)).fetchone()

    if friend_user and friend_user['id'] != user_id:
        friend_id = friend_user['id']
        try:
            # Добавляем связь A -> B и B -> A
            conn.execute('INSERT INTO friends (user_id, friend_id) VALUES (?, ?)', (user_id, friend_id))
            conn.execute('INSERT INTO friends (user_id, friend_id) VALUES (?, ?)', (friend_id, user_id))
            conn.commit()
            flash(f'Пользователь {friend_username} успешно добавлен!')
        except sqlite3.IntegrityError:
            flash(f'Пользователь {friend_username} уже в списке ваших друзей.')
    elif friend_user['id'] == user_id:
        flash('Вы не можете добавить себя как друга.')
    else:
        flash('Пользователь с таким именем не найден.')

    conn.close()
    # После добавления друга перенаправляем на главную страницу
    return redirect(url_for('index'))


# Маршруты API get_messages и send_message остаются без изменений

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)

