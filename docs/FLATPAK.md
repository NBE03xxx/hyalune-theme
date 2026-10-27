# Hyalune：Flatpakアプリ

対応対象はGTK3、GTK4／libadwaitaを使用するFlatpakアプリです。Flathubは配布元であり、すべてのFlathubアプリが同じUIを使うわけではありません。確認例はgedit、GNOME Text Editor、Planifyです。Qt系、独自描画の本文、Snap／AppImageは対象外です。

## 初回導入時

通常テーマの`./install.sh plan`と`apply`は、インストール済みFlatpakを実行せずに検出します。GTK使用を確認できた停止中のアプリへ固定DarkのCSSを適用し、起動中・競合・未判定・未対応は理由を表示します。

基本テーマと追加アプリを同じ処理記録で保全します。一括導入が中断した場合は、先に`./install.sh recover`を実行します。アプリ・remoteの追加導入や、アプリの自動起動・終了は行いません。

## Dark／Lightと共通素材へ追従させる

[Hyalune 設定](THEME-MANAGER.md#flatpakの追従と個別値)の「Flatpakアプリ」で再検出し、対象を選択して設定方法を指定します。

| 設定方法 | 動作 |
| --- | --- |
| 共通設定に追従 | 選択中の明暗と共通の素材値を反映 |
| 個別設定 | アプリ固有の素材値を保持し、前景・部品の明暗を反映 |
| 現在の適用を保持 | 既存CSSを変更しない |

新しいアプリと、単独CLIで導入しただけのアプリは、政策を登録するまで現在の適用を保持します。Ubuntuの明暗変更で未登録アプリを取り込みません。

管理アプリでの通常テーマと対象Flatpakの反映は、一つのjournalへ統合します。明示選択したアプリが起動中・競合等で変更できない場合は全体を停止します。登録済みアプリの暗黙の再反映は理由付きで保留する場合があり、自動連動では起動中の対象が終了した後に再試行します。外部編集を強制的に上書きしません。

GTK4は明暗両方のCSSを読み込み、対応アプリは起動したまま前景・部品の明暗へ追従できます。素材の変更や初回反映ではアプリの開き直しが必要です。起動中アプリのCSSを書き換えることは避けます。

LightのGTK3 Flatpakは、High Contrastを妨げないよう標準外観を使い、素材の個別値は保存します。GTK4のアプリ内ダイアログ・floating／bottom-sheetは、背後の本文が重ならないよう不透明にしています。いずれも意図した適用範囲です。

## 単独CLIで検出・適用する

固定DarkのCSSをアプリ別に管理する場合は、通常ユーザーで実行します。

```sh
./install.sh flatpak scan
./install.sh flatpak list
./install.sh flatpak plan --app APP_ID
./install.sh flatpak apply --app APP_ID
./install.sh flatpak status --app APP_ID
```

`APP_ID`は一覧のIDへ置き換え、対象アプリを完全終了してから適用し、開き直してください。Flatpak CSSだけの反映で再ログインは不要です。機種固有の指定は不要で、[通常テーマ](INSTALL.md)と同じユーザー環境を照合します。

単独CLIの既定の生成元は固定Darkです。管理アプリの明暗・共通追従・個別値を使うアプリの更新は、管理アプリから行ってください。単独CLIはそのプロファイル政策を編集する入口ではありません。

## 更新・解除・復旧

単独CLIで管理するアプリには、次の入口を使えます。

```sh
./install.sh flatpak plan --operation update --app APP_ID
./install.sh flatpak update --app APP_ID
./install.sh flatpak plan --operation remove --app APP_ID
./install.sh flatpak remove --app APP_ID
./install.sh flatpak recover --app APP_ID
```

自動追従へ登録したアプリを個別解除したい場合は、先に管理アプリで「現在の適用を保持」を選び適用し、その後にアプリ別の解除を行います。追従政策が残ったままCSSだけを解除すると、次回の連動・適用で再び反映対象になります。

基本テーマ全体の解除は`./install.sh remove`で管理Flatpakも一括復元するため、アプリ別解除の繰り返しは不要です。管理アプリ本体やGDMは別管理です。

アプリ単独操作の中断はアプリ別`recover`、通常テーマとの一括操作の中断は先に`./install.sh recover`です。アプリ別解除でもアプリのデータは削除しません。基本テーマの`--settings`はアプリ別CSSには適用しません。

## 変更範囲

- `~/.var/app/<APP_ID>/config/gtk-3.0/gtk.css`
- `~/.var/app/<APP_ID>/config/gtk-4.0/gtk.css`
- `~/.local/share/flatpak/overrides/<APP_ID>`のGTK設定共有2件

既存CSSの管理ブロック外を保持し、対象の`xdg-config/gtk-3.0`と`xdg-config/gtk-4.0`共有だけを否定設定にします。ホーム全体等の新しいアクセス権限は付けず、global overrideや`GTK_THEME`は変更しません。

元の内容・モード・不在状態は`~/.local/state/glass50/installer-flatpak-v1/<APP_ID>/`へ保存します。管理ブロック・権限の後編集は競合として止めます。`flatpak override --reset`で他の設定を一括初期化しません。
