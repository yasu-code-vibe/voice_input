#!/usr/bin/env python3
"""
音声入力転送サーバー
スマホのブラウザ(Android Chrome)から音声入力し、PCのクリップボードへ転送する
"""

import os
import json
import atexit
import socket
import threading
import subprocess
import pyperclip
from flask import Flask, request, jsonify, render_template_string

try:
    import pymysql
    import pymysql.cursors
    _PYMYSQL_AVAILABLE = True
except ImportError:
    _PYMYSQL_AVAILABLE = False

app = Flask(__name__)

PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server.pid')
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'history_server.json')
HISTORY_MAX = 1000

# MySQL設定（環境変数）
DB_HOST = os.environ.get('DB_HOST', '')
DB_PORT = int(os.environ.get('DB_PORT', '3306'))
DB_NAME = os.environ.get('DB_NAME', 'voice_input')
DB_USER = os.environ.get('DB_USER', 'voice_input')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'voice_input_pass')


def _use_mysql():
    """DB_HOSTが設定されている場合はMySQL使用"""
    return bool(DB_HOST) and _PYMYSQL_AVAILABLE


def _get_db_conn():
    """MySQL接続を返す（テーブル初期化込み）"""
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, db=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                text TEXT NOT NULL,
                ts VARCHAR(30) NOT NULL DEFAULT '',
                seq INT NOT NULL DEFAULT 0
            ) CHARACTER SET utf8mb4
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key_name VARCHAR(50) PRIMARY KEY,
                value_int INT NOT NULL DEFAULT 0
            ) CHARACTER SET utf8mb4
        """)
        cur.execute("INSERT IGNORE INTO meta (key_name, value_int) VALUES ('seq', -1)")
    conn.commit()
    return conn


def _db_get_history():
    """MySQL: 全履歴をリストで返す（古い順）"""
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT seq, text, ts FROM history ORDER BY id DESC")
            rows = cur.fetchall()
        return [{'seq': r['seq'], 'text': r['text'], 'ts': r['ts']} for r in rows]
    finally:
        conn.close()


def _db_add_history(text, ts):
    """MySQL: 重複削除→seq採番→INSERT。seqはmeta表で管理"""
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM history WHERE text = %s", (text,))
            cur.execute(
                "UPDATE meta SET value_int = MOD(value_int + 1, 1000) WHERE key_name = 'seq'"
            )
            cur.execute("SELECT value_int FROM meta WHERE key_name = 'seq'")
            row = cur.fetchone()
            seq = row['value_int']
            cur.execute(
                "INSERT INTO history (text, ts, seq) VALUES (%s, %s, %s)",
                (text, ts, seq)
            )
            # HISTORY_MAX超過分を古い順に削除
            cur.execute("SELECT COUNT(*) AS cnt FROM history")
            cnt = cur.fetchone()['cnt']
            if cnt > HISTORY_MAX:
                cur.execute(
                    "DELETE FROM history ORDER BY id ASC LIMIT %s",
                    (cnt - HISTORY_MAX,)
                )
        conn.commit()
        return seq
    finally:
        conn.close()


def _db_delete_history(text):
    """MySQL: 指定テキストの履歴を削除"""
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM history WHERE text = %s", (text,))
        conn.commit()
    finally:
        conn.close()


def _load_server_data():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):  # 旧フォーマット移行
                return {'seq': -1, 'history': data}
            return data
    return {'seq': -1, 'history': []}


def _save_server_data(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def copy_to_clipboard(text):
    """クリップボードにコピー（Docker/WSL2環境対応）"""
    # pyperclip (Windowsネイティブ環境で確実)
    try:
        pyperclip.copy(text)
        return
    except Exception:
        pass
    # clip.exe (WSL2)
    try:
        subprocess.run(['clip.exe'], input=text.encode('utf-16'), check=True)
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    # xclip (Linux)
    try:
        subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode('utf-8'), check=True)
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    raise RuntimeError('クリップボードへの書き込みに失敗しました')


def paste_from_clipboard():
    """クリップボードから取得（Docker/WSL2環境対応）"""
    # powershell.exe Get-Clipboard (Windows / WSL2)
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-Command',
             '[Console]::OutputEncoding=[Text.Encoding]::UTF8;'
             'try { $t = Get-Clipboard -Raw; if ($t) { $t } } catch { }'],
            capture_output=True, timeout=3
        )
        if result.returncode == 0:
            text = result.stdout.decode('utf-8', errors='replace').rstrip('\r\n')
            if text:
                return text
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    # xclip (Linux)
    try:
        result = subprocess.run(
            ['xclip', '-selection', 'clipboard', '-o'],
            capture_output=True, timeout=3
        )
        if result.returncode == 0:
            return result.stdout.decode('utf-8', errors='replace')
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    # pyperclip (Windowsネイティブ環境のフォールバック)
    try:
        return pyperclip.paste()
    except Exception:
        pass
    raise RuntimeError('クリップボードへの読み取りに失敗しました')

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
  <title>音声入力→AI</title>
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
    body.ios    { padding-top: 30px; padding-bottom: 0px; }
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
      overflow: hidden;
    }
    #settings-body {
      flex: 1;
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
      background: none;
      padding: 0;
      gap: 8px;
    }
    .settings-section .seg-ctrl { justify-content: flex-end; }
    .settings-section > .btn { display: block; margin-left: auto; }
    .seg-ctrl button {
      background: #45475a;
      border: none;
      color: #cdd6f4;
      font-size: 0.9rem;
      font-weight: bold;
      padding: 10px 14px;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.15s, color 0.15s;
      white-space: nowrap;
      min-width: 90px;
      text-align: center;
    }
    .seg-ctrl button.active {
      background: #89b4fa;
      color: #1e1e2e;
    }

    /* マイクモード切替 */


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
      flex-wrap: wrap;
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
      cursor: pointer;
      user-select: none;
    }
    .history-ts {
      display: none;
      width: 100%;
      font-size: 0.75rem;
      color: #6c7086;
      padding-top: 2px;
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
    .seq-local { color: #89b4fa; font-weight: bold; }
    .seq-server { color: #f9e2af; font-weight: bold; }
    #confirm-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.6);
      z-index: 200;
      align-items: center;
      justify-content: center;
    }
    #confirm-overlay.show { display: flex; }
    #confirm-dialog {
      background: #313244;
      border-radius: 12px;
      padding: 24px 20px 16px;
      width: min(300px, 85vw);
      text-align: center;
    }
    #confirm-dialog p {
      margin: 0 0 20px;
      color: #cdd6f4;
      font-size: 0.95rem;
    }
    #confirm-dialog .confirm-btns {
      display: flex;
      gap: 10px;
      justify-content: center;
    }
    #confirm-dialog .confirm-btns button {
      flex: 1;
      padding: 10px;
      border: none;
      border-radius: 8px;
      font-size: 0.9rem;
      cursor: pointer;
    }
    #confirm-ok  { background: #f38ba8; color: #1e1e2e; }
    #confirm-cancel { background: #45475a; color: #cdd6f4; }
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
    body.ios-chrome { padding-bottom: 20px; }
  </style>
</head>
<body>
  <div class="title-bar">
    <div class="title-spacer"></div>
    <h1>🎤 音声入力→AI</h1>
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
      </div>
    </div>

    <!-- 設定画面 -->
    <div id="settings-screen">
      <div class="title-bar" style="padding: 4px 0 12px;">
        <button id="settings-back-btn">◀ 戻る</button>
        <h1 style="font-size:1.1rem; text-align:center;">設定</h1>
        <div class="title-spacer"></div>
      </div>

      <div id="settings-body">
      <div class="settings-section">
        <div class="settings-label">入力</div>
        <div class="settings-row-title">行末の付加文字</div>
        <div class="settings-row-sub" style="margin: 4px 0 10px;">クリップボードへ送信時に末尾に追加</div>
        <div class="seg-ctrl" id="suffix-ctrl">
          <button data-val="none">なし</button>
          <button data-val="space">スペース</button>
          <button data-val="newline">改行</button>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-label">マイク</div>
        <div class="settings-row-title">マイクボタンのモード</div>
        <div class="settings-row-sub" style="margin: 4px 0 10px;">スナップ：左右にスナップ固定<br>フローティング：画面上を自由移動</div>
        <div class="seg-ctrl" id="mic-mode-ctrl">
          <button data-val="snap">スナップ</button>
          <button data-val="float">フローティング</button>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-label">履歴</div>
        <div class="settings-row-title">保存場所</div>
        <div class="settings-row-sub" style="margin: 4px 0 10px;">ローカル：この端末のみ保存。サーバー：全デバイスで共有。</div>
        <div class="seg-ctrl" id="history-storage-ctrl">
          <button class="seg-btn" data-val="local">ローカル</button>
          <button class="seg-btn" data-val="server">サーバー</button>
        </div>
        <div style="margin-top: 16px;">
        <div class="settings-row-title">削除時の確認ダイアログ</div>
        <div class="settings-row-sub" style="margin: 4px 0 10px;">🗑 ボタンをタップした際に確認ダイアログを表示します。</div>
        <div class="seg-ctrl" id="del-confirm-ctrl">
          <button class="seg-btn" data-val="on">ON</button>
          <button class="seg-btn" data-val="off">OFF</button>
        </div>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-label">クリップボード</div>
        <div class="settings-row-title">クリップボード自動取得</div>
        <div class="settings-row-sub" style="margin: 4px 0 10px;">他のアプリでコピーしてブラウザに戻ると自動でテキスト表示領域に貼り付けます。Android Chrome のみ対応。</div>
        <button class="btn" id="clipboard-monitor-btn" style="color: #1e1e2e;">有効にする</button>
      </div>

      <div class="settings-section">
        <div class="settings-label">アプリ情報</div>
        <div class="settings-row">
          <div class="settings-row-title">バージョン</div>
          <div class="version-text">voice_input v1.0.0</div>
        </div>
      </div>
      </div><!-- /#settings-body -->
    </div>

  </div>

  <div id="confirm-overlay">
    <div id="confirm-dialog">
      <p id="confirm-msg"></p>
      <div class="confirm-btns">
        <button id="confirm-cancel">キャンセル</button>
        <button id="confirm-ok">削除</button>
      </div>
    </div>
  </div>

  <script>
    if (/iPhone|iPad|iPod/i.test(navigator.userAgent)) {
      document.body.classList.add('ios');
      if (/CriOS/i.test(navigator.userAgent)) {
        document.body.classList.add('ios-chrome');
        document.body.style.paddingBottom = '20px';
      }
    } else if (/Android/i.test(navigator.userAgent)) document.body.classList.add('android');

    const micBtn = document.getElementById('mic-btn');
    const micPlaceholder = document.getElementById('mic-placeholder');
    const mainGroup = document.getElementById('main-group');
    const transcript = document.getElementById('transcript');
    const sendBtn = document.getElementById('send-btn');
    const clearBtn = document.getElementById('clear-btn');
    const statusEl = document.getElementById('status');
    const resultEl = document.getElementById('result');
    const historyList = document.getElementById('history-list');

    // --- 設定画面 ---
    const mainScreen     = document.getElementById('main-screen');
    const settingsScreen = document.getElementById('settings-screen');

    const settingsBtn = document.getElementById('settings-btn');
    settingsBtn.addEventListener('click', () => {
      mainScreen.classList.add('slide-out');
      settingsScreen.classList.add('slide-in');
      settingsBtn.style.visibility = 'hidden';
      micBtn.style.display = 'none';
    });
    document.getElementById('settings-back-btn').addEventListener('click', () => {
      mainScreen.classList.remove('slide-out');
      settingsScreen.classList.remove('slide-in');
      settingsBtn.style.visibility = 'visible';
      micBtn.style.display = '';
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
    const HISTORY_STORAGE_KEY = 'history_storage';

    function isServerMode() { return localStorage.getItem(HISTORY_STORAGE_KEY) === 'server'; }

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

    async function refreshAndRender() {
      if (isServerMode()) {
        try {
          const res = await fetch('/history');
          const data = await res.json();
          renderHistory(data.history || []);
        } catch { renderHistory([]); }
      } else {
        renderHistory(loadHistory());
      }
    }

    function switchToLocal() {
      localStorage.setItem(HISTORY_STORAGE_KEY, 'local');
      updateHistoryStorageCtrl();
    }

    async function addHistory(text) {
      if (isServerMode()) {
        const ts = new Date().toISOString();
        try {
          const res = await fetch('/history/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, ts })
          });
          if (!res.ok) throw new Error();
          await refreshAndRender();
        } catch {
          switchToLocal();
          const history = loadHistory().filter(t => t.text !== text);
          history.unshift({ seq: nextSeq(), text, ts });
          if (history.length > HISTORY_MAX) history.pop();
          saveHistory(history);
          renderHistory(loadHistory());
        }
      } else {
        const history = loadHistory().filter(t => t.text !== text);
        history.unshift({ seq: nextSeq(), text, ts: new Date().toISOString() });
        if (history.length > HISTORY_MAX) history.pop();
        saveHistory(history);
        renderHistory(loadHistory());
      }
      historyList.scrollTop = historyList.scrollHeight;
    }

    function formatTs(isoStr) {
      if (!isoStr) return '';
      const d = new Date(isoStr);
      const pad = n => String(n).padStart(2, '0');
      return `${d.getFullYear()}/${pad(d.getMonth()+1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }

    const openTsSeqs = new Set();

    function renderHistory(history) {
      historyList.innerHTML = '';
      history.slice().reverse().forEach(entry => {
        const text = typeof entry === 'string' ? entry : entry.text;
        const seq  = typeof entry === 'string' ? '' : String(entry.seq).padStart(3, '0');
        const ts   = typeof entry === 'string' ? '' : (entry.ts || '');
        const item = document.createElement('div');
        item.className = 'history-item';
        const span = document.createElement('span');
        span.className = 'history-text';
        if (seq) {
          const seqSpan = document.createElement('span');
          seqSpan.className = isServerMode() ? 'seq-server' : 'seq-local';
          seqSpan.textContent = `[${seq}] `;
          span.appendChild(seqSpan);
          span.appendChild(document.createTextNode(text));
        } else {
          span.textContent = text;
        }
        item.appendChild(span);
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
        delBtn.addEventListener('click', async () => {
          if (isDelConfirmEnabled()) {
            const ok = await showConfirm('この履歴を削除しますか？');
            if (!ok) return;
          }
          openTsSeqs.delete(seq);
          if (isServerMode()) {
            await fetch('/history/delete', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ text })
            });
            await refreshAndRender();
          } else {
            const history = loadHistory().filter(e => (typeof e === 'string' ? e : e.text) !== text);
            saveHistory(history);
            renderHistory(loadHistory());
          }
        });
        item.appendChild(resendBtn);
        item.appendChild(delBtn);
        if (ts) {
          const tsEl = document.createElement('span');
          tsEl.className = 'history-ts';
          tsEl.textContent = formatTs(ts);
          if (openTsSeqs.has(seq)) tsEl.style.display = 'block';
          span.addEventListener('click', () => {
            tsEl.style.display = tsEl.style.display === 'block' ? 'none' : 'block';
            if (tsEl.style.display === 'block') {
              openTsSeqs.add(seq);
              tsEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            } else {
              openTsSeqs.delete(seq);
            }
          });
          item.appendChild(tsEl);
        }
        historyList.appendChild(item);
      });
    }

    refreshAndRender();
    setTimeout(() => { historyList.scrollTop = historyList.scrollHeight; }, 50);

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
        if (!isResend) addHistory(text);
        resultEl.textContent = '⚠️ バックエンドがオフラインのため、ローカルに保存しました。';
        resultEl.classList.add('error');
        sendBtn.disabled = false;
        setTimeout(() => {
          const last = historyList.lastElementChild;
          if (last) last.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }, 50);
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

    // --- クリップボード監視 ---
    const confirmOverlay = document.getElementById('confirm-overlay');
    const confirmMsg = document.getElementById('confirm-msg');
    const confirmOkBtn = document.getElementById('confirm-ok');
    const confirmCancelBtn = document.getElementById('confirm-cancel');
    let confirmResolve = null;
    function showConfirm(msg) {
      return new Promise(resolve => {
        confirmMsg.textContent = msg;
        confirmOverlay.classList.add('show');
        confirmResolve = resolve;
      });
    }
    confirmOkBtn.addEventListener('click', () => {
      confirmOverlay.classList.remove('show');
      if (confirmResolve) confirmResolve(true);
    });
    confirmCancelBtn.addEventListener('click', () => {
      confirmOverlay.classList.remove('show');
      if (confirmResolve) confirmResolve(false);
    });

    const historyStorageCtrl = document.getElementById('history-storage-ctrl');
    const pcClipBtn = document.getElementById('pc-clip-btn');
    function updateHistoryStorageCtrl() {
      const val = localStorage.getItem(HISTORY_STORAGE_KEY) || 'local';
      historyStorageCtrl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.dataset.val === val));
      pcClipBtn.textContent = val === 'server' ? '📥 サーバークリップボードを取得' : '📥 PCクリップボードを取得';
    }
    historyStorageCtrl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        localStorage.setItem(HISTORY_STORAGE_KEY, btn.dataset.val);
        updateHistoryStorageCtrl();
        openTsSeqs.clear();
        refreshAndRender().then(() => { historyList.scrollTop = historyList.scrollHeight; });
      });
    });
    updateHistoryStorageCtrl();

    const DEL_CONFIRM_KEY = 'del_confirm';
    const delConfirmCtrl = document.getElementById('del-confirm-ctrl');
    function isDelConfirmEnabled() { return localStorage.getItem(DEL_CONFIRM_KEY) === 'on'; }
    function updateDelConfirmCtrl() {
      const val = localStorage.getItem(DEL_CONFIRM_KEY) || 'off';
      delConfirmCtrl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.dataset.val === val));
    }
    delConfirmCtrl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        localStorage.setItem(DEL_CONFIRM_KEY, btn.dataset.val);
        updateDelConfirmCtrl();
      });
    });
    updateDelConfirmCtrl();

    const CLIPBOARD_MONITOR_KEY = 'clipboard_monitor';
    let clipboardMonitorEnabled = localStorage.getItem(CLIPBOARD_MONITOR_KEY) === '1';
    let lastClipboardText = '';
    const clipboardMonitorBtn = document.getElementById('clipboard-monitor-btn');

    function updateClipboardMonitorBtn() {
      if (clipboardMonitorEnabled) {
        clipboardMonitorBtn.textContent = '無効にする';
        clipboardMonitorBtn.style.background = '#89b4fa';
        clipboardMonitorBtn.style.color = '#1e1e2e';
      } else {
        clipboardMonitorBtn.textContent = '有効にする';
        clipboardMonitorBtn.style.background = '#45475a';
        clipboardMonitorBtn.style.color = '#cdd6f4';
      }
    }
    updateClipboardMonitorBtn();

    // iOS では Clipboard API が制限されているためボタンを無効化
    if (/iPhone|iPad|iPod/i.test(navigator.userAgent)) {
      clipboardMonitorBtn.disabled = true;
      clipboardMonitorBtn.textContent = '非対応（iOS制限）';
      clipboardMonitorBtn.style.background = '#45475a';
      clipboardMonitorBtn.style.color = '#6c7086';
    }

    // iOS では Clipboard API が制限されているためボタンを無効化
    if (/iPhone|iPad|iPod/i.test(navigator.userAgent)) {
      clipboardMonitorBtn.disabled = true;
      clipboardMonitorBtn.textContent = '非対応（iOS制限）';
      clipboardMonitorBtn.style.background = '#45475a';
      clipboardMonitorBtn.style.color = '#6c7086';
    }

    clipboardMonitorBtn.addEventListener('click', async () => {
      if (/iPhone|iPad|iPod/i.test(navigator.userAgent)) return;
      if (clipboardMonitorEnabled) {
        clipboardMonitorEnabled = false;
        localStorage.removeItem(CLIPBOARD_MONITOR_KEY);
        updateClipboardMonitorBtn();
      } else {
        if (!navigator.clipboard || !navigator.clipboard.readText) {
          alert('このブラウザはクリップボード監視に対応していません。');
          return;
        }
        try {
          await navigator.clipboard.readText(); // 許可ダイアログを表示
          clipboardMonitorEnabled = true;
          localStorage.setItem(CLIPBOARD_MONITOR_KEY, '1');
          updateClipboardMonitorBtn();
        } catch (e) {
          alert('クリップボードの許可が得られませんでした。ブラウザの設定を確認してください。');
        }
      }
    });

    async function tryReadClipboard() {
      if (!clipboardMonitorEnabled) return;
      if (!navigator.clipboard || !navigator.clipboard.readText) return;
      try {
        const text = await navigator.clipboard.readText();
        if (text && text !== lastClipboardText) {
          lastClipboardText = text;
          transcript.textContent = text;
          finalText = text;
          sendBtn.disabled = false;
          statusEl.textContent = '📋 クリップボードからテキストを取得しました';
          statusEl.classList.remove('error');
        }
      } catch (e) {
        // 読み取り失敗（フォーカス不足・一時的な権限エラー）- 監視は維持する
      }
    }

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') return;
      // フォーカスが安定するまで少し待ってから読み取る
      setTimeout(tryReadClipboard, 500);
    });

    window.addEventListener('focus', () => {
      setTimeout(tryReadClipboard, 300);
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
    text = data['text']
    if not text or not text.strip():
        return jsonify({'status': 'error', 'message': '空のテキストです'}), 400
    try:
        copy_to_clipboard(text)
    except RuntimeError as e:
        print(f"[受信・クリップボード書込失敗] {text} / {e}")
        return jsonify({'status': 'ok', 'clipboard': False})
    print(f"[受信] {text}")
    return jsonify({'status': 'ok', 'clipboard': True})


@app.route('/cert', methods=['GET'])
def cert():
    from flask import send_file, abort
    cert_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cert.pem')
    if not os.path.exists(cert_file):
        abort(404)
    return send_file(cert_file, as_attachment=True, download_name='cert.pem', mimetype='application/x-pem-file')


@app.route('/clipboard', methods=['GET'])
def clipboard():
    try:
        text = paste_from_clipboard()
    except RuntimeError as e:
        print(f"[クリップボード取得失敗] {e}")
        return jsonify({'status': 'error', 'message': 'クリップボードへのアクセスができません'}), 200
    if not text:
        return jsonify({'status': 'error', 'message': 'クリップボードが空です'}), 200
    print(f"[クリップボード送信] {text[:50]}")
    return jsonify({'status': 'ok', 'text': text})


@app.route('/history', methods=['GET'])
def get_history():
    if _use_mysql():
        history = _db_get_history()
    else:
        history = _load_server_data()['history']
    return jsonify({'status': 'ok', 'history': history})


@app.route('/history/add', methods=['POST'])
def add_history():
    req = request.get_json(silent=True) or {}
    text = req.get('text', '').strip()
    if not text:
        return jsonify({'status': 'error', 'message': 'テキストがありません'}), 400
    ts = req.get('ts', '')
    if _use_mysql():
        seq = _db_add_history(text, ts)
    else:
        data = _load_server_data()
        data['history'] = [e for e in data['history'] if e.get('text') != text]
        seq = (data['seq'] + 1) % 1000
        data['seq'] = seq
        data['history'].insert(0, {'seq': seq, 'text': text, 'ts': ts})
        if len(data['history']) > HISTORY_MAX:
            data['history'] = data['history'][:HISTORY_MAX]
        _save_server_data(data)
    return jsonify({'status': 'ok', 'seq': seq})


@app.route('/history/delete', methods=['POST'])
def delete_history():
    req = request.get_json(silent=True) or {}
    text = req.get('text', '')
    if _use_mysql():
        _db_delete_history(text)
    else:
        data = _load_server_data()
        data['history'] = [e for e in data['history'] if e.get('text') != text]
        _save_server_data(data)
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
