#!/bin/bash
# GitHubへの手動pushスクリプト
# 実行前に必ず動作確認を行ってください

GITHUB_REMOTE="github"
BRANCH="master"

# GitHubリモートが登録されているか確認
if ! git remote | grep -q "^${GITHUB_REMOTE}$"; then
  echo "[ERROR] リモート '${GITHUB_REMOTE}' が登録されていません。"
  echo "以下のコマンドでGitHubリポジトリを登録してください："
  echo "  git remote add ${GITHUB_REMOTE} https://github.com/<ユーザー名>/voice_input.git"
  exit 1
fi

echo "=== GitHubへのpush ==="
echo "リモート : $(git remote get-url ${GITHUB_REMOTE})"
echo "ブランチ : ${BRANCH}"
echo ""
echo "以下の変更をpushします："
git log ${GITHUB_REMOTE}/${BRANCH}..HEAD --oneline 2>/dev/null || git log --oneline -5
echo ""
read -p "pushを実行しますか？ [y/N]: " confirm
if [ "${confirm}" != "y" ] && [ "${confirm}" != "Y" ]; then
  echo "キャンセルしました。"
  exit 0
fi

git push ${GITHUB_REMOTE} ${BRANCH}
echo ""
echo "=== push完了 ==="
