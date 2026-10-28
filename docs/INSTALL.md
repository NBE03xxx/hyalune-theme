# Hyalune：導入・更新・解除・復旧

## 導入条件

Ubuntu 26.04／GNOME Shell 50.x／Waylandの、ログイン中の通常ユーザーを対象とします。動作確認はShell 50.1です。他のOS・デスクトップは対象に含めません。

通常テーマの導入では、ホスト名・PCの機種・固定UID・ディスク名を条件に使いません。実行中Shell、Waylandセッション、ユーザーとHOMEを照合します。機種固有の引数は不要です。GDMは[OS・Shell・GDM資源を照合する別の入口](GDM.md)を使います。機種名による制限はありません。

| 用途 | 必要なもの |
| --- | --- |
| 通常テーマ | `git`、Python3、PyGObject／Gio（`python3-gi`）、`glib-compile-schemas`、導入・有効化済みのUser Themes |
| 管理アプリ・素材の生成・自動明暗連動 | 上記に加え、GTK4、libadwaita、`sassc`と「Hyalune 設定」 |
| Flatpak対応 | `flatpak`と対応するGTK系アプリ |

User ThemesのUUIDは`user-theme@gnome-shell-extensions.gcampax.github.com`です。依存パッケージ・User Themes・Flatpak remote・アプリを自動導入しません。通常テーマと管理アプリは`sudo`を使わず実行します。

HOMEとXDG設定はユーザー登録に対応する標準配置を使用します。HOME・設定ディレクトリのリンクや独自XDG配置は対象外です。GTK CSS入口そのもののリンクは保全・復元できます。

## 新規導入

[README](../README.md#install--uninstall)の手順で取得したディレクトリで実行します。`./install.sh`は使い方、`./install.sh layers`は構成を表示します。生成済みCSSを使う固定Dark導入には`sassc`やdebパッケージ化は不要です。

```sh
./install.sh plan --blur off
./install.sh apply --blur off
./install.sh status
```

`plan`は変更対象を表示し、外観へ適用しません。初回はShell・GTK・Hyalune拡張と、検出した既存の対応GTK系Flatpakをまとめて導入します。自動Flatpak適用を外す場合は、`plan`と`apply`の両方に`--flatpak none`を付けます。

既存のGTK4 CSS入口は内容・モード・リンクを保全して専用importへ切り替えます。リンクの参照先は書き換えません。管理対象の外部編集や未管理の異なるファイルがあれば、変更前に停止します。新規導入時に競合するBlur my Shellが有効なら、名前を示して停止します。

### 管理アプリと明暗連動を使う

```sh
./install.sh manager install
./install.sh manager status
```

テーマ・拡張・管理アプリを同じソースからそろえます。初回は「Hyalune 設定」を開き、配置済みの素材とぼかし選択を確認して、一度「変更内容を確認して適用」を実行します。この適用で自動明暗連動用のHyalune拡張も有効にします。最初の`--blur off`導入だけでは拡張が無効なので、管理アプリの導入だけで連動開始とはなりません。

拡張の初回導入・コード更新後にログアウト→ログインします。以後はUbuntu「設定 → 外観」からDark／Lightが切り替わり、管理アプリのウィンドウは開いておく必要がありません。初期導入はDarkで、Lightを初めて選ぶと保存済みの値、またはLightの既定値を使います。GDMは連動しません。[明暗連動の条件](LIGHT.md)

「Hyalune 設定」の外観・ぼかし画面から、素材と任意の効果を選び、変更内容を確認して適用します。ぼかしはQuick Settingsとウィンドウで独立して選べます。[管理アプリ](THEME-MANAGER.md)

コード更新後は、作業を保存して本人が再ログインしてください。スクリプトは自動ログアウトせず、WaylandでAlt+F2 → rは使用しません。既に開いているGTKアプリは、この版のCSSを初めて読み込む際に開き直します。通常の明暗変更ごとに再ログインする必要はありません。

## 更新

まずソースを更新します。

```sh
git pull --ff-only
```

明暗別素材や管理アプリのプロファイルを使っている場合は、次の順で更新します。

1. 起動中の「Hyalune 設定」で未保存の編集を保存し、閉じます。
2. `./install.sh manager install`で管理アプリを更新します。
3. アプリを開き、保存済み素材と変更内容を確認して適用します。
4. 拡張コードに更新があれば再ログインし、必要なGTKアプリを開き直します。

固定Darkだけを使い、明暗別プロファイルをまだ管理していない場合は、CLIでも更新できます。

```sh
./install.sh plan --operation update
./install.sh update
./install.sh status
```

`--blur`省略時は効果設定を保持します。固定DarkのCLI更新は形式3の明暗別プロファイルがあると停止し、管理アプリの適用を案内します。値を保持するための保護であり、解除・初期化で回避しないでください。既に管理中なら初回`apply`を繰り返しません。

通常CLIの更新は管理Flatpakを再生成しません。プロファイルの追従・個別設定を使うアプリは管理アプリから反映します。単独CLIで管理するアプリは[アプリ別の手順](FLATPAK.md)を使います。

### 既存導入の引き継ぎ

既知の管理記録を自動認識し、元のGTKリンク・設定値の有無・拡張構成を保持します。更新前の解除や初期化は不要です。試用時に停止した拡張の情報も保持し、後で再有効化したDock等を更新時に停止し直しません。

Shellとレガシーアプリケーション（GTK3）のテーマ名は、明暗共通の`Hyalune`です。更新で配置先が変わる場合は、新旧ファイルと設定を同じ処理記録で移行します。古いパスは元状態へ戻し、原本と新パスの復元情報を保持します。保存済み旧コードで戻す場合は、その所有形式に対応する手順を使います。

## 解除と設定の扱い

`./install.sh remove`は管理中Flatpakと通常テーマを一つのトランザクションで解除します。アプリID・機種固有の指定は不要です。削除済みアプリに残る管理記録も確認します。

```sh
# ぼかし設定2項目を残す
./install.sh plan --operation remove --settings keep
./install.sh remove --settings keep

# ぼかし設定も導入前へ戻す（既定）
./install.sh plan --operation remove --settings discard
./install.sh remove --settings discard
```

| 選択 | 動作 |
| --- | --- |
| `keep` | `effect-enabled`と`window-material-enabled`のユーザー値を保持。外観の適用は解除 |
| `discard` | 上記2項目を導入前の値へ復元。元が未設定ならユーザー値を解除 |
| 共通 | 導入前のテーマ・色設定・GTKファイルやリンク・管理する拡張構成へ戻す。保全・処理記録は残す |

後から利用者が変更した一般設定は無条件に戻しません。診断・更新上限等、管理対象外のキーは変更しません。起動中アプリ・中断・CSSや権限の競合が一件でもあれば、全変更前に停止します。アプリの自動終了や、管理外ファイルの一括削除は行いません。

解除はAdwaitaへの一律初期化ではなく、導入前の状態への復元です。管理アプリ本体と保存プロファイル、GDMは別管理です。通常テーマの解除中は自動明暗連動も停止します。

## 中断からの復旧

通常テーマ、初回Flatpak一括導入、一括解除が中断した場合は、先に次を実行します。

```sh
./install.sh recover
```

未確定の操作は逆順で戻し、確定済みなら完了処理を行います。競合がある場合は保全を残して停止します。個別解除や所有記録の手動コピーで中断を回避しないでください。

管理アプリの「履歴と復元」からも、通常テーマと選択Flatpakの中断を復旧できます。アプリ本体の導入中断は`./install.sh manager recover`、単独Flatpak操作の中断は`./install.sh flatpak recover --app APP_ID`です。[復元操作の違い](THEME-MANAGER.md#履歴と復元)

通常ソース入口で行った操作の管理コードは`~/.local/state/glass50/source-packages/<ID>/`へ保存します。checkoutが使えない場合は、その操作に対応する保存済みパッケージを指定します。

```sh
python3 /path/to/saved-package/manage-desktop.py recover --package /path/to/saved-package
```

解除・復旧はOS・Shellの導入条件が変わっていても保存対象の範囲で扱いますが、ユーザーのHOME・D-Bus、Python／Gio、復元する設定のschemaは必要です。保存済みコードを使うときも、現在の所有形式を解釈できる版を選びます。

「直前の適用へ戻す」はプロファイル更新用です。拡張コードを含む旧版復帰は、互換性を確認した保存済みコード・パッケージ・素材値で行います。古い基本テーマ専用ツールや、所有記録だけの巻戻しで代用しないでください。

## 配置と確認範囲

| 対象 | 配置・管理先 |
| --- | --- |
| GNOME Shell | `~/.local/share/themes/Hyalune/gnome-shell/`、選択名`Hyalune` |
| GTK3 | `~/.local/share/themes/Hyalune/gtk-3.0/` |
| GTK4 | `~/.local/share/themes/Glass50-Material-Preview/gtk-4.0/`、内部import先を互換維持 |
| Hyalune拡張 | `~/.local/share/gnome-shell/extensions/glass50-blur@myglass.local/` |
| 通常テーマの所有・保全 | `~/.local/state/glass50/installer-material-v1/` |
| 新規導入のGTK4 include | `~/.config/gtk-4.0/glass50-managed.css` |

旧形式のGTK includeは元の復元情報を保持するため継続使用します。Flatpakの変更先は[別記](FLATPAK.md#変更範囲)です。通常入口はGDM・パッケージ・サービス・ドライバー・ログイン方式を変更しません。

任意ぼかしは単一画面・100％を中心に確認しています。High Contrast／Reduced Motionや条件外の倍率では効果を停止し、文字・アイコンを含むウィンドウ全体のopacityを下げません。GTK3とGTK4でアクセシビリティの退避方式が異なります。[Lightとアクセシビリティ](LIGHT.md#外観とアクセシビリティ)
