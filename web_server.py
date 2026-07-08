import time
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return 'OK'

@app.route('/health')
def health():
    return 'OK', 200

if __name__ == '__main__':
    while True:
        try:
            app.run(host='0.0.0.0', port=5000)
        except Exception as e:
            print(f'❌ Flask caiu: {e}. Reiniciando em 5 segundos...')
            time.sleep(5)
