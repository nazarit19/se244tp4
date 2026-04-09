'''
MIT License

Copyright (c) 2019 Arshdeep Bahga and Vijay Madisetti

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

#!flask/bin/python
from flask import Flask, jsonify, abort, request, make_response, url_for
from flask import render_template, redirect, session, flash
import os
import io
import time
import datetime
from datetime import timedelta
import exifread
import json
from urllib.parse import urlparse, unquote
import pymysql
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image

load_dotenv()

app = Flask(__name__, template_folder="./", static_url_path="/assets", static_folder="assets")

secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    # Keep development sessions stable across app reloads when SECRET_KEY is missing.
    secret_key = "dev-secret-key-change-me"

app.secret_key = secret_key
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.getenv("SESSION_LIFETIME_HOURS", "24")))
)

ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg'])
BUCKET_NAME=os.getenv("BUCKET_NAME")
GCS_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCS_PROJECT")
GCS_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GCS_CREDENTIALS_PATH")
DB_HOSTNAME="34.173.242.26"
DB_USERNAME=os.getenv("USERNAME")
DB_PASSWORD=os.getenv("PASSWORD")
DB_NAME=os.getenv("DB_NAME")
PHOTOS_PER_PAGE = int(os.getenv("PHOTOS_PER_PAGE", "12"))
SIGNED_URL_TTL_MINUTES = int(os.getenv("SIGNED_URL_TTL_MINUTES", "60"))
THUMBNAIL_JPEG_QUALITY = int(os.getenv("THUMBNAIL_JPEG_QUALITY", "75"))

# Metadata access on VMs can break when proxy settings or custom CA settings intercept requests.
# Prefer the link-local metadata endpoint and force metadata hosts into no_proxy.
METADATA_ENDPOINTS = "metadata.google.internal,169.254.169.254"


def _append_no_proxy(existing_value, required_hosts):
    existing_hosts = [h.strip() for h in (existing_value or "").split(',') if h.strip()]
    merged = existing_hosts[:]
    for host in [h.strip() for h in required_hosts.split(',') if h.strip()]:
        if host not in merged:
            merged.append(host)
    return ','.join(merged)


os.environ["NO_PROXY"] = _append_no_proxy(os.getenv("NO_PROXY"), METADATA_ENDPOINTS)
os.environ["no_proxy"] = _append_no_proxy(os.getenv("no_proxy"), METADATA_ENDPOINTS)
# Force metadata traffic to HTTP link-local endpoint to avoid SSL validation issues.
os.environ["GCE_METADATA_HOST"] = "169.254.169.254"
os.environ["GCE_METADATA_IP"] = "169.254.169.254"
os.environ["GCE_METADATA_ROOT"] = "http://169.254.169.254/computeMetadata/v1/"

# Import google auth/storage modules after metadata env overrides are set.
from google.cloud import storage
from google.auth.exceptions import DefaultCredentialsError
from google.auth import compute_engine
from google.auth.transport.requests import Request
from google.api_core.exceptions import NotFound, GoogleAPIError, Forbidden

GCS_REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/devstorage.read_write",
    "https://www.googleapis.com/auth/cloud-platform",
]


def create_gcs_client():
    if GCS_CREDENTIALS_PATH:
        credentials_path = os.path.expanduser(GCS_CREDENTIALS_PATH)
        if not os.path.isabs(credentials_path):
            credentials_path = os.path.abspath(credentials_path)
        if not os.path.exists(credentials_path):
            raise RuntimeError("Google credentials file not found at: " + credentials_path)
        return storage.Client.from_service_account_json(credentials_path, project=GCS_PROJECT)

    # Prefer explicit metadata-backed credentials on GCE VMs.
    try:
        gce_credentials = compute_engine.Credentials(scopes=GCS_REQUIRED_SCOPES)
        gce_credentials.refresh(Request())
        return storage.Client(project=GCS_PROJECT, credentials=gce_credentials)
    except Exception as metadata_error:
        app.logger.info("Compute Engine metadata credentials unavailable: %s", metadata_error)
        pass

    try:
        return storage.Client(project=GCS_PROJECT)
    except DefaultCredentialsError as error:
        raise RuntimeError(
            "Google Cloud credentials are not configured. On a VM, ensure metadata.google.internal and 169.254.169.254 bypass proxies and the system CA bundle is installed. For local development, run 'gcloud auth application-default login'."
        ) from error


GCS_CLIENT = None
PHOTO_USERID_IS_NUMERIC = None


def get_gcs_client():
    global GCS_CLIENT
    if GCS_CLIENT is None:
        GCS_CLIENT = create_gcs_client()
    return GCS_CLIENT


def is_photo_userid_numeric():
    global PHOTO_USERID_IS_NUMERIC
    if PHOTO_USERID_IS_NUMERIC is not None:
        return PHOTO_USERID_IS_NUMERIC

    try:
        conn = pymysql.connect(host=DB_HOSTNAME,
                               user=DB_USERNAME,
                               passwd=DB_PASSWORD,
                               db=DB_NAME,
                               port=3306)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='photogallery' AND COLUMN_NAME='UserID';",
            (DB_NAME,)
        )
        row = cursor.fetchone()
        conn.close()
        numeric_types = {
            'tinyint', 'smallint', 'mediumint', 'int', 'integer',
            'bigint', 'decimal', 'numeric', 'float', 'double'
        }
        PHOTO_USERID_IS_NUMERIC = bool(row and row[0] and row[0].lower() in numeric_types)
    except Exception:
        PHOTO_USERID_IS_NUMERIC = False

    return PHOTO_USERID_IS_NUMERIC


def get_photo_userid_value():
    if not is_photo_userid_numeric():
        return session.get('username')

    user_id = session.get('user_id')
    if user_id is not None:
        return user_id

    username = session.get('username')
    if not username:
        return None

    conn = pymysql.connect(host=DB_HOSTNAME,
                           user=DB_USERNAME,
                           passwd=DB_PASSWORD,
                           db=DB_NAME,
                           port=3306)
    cursor = conn.cursor()
    cursor.execute("SELECT UserID FROM photogallery.Users WHERE Email=%s;", (username,))
    row = cursor.fetchone()
    conn.close()

    if row:
        session['user_id'] = row[0]
        return row[0]
    return None


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_blob_path(stored_reference):
    if not stored_reference:
        return None

    if stored_reference.startswith('gcs://'):
        parsed = urlparse(stored_reference)
        if parsed.netloc == BUCKET_NAME:
            return parsed.path.lstrip('/')
        return None

    if stored_reference.startswith('https://storage.googleapis.com/'):
        parsed = urlparse(stored_reference)
        path_parts = parsed.path.lstrip('/').split('/', 1)
        if len(path_parts) == 2 and path_parts[0] == BUCKET_NAME:
            return unquote(path_parts[1])
        return None

    if stored_reference.startswith('photos/'):
        return stored_reference

    return None


def resolve_photo_url(stored_reference):
    blob_path = extract_blob_path(stored_reference)
    if blob_path:
        return url_for('serve_blob', blob_path=blob_path)
    return stored_reference


def get_page_value(request_args):
    page = request_args.get('page', 1, type=int)
    if not page or page < 1:
        return 1
    return page


def normalize_thumbnail_width(width):
    if not width:
        return None
    return max(120, min(int(width), 1600))


def get_thumbnail_blob_path(blob_path, width):
    return "thumbnails/w" + str(width) + "/" + blob_path


def ensure_thumbnail_blob(bucket, original_blob_path, width):
    thumbnail_path = get_thumbnail_blob_path(original_blob_path, width)
    thumbnail_blob = bucket.blob(thumbnail_path)
    if thumbnail_blob.exists():
        return thumbnail_blob

    original_blob = bucket.blob(original_blob_path)
    original_bytes = original_blob.download_as_bytes(timeout=20)
    image = Image.open(io.BytesIO(original_bytes))

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    image.thumbnail((width, width * 10))

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY, optimize=True)
    output.seek(0)

    thumbnail_blob.upload_from_file(output, content_type="image/jpeg")
    thumbnail_blob.cache_control = "public, max-age=31536000"
    thumbnail_blob.patch()
    return thumbnail_blob


@app.before_request
def refresh_logged_in_session():
    if 'username' in session:
        session.permanent = True
        session.modified = True


@app.after_request
def disable_html_cache(response):
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.errorhandler(400)
def bad_request(error):
    return make_response(jsonify({'error': 'Bad request'}), 400)


@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'error': 'Not found'}), 404)

def getExifData(file_stream):
    file_stream.seek(0)
    tags = exifread.process_file(file_stream)
    ExifData={}
    for tag in tags.keys():
        if tag not in ('JPEGThumbnail', 'TIFFThumbnail',
                       'Filename', 'EXIF MakerNote'):
            key="%s"%(tag)
            val="%s"%(tags[tag])
            ExifData[key]=val
    return ExifData

def gcs_uploading(filename, file_stream, content_type=None):
    if not BUCKET_NAME:
        raise ValueError("BUCKET_NAME is not configured")

    gcs_client = get_gcs_client()
    bucket = gcs_client.bucket(BUCKET_NAME)
    blob_path = "photos/" + filename
    print(blob_path)
    blob = bucket.blob(blob_path)
    file_stream.seek(0)
    try:
        blob.upload_from_file(file_stream, content_type=content_type)
    except Forbidden as error:
        raise RuntimeError(
            "Cloud Storage upload forbidden. On Google Compute Engine, use a service account with Storage Object Admin and VM access scopes that include cloud-platform or devstorage.read_write. "
            "If VM scopes are restricted, set GOOGLE_APPLICATION_CREDENTIALS to a service-account key file with write permissions."
        ) from error

    bucket.reload()
    ubla_enabled = bool(bucket.iam_configuration.uniform_bucket_level_access_enabled)
    if not ubla_enabled:
        try:
            blob.make_public()
        except Exception as error:
            app.logger.warning("Could not make blob public for %s: %s", blob_path, error)
    else:
        app.logger.info(
            "Uniform bucket-level access is enabled; skipping object ACL update for %s",
            blob_path
        )

    return "gcs://" + BUCKET_NAME + "/" + blob_path


@app.route('/media/<path:blob_path>', methods=['GET'])
def serve_blob(blob_path):
    gcs_client = get_gcs_client()
    bucket = gcs_client.bucket(BUCKET_NAME)
    requested_width = normalize_thumbnail_width(request.args.get('w', type=int))
    blob = bucket.blob(blob_path)

    if requested_width:
        try:
            blob = ensure_thumbnail_blob(bucket, blob_path, requested_width)
        except Exception as error:
            app.logger.warning("Thumbnail generation failed for %s: %s", blob_path, error)
            blob = bucket.blob(blob_path)

    # Redirect to a signed Cloud Storage URL so browsers fetch media directly.
    try:
        signed_url = blob.generate_signed_url(
            version='v4',
            expiration=timedelta(minutes=SIGNED_URL_TTL_MINUTES),
            method='GET'
        )
        response = redirect(signed_url, code=302)
        response.headers['Cache-Control'] = 'public, max-age=300'
        return response
    except Exception as error:
        app.logger.info("Signed URL generation failed for %s, falling back to proxy download: %s", blob_path, error)

    try:
        payload = blob.download_as_bytes(timeout=20)
        response = make_response(payload)
        response.headers['Content-Type'] = blob.content_type or 'application/octet-stream'
        if requested_width:
            response.headers['Cache-Control'] = 'public, max-age=31536000'
        else:
            response.headers['Cache-Control'] = 'public, max-age=300'
        if blob.etag:
            response.headers['ETag'] = blob.etag
        return response
    except NotFound:
        abort(404)
    except GoogleAPIError as error:
        app.logger.warning("Failed to fetch blob %s: %s", blob_path, error)
        abort(502)

@app.route('/', methods=['GET', 'POST'])
def home_page():
    page = get_page_value(request.args)
    offset = (page - 1) * PHOTOS_PER_PAGE

    conn = pymysql.connect (host = DB_HOSTNAME,
                        user = DB_USERNAME,
                        passwd = DB_PASSWORD,
                        db = DB_NAME, 
            port = 3306)
    cursor = conn.cursor ()
    cursor.execute("SELECT COUNT(*) FROM photogallery.photogallery;")
    total_count = cursor.fetchone()[0]
    cursor.execute(
        "SELECT * FROM photogallery.photogallery "
        "ORDER BY PhotoID DESC LIMIT %s OFFSET %s;",
        (PHOTOS_PER_PAGE, offset)
    )
    results = cursor.fetchall()
    
    items=[]
    for item in results:
        photo={}
        photo['PhotoID'] = item[0]
        photo['CreationTime'] = item[1]
        photo['Title'] = item[2]
        photo['Description'] = item[3]
        photo['Tags'] = item[4]
        photo['URL'] = resolve_photo_url(item[5])
        items.append(photo)
    conn.close()
    has_prev = page > 1
    has_next = offset + len(items) < total_count
    return render_template('index.html', photos=items,
                           username=session.get('username'),
                           page=page,
                           has_prev=has_prev,
                           has_next=has_next)

@app.route('/myphotos', methods=['GET'])
def my_photos():
    if 'username' not in session:
        flash('Please log in to view your photos')
        return redirect('/login')
    page = get_page_value(request.args)
    offset = (page - 1) * PHOTOS_PER_PAGE

    conn = pymysql.connect(host=DB_HOSTNAME,
                        user=DB_USERNAME,
                        passwd=DB_PASSWORD,
                        db=DB_NAME,
                        port=3306)
    cursor = conn.cursor()
    owner_id = get_photo_userid_value()
    if owner_id is None:
        conn.close()
        flash('Unable to find your account. Please log in again.')
        return redirect('/login')
    cursor.execute("SELECT COUNT(*) FROM photogallery.photogallery WHERE UserID=%s;", (owner_id,))
    total_count = cursor.fetchone()[0]
    cursor.execute(
        "SELECT * FROM photogallery.photogallery "
        "WHERE UserID=%s ORDER BY PhotoID DESC LIMIT %s OFFSET %s;",
        (owner_id, PHOTOS_PER_PAGE, offset)
    )
    results = cursor.fetchall()
    items=[]
    for item in results:
        photo={}
        photo['PhotoID'] = item[0]
        photo['CreationTime'] = item[1]
        photo['Title'] = item[2]
        photo['Description'] = item[3]
        photo['Tags'] = item[4]
        photo['URL'] = resolve_photo_url(item[5])
        items.append(photo)
    conn.close()
    has_prev = page > 1
    has_next = offset + len(items) < total_count
    return render_template('myphotos.html', photos=items,
                           username=session.get('username'),
                           page=page,
                           has_prev=has_prev,
                           has_next=has_next,
                           searchquery=None)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = pymysql.connect(host=DB_HOSTNAME,
                            user=DB_USERNAME,
                            passwd=DB_PASSWORD,
                            db=DB_NAME,
                            port=3306)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM photogallery.Users WHERE Email=%s;", (email,))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            flash('An account with this email already exists')
            return redirect('/register')
        cursor.execute("INSERT INTO photogallery.Users (Email, PasswordHash) VALUES (%s, %s);",
                       (email, generate_password_hash(password)))
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        session.permanent = True
        session['username'] = email
        session['user_id'] = user_id
        return redirect('/')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = pymysql.connect(host=DB_HOSTNAME,
                            user=DB_USERNAME,
                            passwd=DB_PASSWORD,
                            db=DB_NAME,
                            port=3306)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM photogallery.Users WHERE Email=%s;", (email,))
        user = cursor.fetchone()
        conn.close()
        if not user or not check_password_hash(user[2], password):
            flash('Invalid email or password')
            return redirect('/login')
        session.permanent = True
        session['username'] = email
        session['user_id'] = user[0]
        return redirect('/')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('user_id', None)
    return redirect('/')

@app.route('/add', methods=['GET', 'POST'])
def add_photo():
    if 'username' not in session:
        flash('Please log in to upload photos')
        return redirect('/login')
    if request.method == 'POST':
        file = request.files.get('imagefile')
        title = request.form['title']
        tags = request.form['tags']
        description = request.form['description']

        print(title,tags,description)
        if not file or not file.filename:
            flash('Choose an image before submitting the form')
            return redirect('/add')

        if not allowed_file(file.filename):
            flash('Only PNG and JPG images are supported')
            return redirect('/add')

        filename = secure_filename(file.filename)
        filename_root, filename_ext = os.path.splitext(filename)
        unique_filename = filename_root + '-' + str(int(time.time())) + filename_ext.lower()

        try:
            ExifData = getExifData(file)
            uploadedFileURL = gcs_uploading(unique_filename, file, file.content_type)
            print(ExifData)
            ts=time.time()
            timestamp = datetime.datetime.\
                        fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

            conn = pymysql.connect (host = DB_HOSTNAME,
                        user = DB_USERNAME,
                        passwd = DB_PASSWORD,
                        db = DB_NAME,
            port = 3306)
            cursor = conn.cursor ()

            statement = "INSERT INTO photogallery.photogallery \
                        (CreationTime,Title,Description,Tags,URL,EXIF,UserID) \
                        VALUES (%s, %s, %s, %s, %s, %s, %s);"

            cursor.execute(statement, (
                str(timestamp),
                title,
                description,
                tags,
                uploadedFileURL,
                json.dumps(ExifData),
                get_photo_userid_value()
            ))
            conn.commit()
            conn.close()
        except Exception as error:
            app.logger.exception("Upload failed")
            flash('Upload failed: ' + str(error))
            return redirect('/add')

        return redirect('/')
    else:
        return render_template('form.html')

@app.route('/<int:photoID>', methods=['GET'])
def view_photo(photoID):    
    conn = pymysql.connect (host = DB_HOSTNAME,
                        user = DB_USERNAME,
                        passwd = DB_PASSWORD,
                        db = DB_NAME, 
            port = 3306)
    cursor = conn.cursor ()

    cursor.execute("SELECT * FROM photogallery.photogallery \
                    WHERE PhotoID="+str(photoID)+";")

    results = cursor.fetchall()

    items=[]
    for item in results:
        photo={}
        photo['PhotoID'] = item[0]
        photo['CreationTime'] = item[1]
        photo['Title'] = item[2]
        photo['Description'] = item[3]
        photo['Tags'] = item[4]
        photo['URL'] = resolve_photo_url(item[5])
        photo['ExifData']=json.loads(item[6])
        items.append(photo)
    conn.close()        
    tags=items[0]['Tags'].split(',')
    exifdata=items[0]['ExifData']
    
    return render_template('photodetail.html', photo=items[0], 
                            tags=tags, exifdata=exifdata)

@app.route('/search', methods=['GET'])
def search_page():
    query = request.args.get('query', '')
    page = get_page_value(request.args)
    offset = (page - 1) * PHOTOS_PER_PAGE

    conn = pymysql.connect (host = DB_HOSTNAME,
                        user = DB_USERNAME,
                        passwd = DB_PASSWORD,
                        db = DB_NAME, 
            port = 3306)
    cursor = conn.cursor ()

    like_query = '%' + query + '%'
    cursor.execute(
        "SELECT COUNT(*) FROM photogallery.photogallery "
        "WHERE Title LIKE %s OR Description LIKE %s OR Tags LIKE %s;",
        (like_query, like_query, like_query)
    )
    total_count = cursor.fetchone()[0]
    cursor.execute(
        "SELECT * FROM photogallery.photogallery "
        "WHERE Title LIKE %s OR Description LIKE %s OR Tags LIKE %s "
        "ORDER BY PhotoID DESC LIMIT %s OFFSET %s;",
        (like_query, like_query, like_query, PHOTOS_PER_PAGE, offset)
    )

    results = cursor.fetchall()

    items=[]
    for item in results:
        photo={}
        photo['PhotoID'] = item[0]
        photo['CreationTime'] = item[1]
        photo['Title'] = item[2]
        photo['Description'] = item[3]
        photo['Tags'] = item[4]
        photo['URL'] = resolve_photo_url(item[5])
        photo['ExifData']=item[6]
        items.append(photo)
    conn.close()        
    has_prev = page > 1
    has_next = offset + len(items) < total_count
    return render_template('search.html', photos=items,
                            searchquery=query,
                            page=page,
                            has_prev=has_prev,
                            has_next=has_next)

@app.route('/mysearch', methods=['GET'])
def my_search_page():
    if 'username' not in session:
        return redirect('/login')
    query = request.args.get('query', '')
    page = get_page_value(request.args)
    offset = (page - 1) * PHOTOS_PER_PAGE

    conn = pymysql.connect(host=DB_HOSTNAME,
                        user=DB_USERNAME,
                        passwd=DB_PASSWORD,
                        db=DB_NAME,
                        port=3306)
    cursor = conn.cursor()
    owner_id = get_photo_userid_value()
    if owner_id is None:
        conn.close()
        flash('Unable to find your account. Please log in again.')
        return redirect('/login')

    like_query = '%' + query + '%'
    cursor.execute(
        "SELECT COUNT(*) FROM photogallery.photogallery "
        "WHERE UserID=%s AND (Title LIKE %s OR Description LIKE %s OR Tags LIKE %s);",
        (owner_id, like_query, like_query, like_query)
    )
    total_count = cursor.fetchone()[0]
    cursor.execute(
        "SELECT * FROM photogallery.photogallery "
        "WHERE UserID=%s AND (Title LIKE %s OR Description LIKE %s OR Tags LIKE %s) "
        "ORDER BY PhotoID DESC LIMIT %s OFFSET %s;",
        (owner_id, like_query, like_query, like_query, PHOTOS_PER_PAGE, offset)
    )
    results = cursor.fetchall()
    items=[]
    for item in results:
        photo={}
        photo['PhotoID'] = item[0]
        photo['CreationTime'] = item[1]
        photo['Title'] = item[2]
        photo['Description'] = item[3]
        photo['Tags'] = item[4]
        photo['URL'] = resolve_photo_url(item[5])
        items.append(photo)
    conn.close()
    has_prev = page > 1
    has_next = offset + len(items) < total_count
    return render_template('myphotos.html', photos=items,
                           username=session.get('username'),
                           page=page,
                           has_prev=has_prev,
                           has_next=has_next,
                           searchquery=query)

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
