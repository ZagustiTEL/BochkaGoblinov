import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import hashlib

class Database:
    def __init__(self, db_name='messenger.db'):
        self.db_name = db_name
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_name, detect_types=sqlite3.PARSE_DECLTYPES)
    
    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            unique_nickname TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Таблица профилей
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT,
            bio TEXT,
            avatar TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        
        # Таблица друзей
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS friends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            friend_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            accepted_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (friend_id) REFERENCES users (id),
            UNIQUE(user_id, friend_id)
        )
        ''')
        
        # Таблица сообщений с поддержкой разных типов
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT,
            message_type TEXT DEFAULT 'text',
            file_path TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            read_status INTEGER DEFAULT 0,
            FOREIGN KEY (sender_id) REFERENCES users (id),
            FOREIGN KEY (receiver_id) REFERENCES users (id)
        )
        ''')
        
        # Таблица стикеров
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS stickers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            emoji TEXT,
            file_path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Попробуем добавить недостающие колонки
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN message_type TEXT DEFAULT 'text'")
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN file_path TEXT")
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN read_status INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        
        conn.commit()
        conn.close()
        
        # Создаем необходимые папки
        os.makedirs('static/uploads/images', exist_ok=True)
        os.makedirs('static/uploads/stickers', exist_ok=True)
        
        # Добавляем демо-стикеры при первом запуске
        self.add_demo_stickers()
    
    def add_demo_stickers(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Проверяем, есть ли уже стикеры
        cursor.execute('SELECT COUNT(*) FROM stickers')
        count = cursor.fetchone()[0]
        
        if count == 0:
            # Добавляем демо-стикеры (эмодзи)
            demo_stickers = [
                ('👍', 'Лайк', 'reactions', '👍'),
                ('❤️', 'Сердечко', 'reactions', '❤️'),
                ('😂', 'Смех', 'reactions', '😂'),
                ('😮', 'Удивление', 'reactions', '😮'),
                ('😢', 'Грусть', 'reactions', '😢'),
                ('🔥', 'Огонь', 'reactions', '🔥'),
                ('🎉', 'Праздник', 'reactions', '🎉'),
                ('💩', 'Какашка', 'funny', '💩'),
                ('👋', 'Привет', 'greetings', '👋'),
                ('✅', 'Готово', 'actions', '✅'),
                ('❌', 'Отмена', 'actions', '❌'),
                ('💬', 'Сообщение', 'actions', '💬'),
                ('👀', 'Смотрю', 'reactions', '👀'),
                ('🤔', 'Думаю', 'reactions', '🤔'),
                ('🥳', 'Веселье', 'reactions', '🥳')
            ]
            
            for emoji, name, category, file_path in demo_stickers:
                cursor.execute(
                    'INSERT INTO stickers (emoji, name, category, file_path) VALUES (?, ?, ?, ?)',
                    (emoji, name, category, file_path)
                )
        
        conn.commit()
        conn.close()
    
    def update_last_seen(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?',
            (user_id,)
        )
        conn.commit()
        conn.close()
    
    def get_user_status(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT last_seen FROM users WHERE id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            try:
                last_seen = result[0]
                if isinstance(last_seen, str):
                    # Если это строка, парсим
                    if 'T' in last_seen:
                        last_seen_time = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                    else:
                        last_seen_time = datetime.strptime(last_seen, '%Y-%m-%d %H:%M:%S')
                else:
                    # Если это datetime объект
                    last_seen_time = last_seen
                
                current_time = datetime.now()
                time_diff = (current_time - last_seen_time).total_seconds()
                
                if time_diff < 300:  # 5 минут
                    return 'online'
                elif time_diff < 3600:  # 1 час
                    return 'recently'
                else:
                    return 'offline'
            except (ValueError, TypeError, AttributeError) as e:
                print(f"Error parsing date: {e}")
                return 'offline'
        return 'offline'
    
    def register_user(self, username, password):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        unique_nickname = f"@{username}"
        
        try:
            hashed_password = generate_password_hash(password)
            cursor.execute(
                'INSERT INTO users (username, password, unique_nickname, last_seen) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
                (username, hashed_password, unique_nickname)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def authenticate_user(self, username, password):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, username, password, unique_nickname FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()
        
        if user and check_password_hash(user[2], password):
            self.update_last_seen(user[0])
            return {
                'id': user[0], 
                'username': user[1], 
                'unique_nickname': user[3]
            }
        return None
    
    def get_user_by_id(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, username, unique_nickname, created_at FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if user:
            status = self.get_user_status(user_id)
            profile_info = self.get_profile_info(user_id)
            
            result = {
                'id': user[0], 
                'username': user[1], 
                'unique_nickname': user[2],
                'created_at': user[3],
                'status': status
            }
            
            # Добавляем информацию профиля, если есть
            if profile_info:
                result.update(profile_info)
            
            conn.close()
            return result
        
        conn.close()
        return None
    
    def get_user_by_username(self, username):
        """Получить пользователя по логину"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, username, unique_nickname FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'unique_nickname': user[2]
            }
        return None
    
    def check_password(self, user_id, password):
        """Проверить пароль пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT password FROM users WHERE id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result and check_password_hash(result[0], password):
            return True
        return False
    
    def update_password(self, user_id, new_password):
        """Обновить пароль пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        hashed_password = generate_password_hash(new_password)
        cursor.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_password, user_id))
        
        conn.commit()
        conn.close()
    
    def update_username(self, user_id, new_username):
        """Обновить логин пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE users SET username = ? WHERE id = ?', (new_username, user_id))
        
        conn.commit()
        conn.close()
    
    def update_profile_info(self, user_id, display_name=None, bio=None, avatar=None):
        """Обновить информацию профиля"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Проверяем, есть ли запись
        cursor.execute('SELECT user_id FROM profiles WHERE user_id = ?', (user_id,))
        existing = cursor.fetchone()
        
        if existing:
            # Обновляем существующую запись
            cursor.execute('''
                UPDATE profiles 
                SET display_name = COALESCE(?, display_name),
                    bio = COALESCE(?, bio),
                    avatar = COALESCE(?, avatar),
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (display_name, bio, avatar, user_id))
        else:
            # Создаем новую запись
            cursor.execute('''
                INSERT INTO profiles (user_id, display_name, bio, avatar)
                VALUES (?, ?, ?, ?)
            ''', (user_id, display_name, bio, avatar))
        
        conn.commit()
        conn.close()
    
    def get_profile_info(self, user_id):
        """Получить информацию профиля"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT display_name, bio, avatar, updated_at 
            FROM profiles 
            WHERE user_id = ?
        ''', (user_id,))
        
        info = cursor.fetchone()
        conn.close()
        
        if info:
            return {
                'display_name': info[0],
                'bio': info[1],
                'avatar': info[2],
                'updated_at': info[3]
            }
        return None
    
    def get_user_by_nickname(self, nickname):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT u.id, u.username, u.unique_nickname, p.avatar 
            FROM users u
            LEFT JOIN profiles p ON u.id = p.user_id
            WHERE u.unique_nickname = ?
        ''', (nickname,))
        
        user = cursor.fetchone()
        conn.close()
        
        if user:
            status = self.get_user_status(user[0])
            return {
                'id': user[0], 
                'username': user[1], 
                'unique_nickname': user[2],
                'status': status,
                'avatar': user[3]
            }
        return None
    
    def get_all_users(self, exclude_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if exclude_id:
            cursor.execute('''
                SELECT u.id, u.username, u.unique_nickname, p.avatar 
                FROM users u
                LEFT JOIN profiles p ON u.id = p.user_id
                WHERE u.id != ?
            ''', (exclude_id,))
        else:
            cursor.execute('''
                SELECT u.id, u.username, u.unique_nickname, p.avatar 
                FROM users u
                LEFT JOIN profiles p ON u.id = p.user_id
            ''')
        
        users = cursor.fetchall()
        conn.close()
        
        result = []
        for user in users:
            status = self.get_user_status(user[0])
            result.append({
                'id': user[0], 
                'username': user[1], 
                'unique_nickname': user[2],
                'status': status,
                'avatar': user[3]
            })
        
        return result
    
    def get_friend_requests(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT f.id, f.user_id, f.status, f.requested_at, 
                u.username, u.unique_nickname, p.avatar
            FROM friends f
            JOIN users u ON f.user_id = u.id
            LEFT JOIN profiles p ON u.id = p.user_id
            WHERE f.friend_id = ? AND f.status = 'pending'
            ORDER BY f.requested_at DESC
        ''', (user_id,))
        
        requests = cursor.fetchall()
        conn.close()
        
        print(f"Found {len(requests)} friend requests for user {user_id}")  # Отладка
        
        return [{
            'id': req[0],
            'user_id': req[1],
            'status': req[2],
            'requested_at': req[3],
            'username': req[4],
            'unique_nickname': req[5],
            'avatar': req[6]
        } for req in requests]
    
    def get_friends_with_status(self, user_id, status='accepted'):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                CASE 
                    WHEN f.user_id = ? THEN f.friend_id 
                    ELSE f.user_id 
                END as friend_id,
                u.username,
                u.unique_nickname,
                f.status,
                f.accepted_at,
                p.avatar
            FROM friends f
            JOIN users u ON (
                CASE 
                    WHEN f.user_id = ? THEN f.friend_id 
                    ELSE f.user_id 
                END = u.id
            )
            LEFT JOIN profiles p ON u.id = p.user_id
            WHERE (f.user_id = ? OR f.friend_id = ?) 
            AND f.status = ?
            ORDER BY 
                CASE WHEN f.accepted_at IS NULL THEN 1 ELSE 0 END,
                f.accepted_at DESC,
                u.username
        ''', (user_id, user_id, user_id, user_id, status))
        
        friends = cursor.fetchall()
        conn.close()
        
        result = []
        for friend in friends:
            friend_status = self.get_user_status(friend[0])
            result.append({
                'id': friend[0],
                'username': friend[1],
                'unique_nickname': friend[2],
                'status': friend_status,
                'friend_status': friend[3],
                'accepted_at': friend[4],
                'avatar': friend[5]
            })
    
        return result
    
    def get_friends(self, user_id, status='accepted'):
        return self.get_friends_with_status(user_id, status)
    
    def respond_to_friend_request(self, request_id, user_id, action):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id FROM friends 
            WHERE id = ? AND friend_id = ? AND status = 'pending'
        ''', (request_id, user_id))
        
        if not cursor.fetchone():
            return {'success': False, 'error': 'Заявка не найдена'}
        
        if action == 'accept':
            cursor.execute('''
                UPDATE friends 
                SET status = 'accepted', accepted_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (request_id,))
            message = 'Заявка принята'
        elif action == 'reject':
            cursor.execute('''
                UPDATE friends 
                SET status = 'rejected' 
                WHERE id = ?
            ''', (request_id,))
            message = 'Заявка отклонена'
        else:
            return {'success': False, 'error': 'Неизвестное действие'}
        
        conn.commit()
        conn.close()
        
        print(f"Friend request {request_id} {action}ed")  # Отладка
        
        return {'success': True, 'message': message}
    
    def add_friend_request(self, user_id, nickname):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Получаем пользователя по нику
        cursor.execute('SELECT id FROM users WHERE unique_nickname = ?', (nickname,))
        friend = cursor.fetchone()
        
        if not friend:
            return {'success': False, 'error': 'Пользователь не найден'}
        
        friend_id = friend[0]
        
        if friend_id == user_id:
            return {'success': False, 'error': 'Нельзя добавить самого себя'}
        
        # Проверяем, не друзья ли уже
        cursor.execute('''
            SELECT status FROM friends 
            WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)
        ''', (user_id, friend_id, friend_id, user_id))
        
        existing = cursor.fetchone()
        
        if existing:
            if existing[0] == 'accepted':
                return {'success': False, 'error': 'Вы уже друзья'}
            elif existing[0] == 'pending':
                return {'success': False, 'error': 'Заявка уже отправлена'}
            elif existing[0] == 'rejected':
                return {'success': False, 'error': 'Заявка была отклонена'}
        
        # Добавляем заявку
        cursor.execute('''
            INSERT INTO friends (user_id, friend_id, status, requested_at)
            VALUES (?, ?, 'pending', CURRENT_TIMESTAMP)
        ''', (user_id, friend_id))
        
        conn.commit()
        conn.close()
        
        print(f"Friend request sent from {user_id} to {friend_id}")  # Отладка
        
        return {'success': True, 'message': 'Заявка отправлена'}
    
    def remove_friend(self, user_id, friend_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM friends 
            WHERE (user_id = ? AND friend_id = ?) 
               OR (user_id = ? AND friend_id = ?)
        ''', (user_id, friend_id, friend_id, user_id))
        
        conn.commit()
        conn.close()
        return cursor.rowcount > 0
    
    def save_message(self, sender_id, receiver_id, message, message_type='text', file_path=None):

        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO messages (sender_id, receiver_id, message, message_type, file_path) VALUES (?, ?, ?, ?, ?)',
            (sender_id, receiver_id, message, message_type, file_path)
        )
        message_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
    
        return message_id
    
    def get_messages(self, user1_id, user2_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT m.id, m.sender_id, m.receiver_id, m.message, m.message_type, m.file_path, 
                strftime('%Y-%m-%d %H:%M:%S', m.timestamp) as timestamp, 
                u1.username as sender_name, u2.username as receiver_name
            FROM messages m
            JOIN users u1 ON m.sender_id = u1.id
            JOIN users u2 ON m.receiver_id = u2.id
            WHERE (m.sender_id = ? AND m.receiver_id = ?) 
            OR (m.sender_id = ? AND m.receiver_id = ?)
            ORDER BY m.timestamp
        ''', (user1_id, user2_id, user2_id, user1_id))
        
        messages = cursor.fetchall()
        conn.close()
        
        print(f"get_messages: found {len(messages)} messages")  # Для отладки
        
        return messages
        
    def get_unread_count(self, user_id, sender_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM messages 
            WHERE receiver_id = ? AND sender_id = ? AND read_status = 0
        ''', (user_id, sender_id))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def mark_messages_as_read(self, user_id, sender_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE messages 
            SET read_status = 1 
            WHERE receiver_id = ? AND sender_id = ? AND read_status = 0
        ''', (user_id, sender_id))
        
        conn.commit()
        conn.close()
    
    def get_last_message_preview(self, user1_id, user2_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT message, timestamp, sender_id 
            FROM messages 
            WHERE (sender_id = ? AND receiver_id = ?) 
               OR (sender_id = ? AND receiver_id = ?)
            ORDER BY timestamp DESC 
            LIMIT 1
        ''', (user1_id, user2_id, user2_id, user1_id))
        
        message = cursor.fetchone()
        conn.close()
        
        if message:
            # Преобразуем timestamp в строку
            timestamp = message[1]
            if isinstance(timestamp, datetime):
                timestamp = timestamp.strftime('%H:%M')
            elif timestamp and isinstance(timestamp, str):
                # Оставляем только время
                if ' ' in timestamp:
                    timestamp = timestamp.split(' ')[1][:5]
                else:
                    timestamp = timestamp[:5]
            
            return {
                'text': message[0],
                'time': timestamp,
                'is_own': message[2] == user1_id
            }
        return None
    
    def get_stickers(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, emoji, name, category FROM stickers ORDER BY category, name')
        stickers = cursor.fetchall()
        conn.close()
        
        return [{
            'id': sticker[0],
            'emoji': sticker[1],
            'name': sticker[2],
            'category': sticker[3]
        } for sticker in stickers]
    
    def get_sticker_by_id(self, sticker_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, emoji, name, category, file_path FROM stickers WHERE id = ?', (sticker_id,))
        sticker = cursor.fetchone()
        conn.close()
        
        if sticker:
            return {
                'id': sticker[0],
                'emoji': sticker[1],
                'name': sticker[2],
                'category': sticker[3],
                'file_path': sticker[4]
            }
        return None