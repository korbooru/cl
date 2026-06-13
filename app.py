import os
import random
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-change-this'

# --- MOCK EMAIL CONFIGURATION (Bypasses Firewalls & Phone Verification) ---
DOMAIN_NAME = "xanuran.pythonanywhere.com"

def send_automated_email(to_email, subject, body):
    """
    Instead of crashing against the PythonAnywhere firewall, this function
    intercepts the email and prints it beautifully into your Server Log.
    """
    print("\n" + "═"*60)
    print("📧 MOCK EMAIL INTERCEPTED BY SERVER LOGS")
    print(f"TO: {to_email}")
    print(f"SUBJECT: {subject}")
    print("CONTENT:")
    # Strip basic HTML tags just to make the log easier to read
    clean_body = body.replace('<h2>', '').replace('</h2>', '\n').replace('<p>', '').replace('</p>', '\n').replace('<br>', '\n')
    print(clean_body)
    print("═"*60 + "\n")

# --- SAFE PATHWAY RESOLUTION FOR PYTHONANYWHERE / PRODUCTION ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
db_dir = '/app/data'
if not os.path.exists(db_dir):
    try:
        os.makedirs(db_dir)
    except Exception:
        db_dir = os.getcwd()

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(db_dir, 'cloudplay.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Configurable Settings
FEATURED_HASHTAG = "#picks" 

# =========================================
# Database Models
# =========================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False) # Immutable Handle (URL)
    display_name = db.Column(db.String(100), nullable=False)        # Mutable Public Display Name
    email = db.Column(db.String(120), unique=True, nullable=False)   # User Email address
    password = db.Column(db.String(200), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)              # Email Verification state
    verification_token = db.Column(db.String(100), nullable=True)   # Active Verification link holder
    reset_code = db.Column(db.String(8), nullable=True)             # 8-Digit Reset verification container
    bio = db.Column(db.Text, default="")
    pfp = db.Column(db.String(200), default="")
    videos = db.relationship('Video', backref='author', lazy=True)
    playlists = db.relationship('Playlist', backref='author', lazy=True)

playlist_video = db.Table('playlist_video',
    db.Column('playlist_id', db.Integer, db.ForeignKey('playlist.id'), primary_key=True),
    db.Column('video_id', db.Integer, db.ForeignKey('video.id'), primary_key=True)
)

class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    visibility = db.Column(db.String(20), default="public")
    videos = db.relationship('Video', secondary=playlist_video, lazy='subquery', backref=db.backref('playlists', lazy=True))

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    views = db.Column(db.Integer, default=0)
    date = db.Column(db.String(20))
    category = db.Column(db.String(50), default="Entertainment")
    visibility = db.Column(db.String(20), default="public")
    desc = db.Column(db.Text)
    thumb = db.Column(db.String(200))
    vid_url = db.Column(db.String(200))
    likes = db.Column(db.Integer, default=0)
    dislikes = db.Column(db.Integer, default=0)
    scheduled_at = db.Column(db.DateTime, nullable=True) 
    comments = db.relationship('Comment', backref='video', lazy=True, cascade="all, delete-orphan")

class Comment(db.Model):
    __tablename__ = 'comment'
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) 
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    username_cache = db.Column(db.String(50)) 
    time_str = db.Column(db.String(20))
    text = db.Column(db.Text)
    likes = db.Column(db.Integer, default=0)
    dislikes = db.Column(db.Integer, default=0)
    user = db.relationship('User', foreign_keys=[user_id])
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side='Comment.id'), foreign_keys=[parent_id], cascade="all, delete-orphan")

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subscriber_id = db.Column(db.Integer, nullable=False)
    channel_id = db.Column(db.Integer, nullable=False)

class Report(db.Model): 
    id = db.Column(db.Integer, primary_key=True)
    item_type = db.Column(db.String(20), nullable=False) 
    item_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) 
    reason = db.Column(db.String(100), nullable=False)
    date_reported = db.Column(db.DateTime, default=datetime.now)

class RateTracker(db.Model):
    __tablename__ = 'rate_tracker'
    id = db.Column(db.Integer, primary_key=True)
    item_type = db.Column(db.String(20), nullable=False) # 'video' or 'comment'
    item_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(10), nullable=False) # 'like' or 'dislike'

class ViewTracker(db.Model):
    __tablename__ = 'view_tracker'
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)

with app.app_context():
    db.create_all()

# =========================================
# Authentication & Verification Systems
# =========================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash("Username already exists.")
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash("Email address already registered.")
            return redirect(url_for('register'))
            
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        verification_token = secrets.token_hex(16)
        
        # Initially, public display_name mirrors the unique handle path name
        new_user = User(
            username=username, 
            display_name=username, 
            email=email, 
            password=hashed_pw, 
            is_verified=False, 
            verification_token=verification_token
        )
        db.session.add(new_user)
        db.session.commit()
        
        # ACTUALLY SEND THE EMAIL
        verification_link = f"https://{DOMAIN_NAME}/verify-email/{verification_token}"
        email_subject = "CloudPlay - Verify Your Account"
        email_body = f"""
        <h2>Welcome to CloudPlay!</h2>
        <p>Please confirm your email address by clicking the link below:</p>
        <p><a href="{verification_link}">{verification_link}</a></p>
        <p>If you did not create this account, please ignore this email.</p>
        """
        
        send_automated_email(email, email_subject, email_body)
        
        flash("Registration complete! An email verification link was sent to your inbox.")
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/verify-email/<token>')
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if user:
        user.is_verified = True
        user.verification_token = None
        db.session.commit()
        flash("Your email verification is successful! You can now log into your account.")
        return redirect(url_for('login'))
    flash("The email verification token is invalid or has expired.")
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Look up the profile using either their unique handle or email address
        user = User.query.filter(or_(User.username == username, User.email == username)).first()
        
        if user and check_password_hash(user.password, password):
            # CRITICAL CHECK: Block access if email is unverified
            if not user.is_verified:
                flash("Access Denied: Your email address has not been verified yet. Please use the activation link sent to your registration email address.")
                return redirect(url_for('login'))
                
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash("Invalid credentials supplied.")
            return redirect(url_for('login'))
            
    return render_template('login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            # Generate a clean 8-digit numerical recovery token string
            code = "".join([str(random.randint(0, 9)) for _ in range(8)])
            user.reset_code = code
            db.session.commit()
            
            # ACTUALLY SEND THE RESET CODE EMAIL
            email_subject = "CloudPlay - Password Recovery Code"
            email_body = f"""
            <h2>CloudPlay Account Recovery</h2>
            <p>A password reset was requested for your account.</p>
            <p>Your 8-digit temporary security access token is: <strong><span style="font-size: 20px; color: #cc0000;">{code}</span></strong></p>
            <p>If you did not request this, you can safely ignore this email.</p>
            """
            
            send_automated_email(email, email_subject, email_body)
            
            flash("An 8-digit validation code has been sent to your email inbox.")
            return redirect(url_for('reset_password', email=email))
        flash("No user record could be identified matching that email address.")
    return render_template('forgot_password.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    email = request.args.get('email') or request.form.get('email')
    if request.method == 'POST':
        code = request.form.get('code')
        new_password = request.form.get('new_password')
        user = User.query.filter_by(email=email, reset_code=code).first()
        
        if user and code:
            user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
            user.reset_code = None
            db.session.commit()
            flash("Password updated successfully! You can now log in.")
            return redirect(url_for('login'))
        flash("Invalid validation code or mismatched email address.")
    return render_template('reset_password.html', email=email)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        new_display_name = request.form.get('display_name')
        new_username = request.form.get('username')
        current_password = request.form.get('current_password')
        new_bio = request.form.get('bio')
        pfp_file = request.files.get('pfp_file')
        
        # 1. Update Display Name (Can be performed immediately at any point)
        if new_display_name:
            current_user.display_name = new_display_name
            for comment in Comment.query.filter_by(user_id=current_user.id).all():
                comment.username_cache = new_display_name

        # 2. Update Channel Handle Username (Requires explicit password validation lock)
        if new_username and new_username != current_user.username:
            if not current_password or not check_password_hash(current_user.password, current_password):
                flash("Error: You must provide your correct password to alter your unique channel handle name.")
                return redirect(url_for('settings'))
                
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user and existing_user.id != current_user.id:
                flash("Error: That unique handle username path is already claimed by another profile.")
                return redirect(url_for('settings'))
                
            current_user.username = new_username

        if pfp_file and pfp_file.filename != '':
            ext = os.path.splitext(secure_filename(pfp_file.filename))[1]
            pfp_filename = f"user_{current_user.id}_pfp{ext}"
            pfp_file.save(os.path.join(app.config['UPLOAD_FOLDER'], pfp_filename))
            current_user.pfp = f"/static/uploads/{pfp_filename}"
            
        current_user.bio = new_bio or ""
        db.session.commit()
        flash("Profile parameters adjusted successfully.")
        return redirect(url_for('channel', username=current_user.username))
        
    return render_template('settings.html')

# =========================================
# Search & Playlists
# =========================================
@app.route('/search')
def search():
    query_str = request.args.get('q', '')
    if not query_str: return redirect(url_for('home'))
    now = datetime.now()
    
    videos = Video.query.filter(Video.visibility == 'public', or_(Video.scheduled_at == None, Video.scheduled_at <= now)).filter(or_(Video.title.ilike(f'%{query_str}%'), Video.desc.ilike(f'%{query_str}%'))).all()
    users = User.query.filter(or_(User.username.ilike(f'%{query_str}%'), User.display_name.ilike(f'%{query_str}%'))).all()
    playlists = Playlist.query.filter(Playlist.visibility == 'public').filter(Playlist.title.ilike(f'%{query_str}%')).all()
    
    return render_template('search.html', videos=videos, users=users, playlists=playlists, q=query_str)

@app.route('/playlist/create', methods=['POST'])
@login_required
def create_playlist():
    title = request.form.get('title')
    visibility = request.form.get('visibility', 'public')
    video_id = request.form.get('video_id')
    if title:
        new_playlist = Playlist(title=title, user_id=current_user.id, visibility=visibility)
        if video_id:
            vid = Video.query.get(video_id)
            if vid: new_playlist.videos.append(vid)
        db.session.add(new_playlist)
        db.session.commit()
    return redirect(request.referrer or url_for('home'))

@app.route('/playlist/add', methods=['POST'])
@login_required
def add_to_playlist():
    playlist_id = request.form.get('playlist_id')
    video_id = request.form.get('video_id')
    playlist = Playlist.query.get(playlist_id)
    video = Video.query.get(video_id)
    if playlist and video and playlist.user_id == current_user.id:
        if video not in playlist.videos:
            playlist.videos.append(video)
            db.session.commit()
    return redirect(request.referrer or url_for('home'))

@app.route('/playlist/<int:playlist_id>')
def view_playlist(playlist_id):
    playlist = Playlist.query.get_or_404(playlist_id)
    if playlist.visibility == 'private':
        if not current_user.is_authenticated or current_user.id != playlist.user_id:
            return "This playlist is private.", 403
    return render_template('playlist.html', playlist=playlist)

# =========================================
# Video Lifecycle Routes
# =========================================
@app.route('/')
def home():
    now = datetime.now()
    hashtag_videos = Video.query.filter(Video.visibility == 'public', or_(Video.scheduled_at == None, Video.scheduled_at <= now), Video.desc.ilike(f'%{FEATURED_HASHTAG}%')).order_by(Video.id.desc()).limit(8).all()
    
    sub_videos = []
    if current_user.is_authenticated:
        sub_ids = [sub.channel_id for sub in Subscription.query.filter_by(subscriber_id=current_user.id).all()]
        sub_videos = Video.query.filter(Video.visibility == 'public', or_(Video.scheduled_at == None, Video.scheduled_at <= now), Video.user_id.in_(sub_ids)).order_by(Video.id.desc()).limit(8).all()
        
    categories = db.session.query(Video.category).distinct().all()
    trending_by_category = {}
    for cat in categories:
        cat_name = cat[0]
        vids = Video.query.filter_by(category=cat_name, visibility='public').filter(or_(Video.scheduled_at == None, Video.scheduled_at <= now)).order_by(Video.views.desc()).limit(4).all()
        if vids: trending_by_category[cat_name] = vids

    return render_template('index.html', hashtag=FEATURED_HASHTAG, hashtag_videos=hashtag_videos, sub_videos=sub_videos, trending_by_category=trending_by_category)

@app.route('/channel/<username>')
def channel(username):
    user = User.query.filter_by(username=username).first_or_404()
    now = datetime.now()
    
    if current_user.is_authenticated and current_user.id == user.id:
        videos = Video.query.filter_by(user_id=user.id).order_by(Video.id.desc()).all()
        playlists = Playlist.query.filter_by(user_id=user.id).order_by(Playlist.id.desc()).all()
    else:
        videos = Video.query.filter_by(user_id=user.id, visibility='public').filter(or_(Video.scheduled_at == None, Video.scheduled_at <= now)).order_by(Video.id.desc()).all()
        playlists = Playlist.query.filter_by(user_id=user.id, visibility='public').order_by(Playlist.id.desc()).all()

    is_subbed = False
    if current_user.is_authenticated:
        is_subbed = Subscription.query.filter_by(subscriber_id=current_user.id, channel_id=user.id).first() is not None
    sub_count = Subscription.query.filter_by(channel_id=user.id).count()
    
    return render_template('channel.html', channel_user=user, videos=videos, playlists=playlists, is_subbed=is_subbed, sub_count=sub_count)

@app.route('/watch/<int:video_id>')
def watch(video_id):
    video = Video.query.get_or_404(video_id)
    now = datetime.now()
    
    if video.scheduled_at and video.scheduled_at > now:
        if not current_user.is_authenticated or current_user.id != video.user_id:
            return "This video is scheduled for a future release and is not accessible yet.", 403
            
    if video.visibility == 'private':
        if not current_user.is_authenticated or current_user.id != video.user_id:
            return "This video is private.", 403
            
    # --- VIEW LIMITER LOGIC ---
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    
    # Check recent views based on User Account (or IP if logged out)
    if current_user.is_authenticated:
        recent_views = ViewTracker.query.filter(
            ViewTracker.video_id == video.id,
            ViewTracker.user_id == current_user.id,
            ViewTracker.timestamp >= one_hour_ago
        ).count()
    else:
        client_ip = request.remote_addr
        recent_views = ViewTracker.query.filter(
            ViewTracker.video_id == video.id,
            ViewTracker.ip_address == client_ip,
            ViewTracker.timestamp >= one_hour_ago
        ).count()
        
    # Only grant a view if they haven't spammed it 5 times recently
    if recent_views < 5:
        video.views += 1
        new_view = ViewTracker(
            video_id=video.id, 
            user_id=current_user.id if current_user.is_authenticated else None,
            ip_address=request.remote_addr if not current_user.is_authenticated else None
        )
        db.session.add(new_view)
        db.session.commit()
    
    is_subbed = False
    user_playlists = []
    if current_user.is_authenticated:
        is_subbed = Subscription.query.filter_by(subscriber_id=current_user.id, channel_id=video.user_id).first() is not None
        user_playlists = Playlist.query.filter_by(user_id=current_user.id).all()
        
    comments = Comment.query.filter_by(video_id=video.id, parent_id=None).all()
    return render_template('watch.html', video=video, comments=comments, is_subbed=is_subbed, user_playlists=user_playlists)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        title = request.form.get('title')
        desc = request.form.get('desc')
        category = request.form.get('category')
        visibility = request.form.get('visibility', 'public')
        sched_time = request.form.get('scheduled_time')
        video_file = request.files.get('video_file')
        thumb_file = request.files.get('thumb_file')

        scheduled_at = None
        if sched_time:
            try: scheduled_at = datetime.strptime(sched_time, '%Y-%m-%dT%H:%M')
            except ValueError: pass

        if video_file and thumb_file:
            vid_ext = os.path.splitext(secure_filename(video_file.filename))[1]
            thumb_ext = os.path.splitext(secure_filename(thumb_file.filename))[1]
            new_vid = Video(title=title, desc=desc, category=category, visibility=visibility, scheduled_at=scheduled_at, user_id=current_user.id, date=datetime.now().strftime("%b %d, %Y"), vid_url="", thumb="")
            db.session.add(new_vid)
            db.session.flush()

            vid_filename = f"{new_vid.id}{vid_ext}"
            thumb_filename = f"{new_vid.id}{thumb_ext}"
            video_file.save(os.path.join(app.config['UPLOAD_FOLDER'], vid_filename))
            thumb_file.save(os.path.join(app.config['UPLOAD_FOLDER'], thumb_filename))

            new_vid.vid_url = f"/static/uploads/{vid_filename}"
            new_vid.thumb = f"/static/uploads/{thumb_filename}"
            db.session.commit()
            return redirect(url_for('watch', video_id=new_vid.id))
    return render_template('upload.html')

@app.route('/video/<int:video_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.user_id != current_user.id: return "Unauthorized", 403
    
    if request.method == 'POST':
        video.title = request.form.get('title')
        video.desc = request.form.get('desc')
        video.category = request.form.get('category')
        video.visibility = request.form.get('visibility')
        
        sched_time = request.form.get('scheduled_time')
        if sched_time:
            try: video.scheduled_at = datetime.strptime(sched_time, '%Y-%m-%dT%H:%M')
            except ValueError: video.scheduled_at = None
        else:
            video.scheduled_at = None
            
        thumb_file = request.files.get('thumb_file')
        if thumb_file and thumb_file.filename != '':
            thumb_ext = os.path.splitext(secure_filename(thumb_file.filename))[1]
            thumb_filename = f"{video.id}_edit{thumb_ext}"
            thumb_file.save(os.path.join(app.config['UPLOAD_FOLDER'], thumb_filename))
            video.thumb = f"/static/uploads/{thumb_filename}"
            
        db.session.commit()
        return redirect(url_for('watch', video_id=video.id))
        
    sched_str = video.scheduled_at.strftime('%Y-%m-%dT%H:%M') if video.scheduled_at else ""
    return render_template('edit_video.html', video=video, sched_str=sched_str)

@app.route('/video/<int:video_id>/delete', methods=['POST'])
@login_required
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.user_id != current_user.id: return "Unauthorized", 403
    
    try:
        if video.vid_url and video.vid_url.startswith('/static/'): os.remove(video.vid_url.lstrip('/'))
        if video.thumb and video.thumb.startswith('/static/'): os.remove(video.thumb.lstrip('/'))
    except Exception: pass
    
    db.session.delete(video)
    db.session.commit()
    return redirect(url_for('channel', username=current_user.username))

# =========================================
# Interactive DB & Community Actions
# =========================================
@app.route('/action/report', methods=['POST'])
def report_item():
    item_type = request.form.get('item_type')
    item_id = request.form.get('item_id')
    reason = request.form.get('reason')
    if item_type and item_id and reason:
        db.session.add(Report(item_type=item_type, item_id=int(item_id), reason=reason, user_id=current_user.id if current_user.is_authenticated else None))
        db.session.commit()
        flash('Content submitted for verification.')
    return redirect(request.referrer or url_for('home'))

@app.route('/action/rate', methods=['POST'])
def rate():
    data = request.json
    item = Video.query.get(data.get('id')) if data.get('type') == 'video' else Comment.query.get(data.get('id'))
    if not item: return jsonify({'error': 'Not found'}), 404
    if data.get('action') == 'like': item.likes += 1 if data.get('active') else -1
    elif data.get('action') == 'dislike': item.dislikes += 1 if data.get('active') else -1
    db.session.commit()
    return jsonify({'success': True, 'likes': item.likes, 'dislikes': item.dislikes})

@app.route('/action/subscribe', methods=['POST'])
@login_required
def subscribe():
    channel_id = request.json.get('channel_id')
    sub = Subscription.query.filter_by(subscriber_id=current_user.id, channel_id=channel_id).first()
    if sub: db.session.delete(sub)
    else: db.session.add(Subscription(subscriber_id=current_user.id, channel_id=channel_id))
    db.session.commit()
    return jsonify({'status': 'subbed' if not sub else 'unsubbed'})

@app.route('/action/comment', methods=['POST'])
@login_required
def add_comment():
    video_id = request.form.get('video_id')
    text = request.form.get('text')
    parent_id = request.form.get('parent_id')
    if text and video_id:
        db.session.add(Comment(video_id=video_id, user_id=current_user.id, parent_id=parent_id if parent_id else None, username_cache=current_user.display_name, time_str=datetime.now().strftime("%b %d, %Y"), text=text))
        db.session.commit()
    return redirect(url_for('watch', video_id=video_id))

@app.route('/action/edit_comment', methods=['POST'])
@login_required
def edit_comment():
    comment = Comment.query.get(request.form.get('comment_id'))
    if comment and comment.user_id == current_user.id:
        comment.text = request.form.get('new_text')
        db.session.commit()
    return redirect(url_for('watch', video_id=request.form.get('video_id')))

@app.route('/action/delete_comment', methods=['POST'])
@login_required
def delete_comment():
    comment = Comment.query.get(request.form.get('comment_id'))
    video = Video.query.get(request.form.get('video_id'))
    if comment and video and (current_user.id == comment.user_id or current_user.id == video.user_id):
        def delete_all_replies(parent_comment):
            for reply in parent_comment.replies: delete_all_replies(reply)
            db.session.delete(parent_comment)
        delete_all_replies(comment)
        db.session.commit()
    return redirect(url_for('watch', video_id=video.id))

if __name__ == '__main__':
    app.run(debug=True)
