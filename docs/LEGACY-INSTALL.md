# Hyalune：従来の基本テーマパッケージ

この文書は`package-theme.py`が組み立てる従来の基本テーマ用です。現行のHyalune Dark材質版はGit checkoutの`./install.sh`を使ってください。[標準導入](INSTALL.md)

従来パッケージには基本Shell / GTK CSSと`manage-theme.py`を含み、材質・任意ぼかし・Flatpak自動適用は含みません。管理対象の確認済みVM内で、展開先を`--package`に指定して`plan`、`apply`、`update`、`remove`、`recover`、`status`を使用します。

材質管理が有効な場合は重なる変更を拒否します。現行材質版やT16の解除・復旧をこの旧ツールで代用しないでください。既存の復旧用パッケージは削除しません。
