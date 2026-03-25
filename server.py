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
      height: 100vh;
      padding: 24px 16px 16px;
      gap: 16px;
      overflow: hidden;
    }
    h1 { font-size: 1.2rem; color: #89b4fa; margin: -8px 0; }
    #status {
      font-size: 0.85rem;
      color: #a6e3a1;
      min-height: 1.2em;
    }
    #status.error { color: #f38ba8; }
    #main-group {
      display: flex;
      align-items: stretch;
      gap: 10px;
      width: 100%;
      max-width: 560px;
    }
    #mic-btn {
      flex-shrink: 0;
      width: 72px;
      height: 72px;
      border-radius: 50%;
      border: none;
      background: #313244;
      font-size: 2rem;
      cursor: pointer;
      transition: background 0.2s, transform 0.1s;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      align-self: center;
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
      flex: 1;
      min-height: 90px;
      background: #313244;
      border: 1px solid #45475a;
      border-radius: 8px;
      padding: 10px;
      font-size: 1rem;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .btn-col {
      display: flex;
      flex-direction: column;
      gap: 8px;
      flex-shrink: 0;
    }
    .btn {
      padding: 10px 14px;
      border: none;
      border-radius: 8px;
      font-size: 0.9rem;
      cursor: pointer;
      font-weight: bold;
      transition: opacity 0.2s;
      white-space: nowrap;
    }
    .btn:disabled { opacity: 0.4; cursor: default; }
    #send-btn { background: #89b4fa; color: #1e1e2e; }
    #clear-btn { background: #45475a; color: #cdd6f4; }
    #pc-clip-btn { background: #a6e3a1; color: #1e1e2e; }
    #result {
      font-size: 0.85rem;
      color: #a6e3a1;
    }
    #result.error { color: #f38ba8; }
    #history-section {
      width: 100%;
      max-width: 480px;
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
      margin-top: -8px;
    }
    #history-section h2 {
      font-size: 0.9rem;
      color: #89b4fa;
      margin-bottom: 8px;
      flex-shrink: 0;
    }
    #history-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      flex: 1;
      min-height: 0;
      overflow-y: auto;
    }
    .history-item {
      display: flex;
      align-items: center;
      gap: 8px;
      background: #313244;
      border-radius: 6px;
      padding: 8px 10px;
    }
    .history-text {
      flex: 1;
      font-size: 0.9rem;
      word-break: break-all;
      color: #cdd6f4;
    }
    .resend-btn {
      flex-shrink: 0;
      background: #45475a;
      color: #cdd6f4;
      border: none;
      border-radius: 6px;
      padding: 6px 10px;
      font-size: 0.8rem;
      cursor: pointer;
    }
    .resend-btn:active { opacity: 0.7; }
  </style>
</head>
<body>
  <h1>🎤 音声入力 → VS Code</h1>
  <div id="status">マイクボタンを押して話してください</div>

  <div id="main-group">
    <button id="mic-btn" title="音声認識 開始/停止">🎤</button>
    <div id="transcript" placeholder="ここにテキストが表示されます"></div>
    <div class="btn-col">
      <button class="btn" id="send-btn" disabled>📋 送信</button>
      <button class="btn" id="clear-btn">🗑 クリア</button>
    </div>
  </div>

  <button class="btn" id="pc-clip-btn" style="width:100%;max-width:560px;">📥 PCクリップボードを取得</button>

  <div id="result"></div>

  <div id="history-section">
    <h2>📜 履歴</h2>
    <div id="history-list"></div>
  </div>

  <script>
    const micBtn = document.getElementById('mic-btn');
    const transcript = document.getElementById('transcript');
    const sendBtn = document.getElementById('send-btn');
    const clearBtn = document.getElementById('clear-btn');
    const statusEl = document.getElementById('status');
    const resultEl = document.getElementById('result');
    const historyList = document.getElementById('history-list');
    const HISTORY_KEY = 'voice_input_history';
    const HISTORY_SEQ_KEY = 'voice_input_seq';
    const HISTORY_MAX = 1000;

    function loadHistory() {
      try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; }
      catch { return []; }
    }

    function saveHistory(history) {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    }

    function nextSeq() {
      const seq = (parseInt(localStorage.getItem(HISTORY_SEQ_KEY) || '-1') + 1) % 1000;
      localStorage.setItem(HISTORY_SEQ_KEY, String(seq));
      return seq;
    }

    function addHistory(text) {
      const history = loadHistory().filter(t => t.text !== text);
      history.unshift({ seq: nextSeq(), text });
      if (history.length > HISTORY_MAX) history.pop();
      saveHistory(history);
      renderHistory();
    }

    function renderHistory() {
      const history = loadHistory();
      historyList.innerHTML = '';
      history.forEach(entry => {
        const text = typeof entry === 'string' ? entry : entry.text;
        const seq  = typeof entry === 'string' ? '' : String(entry.seq).padStart(3, '0');
        const item = document.createElement('div');
        item.className = 'history-item';
        const span = document.createElement('span');
        span.className = 'history-text';
        span.textContent = (seq ? `[${seq}] ` : '') + text;
        const resendBtn = document.createElement('button');
        resendBtn.className = 'resend-btn';
        resendBtn.textContent = '再送';
        resendBtn.addEventListener('click', () => {
          transcript.textContent = text;
          finalText = text;
          sendBtn.disabled = false;
          doSend(true);
        });
        const delBtn = document.createElement('button');
        delBtn.className = 'resend-btn';
        delBtn.textContent = '🗑';
        delBtn.addEventListener('click', () => {
          const history = loadHistory().filter(e => (typeof e === 'string' ? e : e.text) !== text);
          saveHistory(history);
          renderHistory();
        });
        item.appendChild(span);
        item.appendChild(resendBtn);
        item.appendChild(delBtn);
        historyList.appendChild(item);
      });
    }

    renderHistory();

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
          statusEl.textContent = '認識完了。自動送信します...';
          sendBtn.disabled = false;
          doSend();
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

    async function doSend(isResend = false) {
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
          if (!isResend) addHistory(text);
        } else {
          throw new Error(data.message || '不明なエラー');
        }
      } catch (e) {
        resultEl.textContent = '❌ 送信失敗: ' + e.message;
        resultEl.classList.add('error');
        sendBtn.disabled = false;
      }
    }

    sendBtn.addEventListener('click', doSend);

    document.getElementById('pc-clip-btn').addEventListener('click', async () => {
      const pcClipResult = document.getElementById('pc-clip-result');
      try {
        const res = await fetch('/clipboard');
        const data = await res.json();
        if (data.status === 'ok') {
          finalText = data.text;
          transcript.textContent = finalText;
          sendBtn.disabled = false;
          addHistory(finalText);
        } else {
          throw new Error(data.message || '不明なエラー');
        }
      } catch (e) {
        resultEl.textContent = '❌ PCクリップボード取得失敗: ' + e.message;
        resultEl.classList.add('error');
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
    pyperclip.copy(text + ' ')
    print(f"[受信] {text}")
    return jsonify({'status': 'ok'})


@app.route('/clipboard', methods=['GET'])
def clipboard():
    text = pyperclip.paste()
    if not text:
        return jsonify({'status': 'error', 'message': 'クリップボードが空です'}), 200
    print(f"[クリップボード送信] {text[:50]}")
    return jsonify({'status': 'ok', 'text': text})


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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cert_file = os.path.join(script_dir, 'cert.pem')
    key_file = os.path.join(script_dir, 'key.pem')
    use_https = os.path.exists(cert_file) and os.path.exists(key_file)
    scheme = 'https' if use_https else 'http'
    print("=" * 50)
    print("  音声入力サーバー起動")
    print(f"  スマホのChromeでアクセス: {scheme}://{ip}:{port}")
    print("=" * 50)
    print()
    if use_https:
        print("HTTPS モードで起動します（自己署名証明書）")
        print("【初回のみ】iOSの証明書信頼設定が必要です。READMEを参照してください。")
    else:
        print("【初回のみ】Chromeのマイク許可設定:")
        print(f"  1. Chrome で chrome://flags/#unsafely-treat-insecure-origin-as-secure を開く")
        print(f"  2. テキストボックスに http://{ip}:{port} を入力")
        print(f"  3. 'Relaunch' をタップして再起動")
    print()
    ssl_context = (cert_file, key_file) if use_https else None
    app.run(host='0.0.0.0', port=port, debug=False, ssl_context=ssl_context)
