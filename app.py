from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
import os
from werkzeug.utils import secure_filename
from flask import flash, jsonify
from werkzeug.utils import secure_filename
from flask import jsonify
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
import cloudinary.api



load_dotenv()


app = Flask(__name__)
app.secret_key = 'your_secret_key'


# -------------------------
# Upload / file config
# -------------------------
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Public uploads live under static/uploads so Flask can serve them in dev.
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
PROFILE_UPLOAD_DIR = os.path.join(UPLOAD_FOLDER, 'profiles')

# create folders if missing
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_UPLOAD_DIR, exist_ok=True)

# allowed extensions sets
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_IMG = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_RESUME = {'pdf', 'doc', 'docx'}

# store in app config for later reference
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PROFILE_UPLOAD_DIR'] = PROFILE_UPLOAD_DIR

# file extension check (supports passing a custom allowed set)
def allowed_file(filename, allowed_set=None):
    if not filename or '.' not in filename:
        return False
    allowed = allowed_set if allowed_set is not None else ALLOWED_EXTENSIONS
    return filename.rsplit('.', 1)[1].lower() in allowed



cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# MySQL connection
# def get_connection():
#     return mysql.connector.connect(
#         host='localhost',
#         user='root',
#         password='Swapnil@6320',
#         database='user_snap_app'
#     )

print("Connecting to host:", os.environ.get("MYSQL_HOST"))

def get_connection():
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST"),
        port=int(os.environ.get("MYSQL_PORT")),
        user=os.environ.get("MYSQL_USER"),
        password=os.environ.get("MYSQL_PASSWORD"),
        database=os.environ.get("MYSQL_DATABASE")
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

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch feed posts with the username of the author (most recent first)
    cursor.execute("""
    SELECT posts.*,
           users.username,
           profiles.profile_image AS author_image
    FROM posts
    JOIN users ON posts.user_id = users.id
    LEFT JOIN profiles ON users.id = profiles.user_id
    ORDER BY posts.created_at DESC
    LIMIT 100
""")
    posts = cursor.fetchall()


    # Get current user info
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    # Load profile for current user (if any)
    cursor.execute("SELECT * FROM profiles WHERE user_id = %s", (user_id,))
    profile = cursor.fetchone()

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

    # render dashboard with profile included
    return render_template('dashboard.html', posts=posts, user=user, friends=friends, profile=profile)



@app.route('/profile/create', methods=['GET', 'POST'])
@app.route('/profile/edit', methods=['GET', 'POST'])
def create_or_edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # try to load existing profile
    cur.execute("SELECT * FROM profiles WHERE user_id=%s", (user_id,))
    profile = cur.fetchone()

    if request.method == 'POST':
        headline = request.form.get('headline', '').strip()
        bio = request.form.get('bio', '').strip()
        location = request.form.get('location', '').strip()
        college = request.form.get('college', '').strip()
        graduation_year = request.form.get('graduation_year') or None
        skills = request.form.get('skills', '').strip()  # comma-separated
        interests = request.form.get('interests', '').strip()
        website = request.form.get('website', '').strip()

        # files
        profile_image = request.files.get('profile_image')
        resume = request.files.get('resume')

        profile_image_filename = profile.get('profile_image') if profile else None
        resume_filename = profile.get('resume_filename') if profile else None

        # handle profile image
        if profile_image and profile_image.filename and allowed_file(profile_image.filename, ALLOWED_IMG):
            fn = secure_filename(profile_image.filename)
            # prefix user id and timestamp for uniqueness
            fn = f"user{user_id}_profile_{int(__import__('time').time())}_{fn}"
            upload_result = cloudinary.uploader.upload(profile_image, folder="profiles/")
            profile_image_filename = upload_result['secure_url']


        # handle resume
        if resume and resume.filename and allowed_file(resume.filename, ALLOWED_RESUME):
            rf = secure_filename(resume.filename)
            rf = f"user{user_id}_resume_{int(__import__('time').time())}_{rf}"
            resume.save(os.path.join(app.config['PROFILE_UPLOAD_DIR'], rf))
            resume_filename = rf

        if profile:
            # update
            cur.execute("""
                UPDATE profiles SET headline=%s, bio=%s, location=%s, college=%s, graduation_year=%s,
                    skills=%s, interests=%s, website=%s, profile_image=%s, resume_filename=%s
                WHERE user_id=%s
            """, (headline, bio, location, college, graduation_year, skills, interests, website, profile_image_filename, resume_filename, user_id))
        else:
            # insert
            cur.execute("""
                INSERT INTO profiles (user_id, headline, bio, location, college, graduation_year, skills, interests, website, profile_image, resume_filename)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (user_id, headline, bio, location, college, graduation_year, skills, interests, website, profile_image_filename, resume_filename))
        conn.commit()
        cur.close(); conn.close()
        return redirect(url_for('view_profile_page', user_id=user_id))

    cur.close()
    conn.close()
    return render_template('profile_form.html', profile=profile)


@app.route('/profile/<int:user_id>')
def view_profile_page(user_id):
    # get user basic info
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, username, email FROM users WHERE id=%s", (user_id,))
    user = cur.fetchone()
    if not user:
        cur.close(); conn.close()
        return "User not found", 404

    # get profile data
    cur.execute("SELECT * FROM profiles WHERE user_id=%s", (user_id,))
    profile = cur.fetchone()

    # fetch posts by user (optional)
    cur.execute("""
    SELECT posts.*,
           users.username,
           profiles.profile_image AS author_image
    FROM posts
    JOIN users ON posts.user_id = users.id
    LEFT JOIN profiles ON users.id = profiles.user_id
    WHERE posts.user_id=%s
    ORDER BY posts.created_at DESC
    LIMIT 20
""", (user_id,))
    posts = cur.fetchall()


    cur.close()
    conn.close()
    return render_template('profile_view.html', user=user, profile=profile, posts=posts)

@app.route('/post/<int:post_id>/comment', methods=['POST'])
def post_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    uid = session['user_id']
    comment = request.form.get('comment','').strip()
    if not comment:
        return redirect(url_for('dashboard'))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO post_comments (post_id, user_id, comment) VALUES (%s,%s,%s)", (post_id, uid, comment))
    conn.commit()
    # notify post owner
    cursor.execute("SELECT user_id FROM posts WHERE id=%s", (post_id,))
    owner = cursor.fetchone()
    if owner and owner[0] != uid:
        cursor.execute("INSERT INTO notifications (user_id, actor_id, type, ref_id, text) VALUES (%s,%s,%s,%s,%s)",
                       (owner[0], uid, 'comment', post_id, 'commented on your post'))
        conn.commit()
    cursor.close(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    uid = session['user_id']
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT n.*, u.username as actor_name FROM notifications n LEFT JOIN users u ON n.actor_id = u.id WHERE n.user_id=%s ORDER BY created_at DESC LIMIT 50", (uid,))
    notes = cur.fetchall()
    cur.close(); conn.close()
    return render_template('notifications.html', notifications=notes)

@app.route('/notifications/mark_read/<int:nid>', methods=['POST'])
def mark_notif_read(nid):
    if 'user_id' not in session:
        return jsonify({"ok": False}), 401
    conn = get_connection(); c = conn.cursor()
    c.execute("UPDATE notifications SET is_read=1 WHERE id=%s", (nid,))
    conn.commit(); c.close(); conn.close()
    return jsonify({"ok": True})


@app.route('/post/<int:post_id>/toggle_like', methods=['POST'])
def toggle_like(post_id):
    if 'user_id' not in session:
        return jsonify({"ok": False, "error": "unauthenticated"}), 401
    uid = session['user_id']
    conn = get_connection()
    cursor = conn.cursor()
    # check if exists
    cursor.execute("SELECT id FROM post_reactions WHERE post_id=%s AND user_id=%s", (post_id, uid))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("DELETE FROM post_reactions WHERE id=%s", (existing[0],))
        conn.commit()
        # optional create notification removal logic
        result = {"liked": False}
    else:
        cursor.execute("INSERT INTO post_reactions (post_id, user_id) VALUES (%s, %s)", (post_id, uid))
        conn.commit()
        # create notification for post owner
        cursor.execute("SELECT user_id FROM posts WHERE id=%s", (post_id,))
        owner = cursor.fetchone()
        if owner and owner[0] != uid:
            cursor.execute("INSERT INTO notifications (user_id, actor_id, type, ref_id, text) VALUES (%s, %s, %s, %s, %s)",
                           (owner[0], uid, 'like', post_id, 'someone liked your post'))
            conn.commit()
        result = {"liked": True}
    cursor.close()
    conn.close()
    # return updated counts
    # count likes
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM post_reactions WHERE post_id=%s", (post_id,))
    likes_count = c.fetchone()[0]
    c.close()
    conn.close()
    result["likes_count"] = likes_count
    return jsonify(result)


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

@app.route('/search')
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    query = request.args.get('query', '').strip()
    results = []

    if query:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, username FROM users WHERE username LIKE %s LIMIT 50", (f"%{query}%",))
        results = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template('search_results.html', query=query, results=results)

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
        try:
            upload_result = cloudinary.uploader.upload(image, folder="posts/")
            image_filename = upload_result['secure_url']
        except Exception as e:
            print("Cloudinary upload failed:", e)
            image_filename = None


    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("INSERT INTO posts (user_id, content, image_filename) VALUES (%s, %s, %s)",
                   (user_id, content, image_filename))
    conn.commit()
    cursor.close()

    return redirect(url_for('dashboard'))

# @app.route('/user/<int:user_id>')
# def view_user_profile(user_id):
#     # Get the user's info
#     conn = get_connection()
#     cursor = conn.cursor(dictionary=True)
#     cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
#     user = cursor.fetchone()

#     if not user:
#         return "User not found", 404

#     # Get posts by this user
#     cursor.execute("SELECT * FROM posts WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
#     posts = cursor.fetchall()
#     cursor.close()

#     return render_template('user_profile.html', user=user, posts=posts)


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

@app.route('/chat/<int:friend_id>', methods=['GET', 'POST'])
def chat(friend_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        message = request.form['message']
        cursor.execute("INSERT INTO messages (sender_id, receiver_id, message) VALUES (%s, %s, %s)",
                       (user_id, friend_id, message))
        conn.commit()

    # Fetch chat messages between two users
    cursor.execute("""
        SELECT * FROM messages 
        WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s)
        ORDER BY timestamp ASC
    """, (user_id, friend_id, friend_id, user_id))
    
    messages = cursor.fetchall()

    # Fetch friend's username for display
    cursor.execute("SELECT id,username FROM users WHERE id = %s", (friend_id,))
    friend = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template('chat.html', messages=messages, friend=friend, user_id=user_id)

@app.route('/vanish_chat/<int:friend_id>', methods=['POST'])
def vanish_chat(friend_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    conn = get_connection()
    cursor = conn.cursor()

    # Delete messages between both users
    cursor.execute("""
        DELETE FROM messages
        WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s)
    """, (user_id, friend_id, friend_id, user_id))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('chat', friend_id=friend_id))



# Logout
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# Run
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
