/**
 * localStorage ダミーデータ投入スクリプト（998件）
 * 用途: TODO #52「履歴999件超過テスト」の事前準備
 *
 * 使い方:
 *   ブラウザの DevTools > Console に以下を貼り付けて実行する
 *   実行後、voice_input アプリをリロードして履歴が998件表示されることを確認する
 *   その後、音声入力または送信操作を1件行い、ラップアラウンド・最古エントリ削除が正常に動作するか確認する
 *
 * データ形式:
 *   アプリは unshift() で先頭に追加するため、配列は [最新, ..., 最古] の順で保存する。
 *   entries[0]   = seq:997, text:dummy998  （最新）
 *   entries[997] = seq:0,   text:dummy001  （最古）
 */

(function() {
  var KEY = 'voice_input_history';
  var SEQ_KEY = 'voice_input_seq';
  var N = 998;
  var entries = [];
  // 新しい順（先頭が最新）で格納する
  for (var i = N; i >= 1; i--) {
    entries.push({
      seq: (i - 1) % 1000,
      text: 'dummy' + String(i).padStart(3, '0'),
      ts: '2026-01-01T00:00:00.000Z'
    });
  }
  localStorage.setItem(KEY, JSON.stringify(entries));
  localStorage.setItem(SEQ_KEY, String(N - 1)); // 997
  console.log('ローカルストレージに ' + N + ' 件作成しました（最新順）');
  console.log('次のseq: ' + ((N) % 1000)); // 998
})();
