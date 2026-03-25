# 音声入力ツール

スマホ(Android Chrome)のマイクから音声入力し、PCのVS Code ClaudeCodeチャットへ転送するツール。

## セットアップ

```bash
cd voice_input
pip install -r requirements.txt
```

## 起動

```bash
python server.py
```

起動するとPCのローカルIPアドレスが表示されます。

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

## 使い方

1. PCで `python server.py` を起動
2. AndroidのChromeで表示されたURLにアクセス
3. 🎤 ボタンをタップして話す
4. テキストが表示されたら「📋 送信」ボタンをタップ
5. VS CodeのClaudeCodeチャット欄をクリックして `Ctrl+V` で貼り付け

## 注意事項

- PCとスマホが同じWi-Fiに接続されている必要があります
- 音声認識はGoogleの音声認識サービスを使用するため、インターネット接続が必要です
- Web Speech APIはAndroid ChromeおよびPC版Chromeで動作します
