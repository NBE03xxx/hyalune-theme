# Hyalune：導入・更新・解除・復旧

## 導入条件

Ubuntu 26.04 / GNOME Shell 50.x / Waylandを対象としたユーザー単位のプレビューです。動作確認はShell 50.1。他のOSでの動作は未確認です。

ホスト名、PCの機種、固定UID、ディスク名は導入条件に使いません。通常のデスクトップユーザーとそのHOME、実行中のGNOME Shell、アクティブなWaylandセッションを確認します。機種固有の`--target`指定は不要です。

必要なものは`git`、Python3、PyGObject / Gio（`python3-gi`）、`glib-compile-schemas`と、有効化済みのUser Themes（`user-theme@gnome-shell-extensions.gcampax.github.com`）です。Flatpak対応を使う場合は`flatpak`も必要です。パッケージ・拡張・アプリ・Flatpak remoteは自動導入しません。`sudo`を使わず、GNOMEへログインしたユーザーで実行してください。

HOMEはユーザー登録にある実フォルダー、XDG設定はHOME内の標準配置を使用します。HOMEや設定ディレクトリのシンボリックリンク、独自のXDG配置は現在の導入対象に含めません。GTK CSS入口自体のリンクは保全・復元できます。

第1層Shell、第2層GTK3 / GTK4 / libadwaita、第3層独自拡張を一括配置します。第4層GDMは別の明示入口を持つ[KVM／T16向けの任意機能](GDM.md)です。通常の一括操作には含みません。

## 表示と効果の確認範囲

任意ぼかしは単一画面・100％表示の確認範囲です。機種の照合をなくしても、描画の確認範囲を広げたことにはなりません。ウィンドウ全体のopacityは変えません。High Contrast / Reduced Motionや効果の条件外では任意ぼかしを停止します。テーマ全体の高コントラスト対応を意味しません。

GTK4 CSSはDark・通常コントラスト時に限定します。GTK3のLight / High Contrastへの自動追従は未対応なので、切り替える場合は先にテーマを解除してください。

新規導入時は既知の競合するぼかし拡張（Blur my Shell）があれば、変更を始める前に名前を表示して停止します。先に無効化してから再実行してください。他の拡張を一括で停止したり、既存資産を削除したりしません。別の外観拡張との併用はそれぞれ確認が必要です。

## ソースから導入

[README](../README.md#install)のClone手順で取得したディレクトリで実行します。`./install.sh`は使い方、`./install.sh layers`は構成を表示します。Git管理済みのCSSを使うため、通常導入にSCSSコンパイラーやdebパッケージ化は不要です。

```sh
./install.sh plan --blur off
./install.sh apply --blur off
./install.sh status
```

`plan`は変更対象を表示し、設定やファイルを適用しません。GTK4の`gtk.css`と`gtk-dark.css`は元の内容・モード・リンクを記録してから、Hyalune専用のimportへ置き換えます。リンクの参照先は変更せず、参照先の内容も保全記録に保存します。管理中のファイルや設定に後編集があれば、競合として停止します。

初回`apply`は既存の対応GTK系Flatpakも検出して一括適用します。起動中・未判定・競合などの理由を確認してください。自動適用を外す場合は`plan`と`apply`の両方に`--flatpak none`を付けます。既に管理中なら`apply`を繰り返さず`update`を使います。

ぼかしなしで表示と入力を確認後、任意で有効にします。

```sh
./install.sh plan --operation update --blur on
./install.sh update --blur on
```

独自拡張の新規導入・コード更新時は、未保存作業を保存してログアウト→ログインしてください。`status`の配置版だけで読み込み済みと判断しないでください。スクリプトは自動ログアウトせず、WaylandではAlt+F2 → rを使いません。GTKアプリは完全終了して開き直します。

## 更新と旧試用版からの移行

```sh
git pull --ff-only
./install.sh plan --operation update
./install.sh update
./install.sh status
```

`--blur`省略時は現在の効果設定を維持します。既に管理中のFlatpak CSSは[アプリ別の更新手順](FLATPAK.md)を使います。

以前のVM用・T16試用の管理記録は自動認識します。従来の機種指定を付けず、同じ共通入口で更新・解除・復旧できます。保存されている導入前のGTKリンク、設定値の有無、拡張の復元情報は引き継ぎます。更新のために解除・初期化する必要はありません。

旧試用で一時停止した拡張の情報も維持します。利用者が後で再有効化したDockやロゴ等を、更新で停止し直しません。旧版の保存済みコードを直接使う場合は、その版に付属する手順に従ってください。

## 解除と設定の扱い

`./install.sh remove`は管理記録をscanし、管理中Flatpakと基本テーマを一つのトランザクションで解除します。削除済みアプリに残る管理記録も確認します。アプリIDや機種の指定は不要です。

```sh
# Hyaluneの効果設定2項目を残して解除
./install.sh plan --operation remove --settings keep
./install.sh remove --settings keep

# 効果設定も導入前へ戻して解除（既定）
./install.sh plan --operation remove --settings discard
./install.sh remove --settings discard
```

起動中の対象アプリ、管理記録の中断、CSS・権限の競合が一件でもあれば、すべての変更を始める前に停止します。表示されたアプリを閉じるか競合を解決してから再実行してください。アプリは自動終了せず、管理外のアプリは変更しません。

| 選択 | 動作 |
| --- | --- |
| `keep` | Hyaluneの`effect-enabled`、`window-material-enabled`のユーザー値を保持。適用は解除 |
| `discard`（既定） | 上記2項目を導入前の値へ復元。導入前にユーザー値がなければその値を解除 |
| 両方共通 | 元のテーマ・色設定・GTKファイルやリンク・拡張構成を復元し、他アプリの設定と既存資産を保持 |

`keep`で残すのはHyaluneの効果設定だけです。診断・更新上限など、管理対象に含めないキーは両方とも変更しません。後から利用者が変更した一般設定は無条件に戻さず、管理ファイルの改変は競合として停止します。

解除で戻すのは導入直前の状態です。Adwaitaへ一律初期化する操作ではありません。バックアップ・処理記録・保存済み導入コードは削除せず、旧テーマ・拡張の資産も保持します。

## 中断からの復旧

導入・更新・解除が中断した場合は、まず共通入口で復旧します。

```sh
./install.sh recover
```

初回Flatpak自動適用と一括解除は、基本テーマと同じ処理記録に含まれます。個別解除で中断状態を回避しないでください。未確定分は逆順で戻し、確定済みなら確定処理を完了します。復旧中の競合も、保全を残して停止します。

導入対象のOS・Shell条件が変わっていても、解除・復旧はこのユーザーの保存記録の範囲で処理します。ユーザーのHOME・D-Bus、Python / Gioと復元対象の設定schemaは必要です。

適用・更新・解除時のコードは`~/.local/state/glass50/source-packages/<ID>/`へ保存します。Gitが使えない場合は、該当フォルダーの共通管理コードを使います。

```sh
python3 /path/to/saved-package/manage-desktop.py recover --package /path/to/saved-package
```

新しい保存済みコードは`manage-material.py`名で起動しても所有記録から共通復旧を選びます。現在の共通入口で管理中のものを、古い基本テーマ専用ツールで解除しないでください。

## 変更する場所

テーマは`~/.local/share/themes/Glass50-Material-Preview/`、独自拡張は`~/.local/share/gnome-shell/extensions/glass50-blur@myglass.local/`へ配置します。これらは旧称に由来する内部識別名です。Hyaluneへの文書上の改称後も、既存の導入・復元との互換性のため維持しています。

新規導入のGTK4入口は`~/.config/gtk-4.0/glass50-managed.css`を参照します。旧形式は復元情報を保つため既存の参照先を継続使用します。GSettingsは対象キーだけを変更します。元データ・モード・ユーザー設定値の有無と処理記録は`~/.local/state/glass50/installer-material-v1/`へ0600で保存します。Flatpakの保存先は[別記](FLATPAK.md)です。

この通常入口はシステムテーマ、GDM、パッケージ、サービス、ドライバー、ログイン方式を変更しません。任意ZIPにも共通管理ツールを含められますが、初回Flatpak一括適用の標準入口はGit checkoutの`./install.sh`です。
