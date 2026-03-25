# 音声入力ツール

スマホ(Android Chrome)のマイクから音声入力し、PCのVS Code ClaudeCodeチャットへ転送するツール。

## セットアップ

```bash
cd voice_input
pip install -r requirements.txt
```

## 起動

VS Code起動時に **SessionStartフック** で自動起動します。手動で起動する場合:

```bash
nohup python d:/workspace_git/voice_input/server.py > d:/workspace_git/voice_input/server.log 2>&1 &
```

起動するとPCのローカルIPアドレスが `server.log` に記録されます。

```
==================================================
  音声入力サーバー起動
  スマホのChromeでアクセス: http://192.168.x.x:5000
==================================================
```

## 初回のみ: AndroidのChromeマイク許可設定

HTTP接続でのマイク使用を許可するための設定（1回だけ必要）:

1. AndroidのChromeで `chrome://flags/#unsafely-treat-insecure-origin-as-secure` を開く
2. テキストボックスに `http://192.168.x.x:5000`（サーバー起動時に表示されるURL）を入力
3. **Relaunch** をタップしてChromeを再起動

### セキュリティについて

**自宅の閉じたWi-Fi内での使用であれば実用上問題ありません。**

**リスクの内容：**

この設定は「指定したURLをHTTPSと同等に扱う」ものです。通常HTTPはセキュアでないため、マイク等のセンシティブなAPIが使えません。

- **通信の盗聴リスク**：HTTP通信は暗号化されていないため、同じWi-Fi上の第三者に音声テキストが傍受される可能性があります
- **設定の影響範囲**：指定したURL（`http://192.168.x.x:5000`）のみに限定されます。他のサイトには影響しません
- **フラグ自体の性質**：`chrome://flags` は実験的な機能で、将来的にChromeのアップデートで動作が変わる可能性があります

**自宅Wi-Fiなら安全な理由：**

- ルーターの外に通信が出ない
- 同一ネットワークに信頼できない端末がいない
- 用途が音声入力テキストの転送のみ（機密情報でなければリスク低）

**より安全にしたい場合：**

自己署名証明書でHTTPS化することで、このフラグ設定が不要になります。

## 使い方

1. VS Codeを起動（サーバーが自動起動）
2. AndroidのChromeで `http://192.168.x.x:5000` にアクセス
3. 🎤 ボタンをタップして話す
4. 話し終わると自動でクリップボードへ送信される
5. VS CodeのClaudeCodeチャット欄をクリックして `Ctrl+V` で貼り付け

## 停止

手動で停止する場合（PIDファイルを使用してserver.pyのみ停止）:

```bash
pid=$(cat d:/workspace_git/voice_input/server.pid); taskkill //PID $pid //F
```

## 注意事項

- PCとスマホが同じWi-Fiに接続されている必要があります
- 音声認識はGoogleの音声認識サービスを使用するため、インターネット接続が必要です
- Web Speech APIはAndroid ChromeおよびPC版Chromeで動作します
