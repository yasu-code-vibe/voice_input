#!/usr/bin/env python3
"""
音声入力転送サーバー
スマホのブラウザ(Android Chrome)から音声入力し、PCのクリップボードへ転送する
"""

import os
import atexit
import socket
import pyperclip
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server.pid')

def _write_pid():
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

def _remove_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass

_write_pid()
atexit.register(_remove_pid)

HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>音声入力</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: sans-serif;
      background: #1e1e2e;
      color: #cdd6f4;
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 100vh;
      padding: 24px 16px;
      gap: 16px;
    }
    h1 { font-size: 1.2rem; color: #89b4fa; }
    #status {
      font-size: 0.85rem;
      color: #a6e3a1;
      min-height: 1.2em;
    }
    #status.error { color: #f38ba8; }
    #mic-btn {
      width: 100px;
      height: 100px;
      border-radius: 50%;
      border: none;
      background: #313244;
      font-size: 2.5rem;
      cursor: pointer;
      transition: background 0.2s, transform 0.1s;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    }
    #mic-btn.listening {
      background: #f38ba8;
      animation: pulse 1s infinite;
    }
    @keyframes pulse {
      0%   { transform: scale(1); }
      50%  { transform: scale(1.08); }
      100% { transform: scale(1); }
    }
    #transcript {
      width: 100%;
      max-width: 480px;
      min-height: 120px;
      background: #313244;
      border: 1px solid #45475a;
      border-radius: 8px;
      padding: 12px;
      font-size: 1rem;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .btn-row {
      display: flex;
      gap: 12px;
      width: 100%;
      max-width: 480px;
    }
    .btn {
      flex: 1;
      padding: 14px;
      border: none;
      border-radius: 8px;
      font-size: 1rem;
      cursor: pointer;
      font-weight: bold;
      transition: opacity 0.2s;
    }
    .btn:disabled { opacity: 0.4; cursor: default; }
    #send-btn { background: #89b4fa; color: #1e1e2e; }
    #clear-btn { background: #45475a; color: #cdd6f4; }
    #result {
      font-size: 0.85rem;
      min-height: 1.2em;
      color: #a6e3a1;
    }
    #result.error { color: #f38ba8; }
  </style>
</head>
<body>
  <h1>🎤 音声入力 → VS Code</h1>
  <div id="status">マイクボタンを押して話してください</div>

  <button id="mic-btn" title="音声認識 開始/停止">🎤</button>

  <div id="transcript" placeholder="ここにテキストが表示されます"></div>

  <div class="btn-row">
    <button class="btn" id="send-btn" disabled>📋 送信（クリップボードへ）</button>
    <button class="btn" id="clear-btn">🗑 クリア</button>
  </div>

  <div id="result"></div>

  <script>
    const micBtn = document.getElementById('mic-btn');
    const transcript = document.getElementById('transcript');
    const sendBtn = document.getElementById('send-btn');
    const clearBtn = document.getElementById('clear-btn');
    const statusEl = document.getElementById('status');
    const resultEl = document.getElementById('result');

    let recognition = null;
    let isListening = false;
    let finalText = '';
    let interimText = '';

    // Web Speech API の初期化
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      statusEl.textContent = 'このブラウザはWeb Speech APIに対応していません。Android Chromeをお使いください。';
      statusEl.classList.add('error');
      micBtn.disabled = true;
    } else {
      recognition = new SpeechRecognition();
      recognition.lang = 'ja-JP';
      recognition.interimResults = true;  // 暫定結果も表示
      recognition.continuous = false;

      recognition.onstart = () => {
        isListening = true;
        micBtn.classList.add('listening');
        micBtn.textContent = '⏹';
        statusEl.textContent = '認識中...';
        statusEl.classList.remove('error');
      };

      recognition.onresult = (event) => {
        interimText = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            finalText += event.results[i][0].transcript;
          } else {
            interimText += event.results[i][0].transcript;
          }
        }
        transcript.textContent = finalText + interimText;
        sendBtn.disabled = (finalText + interimText).trim() === '';
      };

      recognition.onend = () => {
        isListening = false;
        micBtn.classList.remove('listening');
        micBtn.textContent = '🎤';
        interimText = '';
        transcript.textContent = finalText;
        if (finalText.trim()) {
          statusEl.textContent = '認識完了。「送信」でクリップボードへコピーされます。';
          sendBtn.disabled = false;
        } else {
          statusEl.textContent = 'マイクボタンを押して話してください';
        }
      };

      recognition.onerror = (event) => {
        isListening = false;
        micBtn.classList.remove('listening');
        micBtn.textContent = '🎤';
        statusEl.textContent = 'エラー: ' + event.error;
        statusEl.classList.add('error');
      };
    }

    micBtn.addEventListener('click', () => {
      if (isListening) {
        recognition.stop();
      } else {
        finalText = '';
        transcript.textContent = '';
        sendBtn.disabled = true;
        resultEl.textContent = '';
        recognition.start();
      }
    });

    sendBtn.addEventListener('click', async () => {
      const text = transcript.textContent.trim();
      if (!text) return;
      sendBtn.disabled = true;
      try {
        const res = await fetch('/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          resultEl.textContent = '✅ クリップボードにコピーしました！VS CodeでCtrl+Vで貼り付けてください。';
          resultEl.classList.remove('error');
        } else {
          throw new Error(data.message || '不明なエラー');
        }
      } catch (e) {
        resultEl.textContent = '❌ 送信失敗: ' + e.message;
        resultEl.classList.add('error');
        sendBtn.disabled = false;
      }
    });

    clearBtn.addEventListener('click', () => {
      finalText = '';
      interimText = '';
      transcript.textContent = '';
      sendBtn.disabled = true;
      resultEl.textContent = '';
      statusEl.textContent = 'マイクボタンを押して話してください';
      statusEl.classList.remove('error');
    });
  </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/send', methods=['POST'])
def send():
    data = request.get_json(silent=True)
    if not data or 'text' not in data:
        return jsonify({'status': 'error', 'message': 'テキストがありません'}), 400
    text = data['text'].strip()
    if not text:
        return jsonify({'status': 'error', 'message': '空のテキストです'}), 400
    pyperclip.copy(text)
    print(f"[受信] {text}")
    return jsonify({'status': 'ok'})


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())


if __name__ == '__main__':
    ip = get_local_ip()
    port = 5000
    print("=" * 50)
    print("  音声入力サーバー起動")
    print(f"  スマホのChromeでアクセス: http://{ip}:{port}")
    print("=" * 50)
    print()
    print("【初回のみ】Chromeのマイク許可設定:")
    print(f"  1. Chrome で chrome://flags/#unsafely-treat-insecure-origin-as-secure を開く")
    print(f"  2. テキストボックスに http://{ip}:{port} を入力")
    print(f"  3. 'Relaunch' をタップして再起動")
    print()
    app.run(host='0.0.0.0', port=port, debug=False)
