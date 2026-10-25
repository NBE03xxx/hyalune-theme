# Hyalune：Flatpakアプリ

Flathubは配布元です。同じFlathubのアプリでもUIの仕組みは異なります。現行はGTK3、GTK4 / libadwaita向けのアプリ単位CSSを用意しています。Qt系は未対応、Electronなど独自描画の内部は未検証です。Snap / AppImageは対象外です。

確認例はgedit（GTK3）、GNOME Text Editor、Planify（GTK4 / libadwaita）です。アプリ自身の本文・独自配色・レイアウトをすべて透明化するものではありません。GTK4のウィンドウ内ダイアログは読みやすい不透明面を使います。

## 初回導入時

基本テーマの`./install.sh plan`、`./install.sh apply`は既存Flatpakを検出します。実行ファイルの依存などからGTK使用を確認できた停止中アプリに適用し、起動中・未判定・未対応・競合は理由を表示します。アプリを自動起動・終了したり、追加インストールしたりしません。

基本テーマと今回追加するアプリの変更は一つの処理記録で保全します。失敗・中断は先に基本テーマの`./install.sh recover`を使って復旧します。

## 後から追加したアプリ

```sh
./install.sh flatpak scan
./install.sh flatpak list
./install.sh flatpak plan --app APP_ID
./install.sh flatpak apply --app APP_ID
./install.sh flatpak status --app APP_ID
```

`APP_ID`は一覧のアプリIDで置き換えます。変更するアプリは先に完全終了し、適用後に開き直してください。Flatpak CSSだけの変更で再ログインは不要です。機種固有の指定は不要です。導入条件は[基本テーマ](INSTALL.md)と共通です。

## 更新・解除・復旧

```sh
./install.sh flatpak plan --operation update --app APP_ID
./install.sh flatpak update --app APP_ID
./install.sh flatpak plan --operation remove --app APP_ID
./install.sh flatpak remove --app APP_ID
./install.sh flatpak recover --app APP_ID
```

アプリ単体の中断はアプリ別`recover`を使います。基本テーマの初回一括導入または一括解除が中断した場合は、先に基本テーマの`recover`です。

基本テーマ全体を解除する場合は`./install.sh remove`を使います。管理記録のscanからFlatpakと基本テーマの一括復元までを行うため、上記のアプリ別解除を繰り返す必要はありません。起動中・競合があれば書き込み前に停止します。アプリ別解除は元のCSS・権限上書きへ戻し、アプリのデータは削除しません。基本テーマの`--settings`はアプリ別CSSには適用しません。

## 変更範囲

- `~/.var/app/<APP_ID>/config/gtk-3.0/gtk.css`
- `~/.var/app/<APP_ID>/config/gtk-4.0/gtk.css`
- `~/.local/share/flatpak/overrides/<APP_ID>`のGTK設定共有2件

既存CSSの管理ブロック外を保持し、対象アプリの`xdg-config/gtk-3.0`、`xdg-config/gtk-4.0`共有だけを否定設定にします。これによりホストの共有CSSよりアプリ専用CSSを使います。ホーム全体などへの新しいアクセス権限は付けず、global overrideや`GTK_THEME`を変更しません。

元の内容・権限・不在状態は`~/.local/state/glass50/installer-flatpak-v1/<APP_ID>/`へ保存します。管理ブロック・権限の後編集は競合として止め、保全を残します。`flatpak override --reset`で他の設定を一括初期化しません。

GTK3のLight / High Contrastへの自動追従は未対応です。切り替える場合は先にアプリ別解除してください。
