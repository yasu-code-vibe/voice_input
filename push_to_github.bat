@echo off
chcp 65001 > nul
rem GitHubへの手動pushスクリプト
rem 実行前に必ず動作確認を行ってください

set GITHUB_REMOTE=github
set BRANCH=master

rem GitHubリモートが登録されているか確認
git remote | findstr /x "%GITHUB_REMOTE%" > nul 2>&1
if errorlevel 1 (
  echo [ERROR] リモート '%GITHUB_REMOTE%' が登録されていません。
  echo 以下のコマンドでGitHubリポジトリを登録してください：
  echo   git remote add %GITHUB_REMOTE% https://github.com/^<ユーザー名^>/voice_input.git
  pause
  exit /b 1
)

echo === GitHubへのpush ===
for /f "usebackq" %%i in (`git remote get-url %GITHUB_REMOTE%`) do echo リモート : %%i
echo ブランチ : %BRANCH%
echo.
echo 直近のコミット：
git log --oneline -5
echo.
set /p confirm=pushを実行しますか？ [y/N]:
if /i not "%confirm%"=="y" (
  echo キャンセルしました。
  pause
  exit /b 0
)

git push %GITHUB_REMOTE% %BRANCH%
echo.
echo === push完了 ===
pause
