from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_secret_key'

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# File extension check
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# MySQL connection
def get_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='Swapnil@6320',
        database='user_snap_app'
    )

# Create initial table (only if not exists)
def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# Global context for navbar
@app.context_processor
def inject_navbar_data():
    if 'user_id' not in session:
        return {}

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Friend Requests
    cursor.execute('''
        SELECT friend_requests.id, users.username
        FROM friend_requests
        JOIN users ON friend_requests.sender_id = users.id
        WHERE friend_requests.receiver_id = %s AND friend_requests.status = 'pending'
    ''', (session['user_id'],))
    friend_requests = cursor.fetchall()

    # Suggested Users
    cursor.execute('''
        SELECT id, username FROM users
        WHERE id != %s AND id NOT IN (
            SELECT sender_id FROM friend_requests WHERE receiver_id = %s
            UNION
            SELECT receiver_id FROM friend_requests WHERE sender_id = %s
        )
    ''', (session['user_id'], session['user_id'], session['user_id']))
    suggested_users = cursor.fetchall()

    conn.close()
    return dict(friend_requests=friend_requests, suggested_users=suggested_users)

# Home
@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect('/login')
    return redirect('/dashboard')

# Register
@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO users (username, email, password) VALUES (%s, %s, %s)',
                           (username, email, password))
            conn.commit()
            return redirect(url_for('login'))
        except mysql.connector.IntegrityError:
            error = "Username or email already exists."
        finally:
            conn.close()
    return render_template('register.html', error=error)

# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password_input = request.form['password']

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password_input):
            session['user_id'] = user['id']
            return redirect(url_for('dashboard'))
        else:
            return "Invalid email or password"
    return render_template('login.html')

# Dashboard
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch only the posts created by the current user
    cursor.execute("SELECT * FROM posts WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    posts = cursor.fetchall()

    # Get current user info
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    # Fetch accepted friends (both directions)
    cursor.execute('''
        SELECT users.id, users.username
        FROM users
        JOIN friend_requests ON (
            (friend_requests.sender_id = users.id AND friend_requests.receiver_id = %s)
            OR (friend_requests.receiver_id = users.id AND friend_requests.sender_id = %s)
        )
        WHERE friend_requests.status = 'accepted' AND users.id != %s
    ''', (user_id, user_id, user_id))
    friends = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('dashboard.html', posts=posts, user=user, friends=friends)


# Friend Requests Page
@app.route('/friend_requests')
def view_friend_requests():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT friend_requests.id, users.username
        FROM friend_requests
        JOIN users ON friend_requests.sender_id = users.id
        WHERE friend_requests.receiver_id = %s AND friend_requests.status = 'pending'
    ''', (session['user_id'],))
    requests = cursor.fetchall()
    conn.close()

    return render_template('friend_requests.html', friend_requests=requests)

# Suggested Users Page
@app.route('/suggested_users')
def view_suggested_users():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT id, username FROM users
        WHERE id != %s AND id NOT IN (
            SELECT sender_id FROM friend_requests WHERE receiver_id = %s
            UNION
            SELECT receiver_id FROM friend_requests WHERE sender_id = %s
        )
    ''', (session['user_id'], session['user_id'], session['user_id']))
    suggested = cursor.fetchall()
    conn.close()

    return render_template('suggested_users.html', suggested_users=suggested)


# Create post
@app.route('/post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    content = request.form['content']
    image = request.files['image']
    image_filename = None

    if image and image.filename:
        image_filename = secure_filename(image.filename)
        image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO posts (user_id, content, image_filename) VALUES (%s, %s, %s)",
                   (user_id, content, image_filename))
    mysql.connection.commit()
    cursor.close()

    return redirect(url_for('dashboard'))

@app.route('/user/<int:user_id>')
def view_user_profile(user_id):
    # Get the user's info
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    if not user:
        return "User not found", 404

    # Get posts by this user
    cursor.execute("SELECT * FROM posts WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    posts = cursor.fetchall()
    cursor.close()

    return render_template('user_profile.html', user=user, posts=posts)


# Send friend request
@app.route('/send_request/<int:receiver_id>', methods=['POST'])
def send_request(receiver_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO friend_requests (sender_id, receiver_id)
        VALUES (%s, %s)
    ''', (session['user_id'], receiver_id))
    conn.commit()
    conn.close()

    return redirect(url_for('dashboard'))

# Accept friend request
@app.route('/accept_request/<int:request_id>', methods=['POST'])
def accept_request(request_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE friend_requests SET status = 'accepted' WHERE id = %s AND receiver_id = %s
    ''', (request_id, session['user_id']))
    conn.commit()
    conn.close()

    return redirect(url_for('dashboard'))

# Logout
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# Run
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
