# RedactSafe - Activity Log

## Current Status
**Last Updated:** 2026-04-21
**Tasks Completed:** 4 / 25
**Current Task:** Task 4 - JSONベースの状態管理システムと座標系ユーティリティ (完了)

---

## Session Log

### 2026-04-21 - Task 1: Tauri v2プロジェクト初期化とディレクトリ構造構築

**変更内容:**
- `npm init` で package.json 作成
- Vite v8.0.9 + @tauri-apps/cli v2.10.1 + @tauri-apps/api インストール
- `npx tauri init` で src-tauri/ (Rust backend) を初期化
- src/ (Vanilla JS frontend) に index.html, main.js, styles.css 作成
- python-worker/ ディレクトリ作成
- tauri.conf.json: identifier を com.redactsafe.app に設定、ウィンドウサイズ 1200x800 に調整
- vite.config.js: Tauri dev サーバー設定 (port 1420)
- .gitignore: dist/, target/ を追加

**実行コマンド:**
- `npm install -D vite @tauri-apps/cli@latest` - 成功
- `npm install @tauri-apps/api@latest` - 成功
- `npx tauri init` - 成功
- `cargo check` (src-tauri/) - 成功 (507 crates, 1m09s)
- `npm run build` - 成功 (dist/ にビルド出力)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** なし

### 2026-04-21 - Task 2: Pythonワーカーの依存関係設定とstdin/stdout通信確立

**変更内容:**
- `python-worker/requirements.txt` 作成（PyMuPDF, Pillow, paddleocr, paddlepaddle, fugashi, unidic-lite, pyyaml）
- `python-worker/worker.py` 作成 - stdin/stdoutベースのJSON-RPC 2.0通信プロトコル実装
  - `ping` コマンド: メッセージのエコー応答
  - `get_version` コマンド: ワーカー バージョンと利用可能メソッド一覧
  - エラーハンドリング: JSON parse error, method not found, internal error
- `src-tauri/src/python_worker.rs` 作成 - Pythonワーカープロセス管理モジュール
  - Pythonパス自動検出（python3/python/py順）
  - worker.pyパス解決（dev/production両対応）
  - JSON-RPCリクエスト送受信（stdin/stdout）
  - プロセス生存確認・kill機能
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `init_worker`: Pythonワーカープロセス起動
  - `shutdown_worker`: ワーカー終了
  - `worker_ping`: ping送信
  - `worker_get_status`: ワーカー接続状態確認
- `src-tauri/Cargo.toml` 更新 - tauri-plugin-shell, uuid 追加
- `src-tauri/capabilities/default.json` 更新 - shell権限追加
- `index.html` 更新 - Python Workerテストパネル追加（Initialize Worker / Send Ping）
- `src/styles.css` 更新 - テストパネルUIスタイル追加
- `src/main.js` 更新 - ワーカー初期化・ping通信のロジック実装

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (warningなし)
- `cargo clippy` (src-tauri/) - 成功 (warningなし)
- `npm run build` - 成功 (dist/ にビルド出力)

**スクリーンショット:** ブラウザ権限未承認のため未取得 (ビルド成功で代替確認)

**課題:** Pythonがシステムにインストールされていないため、実際のワーカー通信テストは未実施。Python環境導入後に実行時テストが必要。

### 2026-04-21 - Task 3: JSON-Lines形式のロギングシステムとハッシュチェーン

**変更内容:**
- `src-tauri/src/audit_log.rs` 作成 - 監査ログモジュール実装
  - JSON-Lines形式のログ出力（日次ローテーション対応）
  - SHA-256ハッシュチェーン（各レコードにprev_hash + hash、genesisハッシュ起点）
  - 日次ルートハッシュを `root_hashes.jsonl` に別保存
  - ログ保存先: `%APPDATA%/RedactSafe/logs/`（`dirs::data_dir()` 使用）
  - ログファイル名: `audit_YYYY-MM-DD.jsonl`
  - チェーン整合性検証機能（`verify_chain`）
  - OSユーザー名自動取得（`get_current_user`）
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `log_event`: 監査イベント記録（event, user, document_id, data）
  - `get_log_dir`: ログディレクトリパス取得
  - `verify_log_chain`: 指定日のログチェーン検証
  - `AuditState` 状態管理をアプリに統合
- `src-tauri/Cargo.toml` 更新 - 依存関係追加（chrono, sha2, hex, dirs）
- `index.html` 更新 - Audit Logテストパネル追加
- `src/main.js` 更新 - 監査ログテストUIロジック追加

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功
- `cargo clippy` (src-tauri/) - 成功 (warningなし)
- `npm run build` - 成功

**課題:** ブラウザでの動作確認はTauri dev serverの起動権限が未承認のため未実施。ビルド成功で代替確認。

### 2026-04-21 - Task 4: JSONベースの状態管理システムと座標系ユーティリティ

**変更内容:**
- `src-tauri/src/document_state.rs` 作成 - ドキュメント状態管理モジュール実装
  - データ構造定義: `DocumentStatus` (Draft/Confirmed/Finalized), `RegionType` (Name/Address/Phone/Email/BirthDate/MyNumber/CorporateNumber/Custom), `RegionSource` (Auto/Manual), `CoordinateSystem`, `Region`, `PageInfo`, `HistoryEntry`, `MaskingDocument`
  - CRUD操作: 新規作成、JSONファイルからの読込/書込、ページ追加、リージョン追加/切替/削除/BBox更新、一括ON/OFF
  - 状態遷移ロジック: draft→confirmed（確認承認）、confirmed→draft（差し戻し）、confirmed→finalized（確定）、finalizedは不可逆
  - 各遷移でhistoryに自動記録、差し戻し時はrevision自動インクリメント
  - 編集制約: confirmed/finalized状態ではリージョン操作不可
  - 12個のRust単体テスト作成（全テスト通過）
- `src-tauri/src/lib.rs` 更新 - Tauriコマンド追加
  - `create_document`, `get_document`, `get_document_status`, `get_document_summary`
  - `add_page`, `add_region`, `toggle_region`, `remove_region`, `update_region_bbox`, `set_all_regions_enabled`
  - `confirm_document`, `rollback_document`, `finalize_document`
  - `save_document`, `load_document`
  - `DocumentState` 状態管理をアプリに統合
- `python-worker/coord_utils.py` 作成 - 座標変換ユーティリティ
  - `pdf_point_to_pixel` / `pixel_to_pdf_point` - PDF point ↔ pixel 変換
  - `bbox_pdf_point_to_pixel` / `bbox_pixel_to_pdf_point` - bbox変換
  - `rotate_bbox` - ページ回転補正（0°/90°/180°/270°対応）
- `python-worker/worker.py` 更新 - 座標変換JSON-RPCコマンド追加
  - `pdf_point_to_pixel`, `pixel_to_pdf_point`, `bbox_pdf_to_pixel`, `bbox_pixel_to_pdf`, `rotate_bbox`
  - バージョンを0.2.0に更新
- `python-worker/tests/test_coord_utils.py` 作成 - 座標変換単体テスト（20テストケース）
- `index.html` 更新 - Document State Testパネル追加
- `src/main.js` 更新 - ドキュメント状態テストUIロジック追加
- `src/styles.css` 更新 - テスト結果テキストスタイル追加

**実行コマンド:**
- `cargo check` (src-tauri/) - 成功 (dead_code warnings のみ)
- `cargo clippy` (src-tauri/) - 成功 (dead_code warnings のみ)
- `cargo test` (src-tauri/) - 成功 (12 tests passed)
- `npm run build` - 成功
- `npm run tauri dev` - 成功 (localhost:1420 で起動確認)

**課題:** Pythonがシステムにインストールされていないため、Python単体テストは未実施。Python環境導入後に実行必要。ブラウザ動作確認は権限未承認のためビルド成功で代替。
