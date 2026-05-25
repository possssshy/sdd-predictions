"""
Book Oracle — Flask сервер
"""
from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, abort
import pdfplumber
import os, json, re, random

app = Flask(__name__, static_folder='static')

app.secret_key = os.environ.get('SECRET_KEY', 'book-oracle-secret-2024')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'slashdotdash')

# Book state — stored in memory (reloads on restart)
book_state = {
    'pages': {},
    'total_pages': 0,
    'title': '',
    'lines_take': 2
}

# ── Static files ──────────────────────────────────────────────────────────────
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# ── Public page ───────────────────────────────────────────────────────────────
@app.route('/')
def index():
    response = send_from_directory('static', 'index.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ── Admin pages ───────────────────────────────────────────────────────────────
@app.route('/admin')
def admin():
    if not session.get('admin'):
        return redirect('/admin/login')
    return send_from_directory('static', 'admin.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        data = request.json or {}
        if data.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'Невірний пароль'}), 401
    return send_from_directory('static', 'login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect('/admin/login')

# ── API: book info for public page ────────────────────────────────────────────
@app.route('/api/book-info')
def book_info():
    return jsonify({
        'title': book_state['title'],
        'total_pages': book_state['total_pages'],
        'loaded': bool(book_state['pages'])
    })

# ── API: upload PDF (admin only) ──────────────────────────────────────────────
@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():
    if not session.get('admin'):
        abort(403)
    if 'pdf' not in request.files:
        return jsonify({'error': 'Файл не надіслано'}), 400
    f = request.files['pdf']
    pages = {}
    try:
        with pdfplumber.open(f) as pdf:
            total = len(pdf.pages)
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    lines = [l.strip() for l in text.split('\n') if l.strip()]
                    if lines:
                        pages[str(i)] = lines
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    book_state['pages'] = pages
    book_state['total_pages'] = total
    book_state['title'] = request.form.get('title', f.filename.replace('.pdf', ''))
    book_state['lines_take'] = int(request.form.get('lines_take', 2))

    return jsonify({
        'ok': True,
        'title': book_state['title'],
        'total_pages': total,
        'total_lines': sum(len(v) for v in pages.values())
    })

# ── API: set lines_take (admin) ───────────────────────────────────────────────
@app.route('/api/settings', methods=['POST'])
def settings():
    if not session.get('admin'):
        abort(403)
    data = request.json or {}
    if 'lines_take' in data:
        book_state['lines_take'] = int(data['lines_take'])
    if 'title' in data:
        book_state['title'] = data['title']
    return jsonify({'ok': True})

# ── Text extraction helpers ───────────────────────────────────────────────────
def extract_text(page_lines, line_num, lines_take):
    idx = line_num - 1
    start_idx = idx
    if start_idx > 0:
        target = page_lines[start_idx]
        if target and (target[0].islower() or target[0] in ',:;'):
            start_idx = max(0, start_idx - 1)

    window_lines = page_lines[start_idx:start_idx + lines_take + 8]

    joined_parts = []
    for line in window_lines:
        if joined_parts and joined_parts[-1].endswith('-'):
            joined_parts[-1] = joined_parts[-1][:-1] + line
        else:
            joined_parts.append(line)
    raw = ' '.join(joined_parts)

    cap_match = re.search(r'[А-ЯІЇЄA-Z]', raw)
    dash_match = re.search(r'[\u2014\-]\s*(?=[а-яіїєА-ЯІЇЄ])', raw)

    if cap_match and dash_match:
        if cap_match.start() <= dash_match.start() + 3:
            raw = raw[cap_match.start():]
        else:
            raw = raw[dash_match.start():]
    elif cap_match:
        raw = raw[cap_match.start():]
    elif dash_match:
        raw = raw[dash_match.start():]

    min_chars = 40
    max_chars = 400
    endings = [m.end() for m in re.finditer(r'[.!?»][)\s»"\']*', raw)]
    text = raw
    for end in endings:
        candidate = raw[:end].strip()
        if len(candidate) >= min_chars:
            text = candidate
            break
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(' ', 1)[0] + '...'
    return text

def get_random(pages, lines_take):
    page_keys = list(pages.keys())
    for _ in range(20):
        pk = random.choice(page_keys)
        pl = pages[pk]
        if not pl:
            continue
        ln = random.randint(1, len(pl))
        t = extract_text(pl, ln, lines_take)
        if len(t) >= 40:
            return t, pk, ln
    pk = page_keys[0]
    return extract_text(pages[pk], 1, lines_take), pk, 1

# ── API: get prophecy (public) ────────────────────────────────────────────────
@app.route('/api/prophecy', methods=['POST'])
def prophecy():
    if not book_state['pages']:
        return jsonify({'error': 'Книга ще не завантажена. Зверніться до адміністратора.'}), 503

    data = request.json or {}
    pages = book_state['pages']
    lines_take = book_state['lines_take']

    raw_page = str(data.get('page', '')).strip()
    raw_line = str(data.get('line', '')).strip()

    if not raw_page or not raw_line or raw_page == '0' or raw_line == '0':
        text, used_page, used_line = get_random(pages, lines_take)
        return jsonify({'text': text, 'page': used_page, 'line': used_line, 'mode': 'random'})

    page_lines = pages.get(raw_page)
    if not page_lines:
        return jsonify({'error': f'Сторінка {raw_page} не знайдена. Спробуйте інше число.'}), 404

    line_num = int(raw_line)
    if line_num < 1 or line_num > len(page_lines):
        return jsonify({'error': f'Рядок {raw_line} не існує на сторінці {raw_page}. Максимум: {len(page_lines)}.'}), 404

    text = extract_text(page_lines, line_num, lines_take)
    return jsonify({'text': text, 'page': raw_page, 'line': raw_line, 'mode': 'coordinate'})

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    print('\n  Book Oracle запущено!')
    print('  Публічна: http://localhost:5000')
    print('  Адмін:    http://localhost:5000/admin\n')
    app.run(debug=False, port=5000)
