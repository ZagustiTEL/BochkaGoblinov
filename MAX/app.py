from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/features')
def features():
    """Страница с возможностями"""
    return render_template('features.html')

@app.route('/about')
def about():
    """О проекте"""
    return render_template('about.html')

@app.route('/download')
def download():
    """Страница загрузки"""
    return render_template('download.html')

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True, port=5001)