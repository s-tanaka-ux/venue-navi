# 会場ナビ 自動更新サイト

OpenStreetMapの会場データを自動取得し、AIで紹介文を下書きして、毎朝5時(日本時間)に自動で公開サイトを更新します。
サーバー管理は不要で、GitHubの無料枠で動きます。

## 最初の設定(1回だけ・約30分)

1. GitHubで新しいリポジトリを作り、このフォルダの中身をすべてアップロード
2. `config.json` を編集
   - `site_name` / `tagline`: サイト名
   - `base_url`: 公開URL(例 `https://ユーザー名.github.io/リポジトリ名`)
   - `contact_email`: 連絡先メール(お問い合わせページに表示)
   - `user_agent`: 末尾の括弧内を自分の連絡先(メール等)に変更
3. リポジトリの Settings → Pages → Source を **GitHub Actions** にする
4. Settings → Secrets and variables → Actions に `ANTHROPIC_API_KEY` を登録(紹介文の下書き用。未設定でも動きますが紹介文は作られません)
5. Actions タブ → `update-site` → **Run workflow** で初回実行(初回はデータ取得に30〜60分かかります)

以降は毎朝自動で動きます。

## 広告(AdSense)を入れる

AdSenseの審査に通ったら、`config.json` の次の3つを埋めるだけです。コードの貼り付けは不要です。

- `adsense_client`: `ca-pub-XXXXXXXXXXXXXXXX`
- `ad_slots`: AdSenseで作った広告ユニットのID(`top` / `mid` / `bottom`)
- 広告が入ったら `show_ad_placeholders` を `false` に(仮の枠を消す)

`ads.txt` は自動で作られます。

## 毎月の確認(10〜15分)

Actionsの実行ログ(Build)に「未確認の紹介文: N 件」と出ます。

1. `data/descriptions.json` を開く
2. 数件〜数十件を読んで、事実と違う・不自然な文は直す
3. 確認した会場は `"reviewed": true` にする(確認済みの文は上書きされません)
4. 不要な紹介文は削除すると、次回に再生成されます

## 仕組みと注意

- 会場データは週1回(`refetch_days`)だけ再取得します。毎日動くのは再生成と、新しい会場の紹介文の下書き(1回あたり最大 `max_new_descriptions` 件)です。
- 紹介文がない会場のページは `noindex` になり、検索に出ません(薄いページ対策)。
- 紹介文は、会場名・種類・所在地・収容人数だけを材料にし、他の情報は書かないよう指示しています。それでも誤りが出る可能性があるため、月次確認をしてください。
- OpenStreetMapのデータを使うため、フッターの出典表示(ODbL)は消さないでください。
- 固定ページ(運営について・プライバシーポリシー)は雛形です。公開前に内容を確認・修正してください。
- 紹介文の下書きにかかるAPI費用は少額ですが、使用量はAnthropicのコンソールで確認できます。
