from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
import os
import time
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet

app = Flask(__name__)
app.secret_key = 'local_secret_key_2026'

ENCRYPTION_KEY = b'uX6-f1vE0zP_kYQ-jD2pL_9a_N3b_C4d_E5f_G6h_I7='
cipher = Fernet(ENCRYPTION_KEY)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'data1.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static/uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'docx', 'zip'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.before_request
def update_last_seen():
    if 'user_id' in session:
        conn = get_db()
        conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (int(time.time()), session['user_id']))
        conn.commit()
        conn.close()

@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db()
    friends_rows = conn.execute('''
        SELECT u.id, u.username FROM users u
        JOIN friends f ON u.id = f.friend_id
        WHERE f.user_id = ?
    ''', (user_id,)).fetchall()
    conn.close()
    friends = [{'id': r['id'], 'username': "⭐ Избранное" if r['id'] == user_id else r['username']} for r in friends_rows]
    return render_template('index.html', username=session['username'], friends=friends)

@app.route('/api/messages/<int:friend_id>')
def get_messages(friend_id):
    u_id = session.get('user_id')
    conn = get_db()
    friend = conn.execute('SELECT username, last_seen FROM users WHERE id = ?', (friend_id,)).fetchone()
    is_online = (int(time.time()) - (friend['last_seen'] or 0)) < 60
    rows = conn.execute('''
        SELECT id, sender_id, text, timestamp FROM messages 
        WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
        ORDER BY timestamp ASC''', (u_id, friend_id, friend_id, u_id)).fetchall()
    conn.close()
    msgs = []
    for r in rows:
        try: txt = cipher.decrypt(r.encode()).decode()
        except: txt = "[Ошибка расшифровки]"
        msgs.append({"id": r['id'], "text": txt, "time": r['timestamp'][11:16], "is_me": r['sender_id'] == u_id})
    return jsonify({"messages": msgs, "friend_name": "Избранное" if friend_id == u_id else friend['username'], "online": is_online})

@app.route('/api/send', methods=['POST'])
def send():
    data = request.json
    enc_text = cipher.encrypt(data.encode()).decode()
    conn = get_db()
    conn.execute('INSERT INTO messages (sender_id, receiver_id, text) VALUES (?, ?, ?)', (session['user_id'], data['receiver_id'], enc_text))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/upload', methods=['POST'])
def upload():
    if 'user_id' not in session: return jsonify({"status": "error"}), 403
    file = request.files.get('file')
    receiver_id = request.form.get('receiver_id')
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{int(time.time())}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        file_url = f"/static/uploads/{filename}"
        ext = filename.rsplit('.', 1)[1].lower()
        msg_type = "img" if ext in {'png', 'jpg', 'jpeg', 'gif'} else "file"
        payload = f"__file__:{msg_type}:{file_url}"
        enc_payload = cipher.encrypt(payload.encode()).decode()
        conn = get_db()
        conn.execute('INSERT INTO messages (sender_id, receiver_id, text) VALUES (?, ?, ?)', (session['user_id'], receiver_id, enc_payload))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    return jsonify({"status": "error"}), 400

@app.route('/api/delete_message/<int:message_id>', methods=['POST'])
def delete_message(message_id):
    if 'user_id' not in session: return jsonify({"status": "error"}), 403
    user_id = session['user_id']
    conn = get_db()
    msg = conn.execute('SELECT sender_id FROM messages WHERE id = ?', (message_id,)).fetchone()
    if msg and msg['sender_id'] == user_id:
        conn.execute('DELETE FROM messages WHERE id = ?', (message_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    conn.close()
    return jsonify({"status": "error", "message": "Нельзя удалить чужое сообщение"}), 403

@app.route('/add_friend', methods=['POST'])
def add_friend():
    friend_username = request.form.get('friend_username', '').strip()
    user_id = session.get('user_id')
    conn = get_db()
    friend_user = conn.execute('SELECT id FROM users WHERE username = ?', (friend_username,)).fetchone()
    if friend_user and friend_user['id'] != user_id:
        try:
            conn.execute('INSERT INTO friends (user_id, friend_id) VALUES (?, ?)', (user_id, friend_user['id']))
            conn.execute('INSERT INTO friends (user_id, friend_id) VALUES (?, ?)', (friend_user['id'], user_id))
            conn.commit()
        except: pass
    conn.close()
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u, p = request.form['username'], request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (u,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], p):
            session['user_id'], session['username'] = user['id'], user['username']
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u, p = request.form['username'], generate_password_hash(request.form['password'])
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT INTO users (username, password) VALUES (?, ?)', (u, p))
            uid = c.lastrowid
            c.execute('INSERT INTO friends (user_id, friend_id) VALUES (?, ?)', (uid, uid))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except: return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
