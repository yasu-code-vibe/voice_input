#!/usr/bin/env python3
"""
音声入力転送サーバー
スマホのブラウザ(Android Chrome)から音声入力し、PCのクリップボードへ転送する
"""

import os
import atexit
import socket
import threading
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
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
      height: 100dvh;
      padding: 12px 16px 16px;
      overflow: hidden;
    }
    body.ios    { padding-bottom: 0px; }
    body.android { padding-bottom: 36px;
      gap: 8px;
    }

    /* ── アプリルート ── */
    #app-root {
      width: 100%;
      max-width: 560px;
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
      position: relative;
      overflow: hidden;
    }

    /* ── メイン画面 ── */
    #main-screen {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
      transition: transform 0.3s ease;
    }
    #main-screen.slide-out {
      transform: translateX(-100%);
    }

    /* ── 設定画面 ── */
    #settings-screen {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      background: #1e1e2e;
      transform: translateX(100%);
      transition: transform 0.3s ease;
      overflow-y: auto;
    }
    #settings-screen.slide-in {
      transform: translateX(0);
    }

    /* ── タイトルバー ── */
    .title-bar {
      display: flex;
      align-items: center;
      flex-shrink: 0;
      width: 100%;
      max-width: 560px;
    }
    .title-bar h1 {
      flex: 1;
      font-size: 1.2rem;
      color: #89b4fa;
      text-align: center;
    }
    .title-spacer {
      width: 40px;
      flex-shrink: 0;
    }
    #settings-btn {
      background: none;
      border: none;
      color: #89b4fa;
      font-size: 1.4rem;
      cursor: pointer;
      padding: 4px 8px;
      line-height: 1;
      width: 40px;
      flex-shrink: 0;
    }
    #settings-back-btn {
      background: none;
      border: none;
      color: #89b4fa;
      font-size: 1rem;
      cursor: pointer;
      padding: 4px 8px 4px 0;
      display: flex;
      align-items: center;
      gap: 4px;
    }

    /* ── 設定項目 ── */
    .settings-section {
      border-bottom: 1px solid #313244;
      padding: 16px 0;
    }
    .settings-section:last-child { border-bottom: none; }
    .settings-label {
      font-size: 0.8rem;
      color: #6c7086;
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .settings-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 4px 0;
    }
    .settings-row-title {
      font-size: 0.95rem;
      color: #cdd6f4;
    }
    .settings-row-sub {
      font-size: 0.78rem;
      color: #6c7086;
      margin-top: 2px;
    }

    /* セグメントコントロール（行末付加） */
    .seg-ctrl {
      display: flex;
      background: #313244;
      border-radius: 8px;
      padding: 3px;
      gap: 2px;
    }
    .seg-ctrl button {
      background: none;
      border: none;
      color: #6c7086;
      font-size: 0.8rem;
      padding: 5px 10px;
      border-radius: 6px;
      cursor: pointer;
      transition: background 0.15s, color 0.15s;
      white-space: nowrap;
    }
    .seg-ctrl button.active {
      background: #89b4fa;
      color: #1e1e2e;
      font-weight: bold;
    }

    /* マイクモード切替 */
    #settings-mic-mode-btn {
      background: #313244;
      color: #cdd6f4;
      border: 1px solid #45475a;
      border-radius: 8px;
      padding: 8px 14px;
      font-size: 0.85rem;
      cursor: pointer;
    }

    /* バージョン情報 */
    .version-text {
      font-size: 0.9rem;
      color: #6c7086;
    }

    #history-section {
      width: 100%;
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
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
    #bottom-area {
      width: 100%;
      display: flex;
      flex-direction: column;
      gap: 8px;
      flex-shrink: 0;
    }
    #status { font-size: 0.85rem; color: #a6e3a1; }
    #status.error { color: #f38ba8; }
    #result { font-size: 0.85rem; color: #a6e3a1; }
    #result.error { color: #f38ba8; }
    #main-group {
      display: flex;
      align-items: stretch;
      gap: 10px;
      width: 100%;
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
      transition: background 0.2s;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      align-self: center;
      touch-action: none;
      user-select: none;
      -webkit-user-select: none;
    }
    #mic-btn.listening {
      background: #f38ba8;
      animation: pulse 1s infinite;
    }
    #mic-btn.floating {
      position: fixed;
      z-index: 1000;
      touch-action: none;
    }
    #mic-placeholder {
      display: none;
      flex-shrink: 0;
      width: 72px;
      height: 72px;
      align-self: center;
    }
    #mic-placeholder.visible { display: block; }
    @keyframes pulse {
      0%   { transform: scale(1); }
      50%  { transform: scale(1.08); }
      100% { transform: scale(1); }
    }
    #transcript {
      flex: 1;
      min-height: 72px;
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
    #bottom-bar {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    #mic-mode-btn {
      flex: 1;
      background: #313244;
      color: #a6adc8;
      border: 1px solid #45475a;
      border-radius: 8px;
      padding: 6px 10px;
      font-size: 0.75rem;
      cursor: pointer;
      text-align: center;
    }
  </style>
</head>
<body>
  <div class="title-bar">
    <div class="title-spacer"></div>
    <h1>🎤 音声入力 → VS Code</h1>
    <button id="settings-btn" title="設定">⚙️</button>
  </div>

  <div id="app-root">

    <!-- メイン画面 -->
    <div id="main-screen">
      <div id="history-section">
        <h2>📜 履歴</h2>
        <div id="history-list"></div>
      </div>

      <div id="bottom-area">
        <div id="status">マイクボタンを押して話してください</div>
        <div id="result"></div>
        <div id="main-group">
          <button id="mic-btn" title="音声認識 開始/停止">🎤</button>
          <div id="mic-placeholder"></div>
          <div id="transcript" placeholder="ここにテキストが表示されます"></div>
          <div class="btn-col">
            <button class="btn" id="send-btn" disabled>📋 送信</button>
            <button class="btn" id="clear-btn">🗑 クリア</button>
          </div>
        </div>
        <button class="btn" id="pc-clip-btn">📥 PCクリップボードを取得</button>
        <div id="bottom-bar">
          <button id="mic-mode-btn">🔄 フローティングモードに切替</button>
        </div>
      </div>
    </div>

    <!-- 設定画面 -->
    <div id="settings-screen">
      <div class="title-bar" style="padding: 4px 0 12px;">
        <button id="settings-back-btn">◀ 戻る</button>
        <h1 style="font-size:1.1rem; text-align:center;">設定</h1>
        <div class="title-spacer"></div>
      </div>

      <div class="settings-section">
        <div class="settings-label">入力</div>
        <div class="settings-row">
          <div>
            <div class="settings-row-title">行末の付加文字</div>
            <div class="settings-row-sub">クリップボードへ送信時に末尾に追加</div>
          </div>
          <div class="seg-ctrl" id="suffix-ctrl">
            <button data-val="none">なし</button>
            <button data-val="space">スペース</button>
            <button data-val="newline">改行</button>
          </div>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-label">マイク</div>
        <div class="settings-row-title">マイクボタンのモード</div>
        <div class="settings-row-sub" style="margin: 4px 0 10px;">スナップ：左右にスナップ固定<br>フローティング：画面上を自由移動</div>
        <div class="seg-ctrl" id="mic-mode-ctrl" style="display: inline-flex;">
          <button data-val="snap">スナップ</button>
          <button data-val="float">フローティング</button>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-label">アプリ情報</div>
        <div class="settings-row">
          <div class="settings-row-title">バージョン</div>
          <div class="version-text">v1.0.0</div>
        </div>
      </div>
    </div>

  </div>

  <script>
    if (/iPhone|iPad|iPod/i.test(navigator.userAgent)) document.body.classList.add('ios');
    else if (/Android/i.test(navigator.userAgent)) document.body.classList.add('android');

    const micBtn = document.getElementById('mic-btn');
    const micPlaceholder = document.getElementById('mic-placeholder');
    const mainGroup = document.getElementById('main-group');
    const transcript = document.getElementById('transcript');
    const sendBtn = document.getElementById('send-btn');
    const clearBtn = document.getElementById('clear-btn');
    const statusEl = document.getElementById('status');
    const resultEl = document.getElementById('result');
    const historyList = document.getElementById('history-list');
    const micModeBtn = document.getElementById('mic-mode-btn');

    // --- 設定画面 ---
    const mainScreen     = document.getElementById('main-screen');
    const settingsScreen = document.getElementById('settings-screen');

    document.getElementById('settings-btn').addEventListener('click', () => {
      mainScreen.classList.add('slide-out');
      settingsScreen.classList.add('slide-in');
    });
    document.getElementById('settings-back-btn').addEventListener('click', () => {
      mainScreen.classList.remove('slide-out');
      settingsScreen.classList.remove('slide-in');
    });

    // --- 行末付加設定 ---
    const SUFFIX_KEY = 'voice_suffix';
    const suffixCtrl = document.getElementById('suffix-ctrl');

    function getSuffix() {
      return localStorage.getItem(SUFFIX_KEY) || 'space';
    }
    function setSuffix(val) {
      localStorage.setItem(SUFFIX_KEY, val);
      suffixCtrl.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.val === val);
      });
    }
    suffixCtrl.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => setSuffix(btn.dataset.val));
    });
    setSuffix(getSuffix());

    function applyText(text) {
      const suffix = getSuffix();
      if (suffix === 'space')   return text + ' ';
      if (suffix === 'newline') return text + '\\n';
      return text;
    }

    // --- 設定画面のマイクモード セグメントコントロール ---
    const micModeCtrl = document.getElementById('mic-mode-ctrl');
    function updateMicModeCtrl() {
      micModeCtrl.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.val === micMode);
      });
    }
    micModeCtrl.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.val === 'snap') enterSnapMode();
        else enterFloatMode();
        updateMicModeCtrl();
      });
    });

    // --- マイクボタン移動モード ---
    const MIC_MODE_KEY = 'mic_mode';         // 'snap' | 'float'
    const MIC_SNAP_KEY = 'mic_snap_side';    // 'left' | 'right'
    const MIC_POS_KEY  = 'mic_float_pos';    // {x, y}

    let micMode = localStorage.getItem(MIC_MODE_KEY) || 'snap';

    function applySnapSide(side) {
      localStorage.setItem(MIC_SNAP_KEY, side);
      mainGroup.style.flexDirection = side === 'right' ? 'row-reverse' : 'row';
    }

    function applyFloatPos(x, y) {
      const r = 36;
      x = Math.max(r, Math.min(window.innerWidth  - r, x));
      y = Math.max(r, Math.min(window.innerHeight - r, y));
      micBtn.style.left      = x + 'px';
      micBtn.style.top       = y + 'px';
      micBtn.style.marginLeft = '-36px';
      micBtn.style.marginTop  = '-36px';
      localStorage.setItem(MIC_POS_KEY, JSON.stringify({x, y}));
    }

    function enterSnapMode() {
      micMode = 'snap';
      localStorage.setItem(MIC_MODE_KEY, 'snap');
      micBtn.classList.remove('floating');
      micBtn.style.cssText = '';
      micPlaceholder.classList.remove('visible');
      mainGroup.insertBefore(micBtn, mainGroup.firstChild);
      const side = localStorage.getItem(MIC_SNAP_KEY) || 'left';
      applySnapSide(side);
    }

    function enterFloatMode() {
      micMode = 'float';
      localStorage.setItem(MIC_MODE_KEY, 'float');
      micBtn.classList.add('floating');
      micPlaceholder.classList.add('visible');
      document.body.appendChild(micBtn);
      const saved = JSON.parse(localStorage.getItem(MIC_POS_KEY) || 'null');
      if (saved) {
        applyFloatPos(saved.x, saved.y);
      } else {
        applyFloatPos(36, window.innerHeight - 120);
      }
    }

    // スナップモード：ドラッグで左右切替
    let snapDragStartX = null;
    micBtn.addEventListener('touchstart', e => {
      if (micMode !== 'snap') return;
      snapDragStartX = e.touches[0].clientX;
    }, {passive: true});
    micBtn.addEventListener('touchend', e => {
      if (micMode !== 'snap' || snapDragStartX === null) return;
      const dx = e.changedTouches[0].clientX - snapDragStartX;
      if (Math.abs(dx) > 20) {
        applySnapSide(dx > 0 ? 'right' : 'left');
      }
      snapDragStartX = null;
    }, {passive: true});

    // フローティングモード：ドラッグで自由移動
    let floatDragging = false;
    let floatDragMoved = false;
    let floatDragStartX = 0, floatDragStartY = 0;
    micBtn.addEventListener('touchstart', e => {
      if (micMode !== 'float') return;
      floatDragging = true;
      floatDragMoved = false;
      floatDragStartX = e.touches[0].clientX;
      floatDragStartY = e.touches[0].clientY;
    }, {passive: true});
    micBtn.addEventListener('touchmove', e => {
      if (!floatDragging || micMode !== 'float') return;
      const dx = e.touches[0].clientX - floatDragStartX;
      const dy = e.touches[0].clientY - floatDragStartY;
      if (Math.sqrt(dx * dx + dy * dy) > 10) {
        e.preventDefault();
        floatDragMoved = true;
        applyFloatPos(e.touches[0].clientX, e.touches[0].clientY);
      }
    }, {passive: false});
    micBtn.addEventListener('touchend', e => {
      floatDragging = false;
    }, {passive: true});

    // 初期化
    if (micMode === 'float') {
      enterFloatMode();
    } else {
      const side = localStorage.getItem(MIC_SNAP_KEY) || 'left';
      applySnapSide(side);
    }
    updateMicModeCtrl();
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
      historyList.scrollTop = historyList.scrollHeight;
    }

    function renderHistory() {
      const history = loadHistory();
      historyList.innerHTML = '';
      history.slice().reverse().forEach(entry => {
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
      if (micMode === 'float' && floatDragMoved) { floatDragMoved = false; return; }
      if (isListening) {
        const current = (finalText + interimText).trim();
        if (current) {
          finalText = current;
          interimText = '';
          transcript.textContent = finalText;
        }
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
          body: JSON.stringify({ text: applyText(text) })
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
      try {
        const res = await fetch('/clipboard');
        const data = await res.json();
        if (data.status === 'ok') {
          addHistory(data.text);
          if (data.text.length <= 50) {
            finalText = data.text;
            transcript.textContent = finalText;
            sendBtn.disabled = false;
          }
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
    pyperclip.copy(text)
    print(f"[受信] {text}")
    return jsonify({'status': 'ok'})


@app.route('/cert', methods=['GET'])
def cert():
    from flask import send_file, abort
    cert_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cert.pem')
    if not os.path.exists(cert_file):
        abort(404)
    return send_file(cert_file, as_attachment=True, download_name='cert.pem', mimetype='application/x-pem-file')


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
    http_port = 5000
    https_port = 5001
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cert_file = os.path.join(script_dir, 'cert.pem')
    key_file = os.path.join(script_dir, 'key.pem')
    use_https = os.path.exists(cert_file) and os.path.exists(key_file)

    print("=" * 50)
    print("  音声入力サーバー起動")
    print(f"  Android用 (HTTP) : http://{ip}:{http_port}")
    if use_https:
        print(f"  iPhone用 (HTTPS) : https://{ip}:{https_port}")
    print("=" * 50)
    print()
    print("【Android 初回のみ】Chromeのマイク許可設定:")
    print(f"  1. Chrome で chrome://flags/#unsafely-treat-insecure-origin-as-secure を開く")
    print(f"  2. テキストボックスに http://{ip}:{http_port} を入力")
    print(f"  3. 'Relaunch' をタップして再起動")
    if use_https:
        print()
        print("【iPhone 初回のみ】iOSの証明書信頼設定が必要です。READMEを参照してください。")
    print()

    if use_https:
        t = threading.Thread(
            target=app.run,
            kwargs={'host': '0.0.0.0', 'port': https_port, 'debug': False, 'ssl_context': (cert_file, key_file)},
            daemon=True
        )
        t.start()

    app.run(host='0.0.0.0', port=http_port, debug=False)
