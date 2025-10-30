from flask import Flask, request, jsonify, render_template
from main import fetch_bilibili_subtitle_text

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/subtitle', methods=['POST'])
def api_subtitle():
    data = request.get_json(force=True)
    url = data.get('url','').strip()
    whitelist = data.get('whitelist', None)
    lang_priority = data.get('lang_priority', None)
    res = fetch_bilibili_subtitle_text(url, whitelist, lang_priority)
    return jsonify(res)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=17772, debug=True)
