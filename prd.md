# RedactSafe - 改善版 Product Requirements Document (v2)

## Overview

**RedactSafe** v1の全27タスクが完了した後、コードレビューに基づく改善を実施する。以下の3分野を対象とする。

1. **OCR/検出パイプライン** — 精度向上、メモリ効率改善、バグ修正
2. **UI/UX操作性** — アクセシビリティ、安定性、コード保守性
3. **性能・安定性** — メモリ管理、プロセス管理、エラーハンドリング

## Target Audience

v1と同じ（行政職員・管理職・情報システム担当）

## Core Features

v1の機能に加え、以下の改善を実装する。

1. **セキュリティ修正** — ハードコードされたパスワード除去、トレースバック漏洩防止
2. **メモリ最適化** — 大容量PDFのbase64廃止、ページ再描画の統合
3. **OCR精度向上** — マイナンバー/法人番号のチェックデジット検証、重複検出の排除
4. **プロセス管理改善** — PythonワーカーのDrop実装、自動再起動、タイムアウト
5. **アクセシビリティ改善** — ARIA属性、フォーカストラップ、WCAG準拠
6. **UI安定性** — Undoのページ跨ぎ問題修正、alert()廃止、モジュール分割

## Tech Stack

v1と同じ（変更なし）

## Architecture

v1と同じ（変更なし）

## Data Model

v1と同じ（変更なし）

## UI/UX Requirements

v1に加え、以下を改善する。

- WCAG AA準拠のフォントサイズ（最小12px）とコントラスト比（4.5:1以上）
- 全モーダルダイアログにARIA属性とフォーカストラップを実装
- メニューバーにARIA属性を実装
- alert()を独自トースト/ダイアログに置き換え
- サイドバーの折りたたみ機能を追加
- main.jsを複数モジュールに分割

## Security Considerations

v1に加え、以下を修正する。

- PDFオーナーパスワードをランタイム生成に変更（ハードコード廃止）
- エラーレスポンスに内部パスやトレースバックを含めない
- page_num等の入力値をバリデーションする

## Constraints & Assumptions

v1と同じ（変更なし）

## Success Criteria

1. 100MBのPDFで確定処理がOOMクラッシュしないこと
2. Pythonワーカー異常終了後に自動再起動すること
3. マイナンバー/法人番号の誤検出率が大幅に低下すること
4. 全モーダルでキーボード操作が完全に機能すること
5. main.jsのモジュール分割により各ファイルが1000行以下であること

---

## Task List

```json
[
  {
    "category": "security",
    "description": "ハードコードされたPDFオーナーパスワードをランタイム生成に変更する",
    "steps": [
      "worker.pyとpdf_sanitizer.pyからハードコードされたパスワード 'RedactSafe_Owner_2024!' を削除",
      "ランダムパスワードをsecrets.token_urlsafe()で生成しメモリのみに保持する実装に変更",
      "出力PDFのユーザーパスワードは空（誰でも開ける）、オーナーパスワードのみで制限をかける方式を維持",
      "確定処理後にパスワードをメモリから明示的に削除",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "security",
    "description": "Pythonワーカーのエラーレスポンスからトレースバックと内部パスを除去する",
    "steps": [
      "worker.pyのprocess_message()でtraceback.format_exc()をエラーレスポンスに含めている箇所を修正",
      "エラーメッセージを 'Internal error' のみにし、dataフィールドにスタックトレースを含めない",
      "page_numパラメータのバリデーションを全ハンドラに追加（0以上、page_count以下）",
      "負のpage_numや異常に大きなpage_numが渡された場合は 'Invalid page number' エラーを返す",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "performance",
    "description": "大容量PDFのIPC通信をbase64からファイルパスベースに変更する",
    "steps": [
      "lib.rsのfinalize_masking_pdfコマンドでPDFをbase64で送信するのをやめ、一時ファイルパスを渡す方式に変更",
      "worker.pyのhandle_finalize_maskingでpdf_data_b64の代わりにpdf_pathを受け取れるように修正",
      "lib.rsのread_file_as_base64/save_base64_to_fileに100MBのサイズ制限を追加",
      "フロントエンドのmain.jsで確定処理時にPDFをbase64エンコードせずパスを渡すように変更",
      "handle_extract_text_digitalでpdf_pathが渡された場合にbase64エンコードをスキップするように修正",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "performance",
    "description": "OCRパイプラインで同一ページの再描画を1回に統合する",
    "steps": [
      "ocr_pipeline.pyの_render_page_to_image()を呼び出している箇所を特定（analyze_layout, recognize_text_paddleocr, recognize_text_tesseract）",
      "run_ocr_pipeline()でページ画像を1回だけレンダリングし、全ステップに同じPIL Imageを渡すように変更",
      "PNG encode/decodeのラウンドトリップを排除：pix.samplesから直接PIL Imageを構築（Image.frombytes）",
      "低信頼度領域のTesseractフォールバックでも再描画しないことを確認",
      "Python単体テストでレンダリング回数が1回/pageになることを確認",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "performance",
    "description": "secure_delete_fileをSSD最適化し、不要な3パス書き込みを削除する",
    "steps": [
      "worker.pyのsecure_delete_file()で3パス（ゼロ・ランダム・ゼロ）書き込みを1パス（ゼロのみ）に変更",
      "SSD環境では複数回書き込みが逆効果（ウェアレベリング・寿命短縮）であることをコメントで記載",
      "os.fsync()は1回のみ呼び出す",
      "一時ファイルがメモリ上のみの場合はファイル書き込み自体をスキップする条件を追加",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "stability",
    "description": "PythonWorkerにDropを実装し、ゾンビプロセスを防止する",
    "steps": [
      "python_worker.rsのPythonWorker構造体にimpl Dropを追加",
      "drop()でstderr_stopフラグをtrueに設定し、child.kill()とchild.wait()を呼び出す",
      "BufReaderをPythonWorker構造体に保持し、call()ごとに再作成しないように変更",
      "WorkerStateのMutexがdropされた時に自動的にプロセスが終了することを確認",
      "cargo test、cargo clippyが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "stability",
    "description": "Pythonワーカーの異常終了時に自動再起動するメカニズムを実装する",
    "steps": [
      "lib.rsのworker_get_statusまたは各ワーカーコマンドの実行前にプロセス生存チェックを追加",
      "プロセスが終了している場合は自動的にPythonWorker::spawn()で再起動",
      "cancel_worker実行後も次回コマンド実行時に自動再起動することを確認",
      "再起動時にinfoレベルのログを記録",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "stability",
    "description": "Pythonワーカーのcall()にタイムアウトを追加し、WorkerStateのMutexを改善する",
    "steps": [
      "python_worker.rsのcall()メソッドにタイムアウト（デフォルト5分、確定処理は10分）を追加",
      "タイムアウト時にプロセスをkillしエラーを返す",
      "inspect.signature()の結果を起動時にキャッシュし、毎回の呼び出しを回避（PROGRESS_HANDLERSセットの作成）",
      "WorkerStateのMutexが長時間のOCR/確定処理中にcancel_workerをブロックしないように、call()を別スレッドで実行する方式を検討",
      "cargo test、cargo clippyが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "stability",
    "description": "Windowsでのアトミックセーブを修正し、on_window_eventでルートハッシュを保存する",
    "steps": [
      "document_state.rsのsave_to_file()でWindows POSIX renameの問題を修正：fs::hard_link + remove_fileパターンを使用",
      "lib.rsのon_window_eventハンドラでアプリ終了時にsave_current_day_root_hash()を呼び出す",
      "load_from_file()にファイルサイズ上限（100MB）を追加",
      "can_recover()でファイル全体を読まず先頭数KBのみでJSON妥当性チェックするように変更",
      "cargo test、cargo clippyが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "stability",
    "description": "正規表現のタイムアウトをスレッドベースで実装し、ルール読込をキャッシュする",
    "steps": [
      "pii_detector.pyのdetect_pii()でregex matchingをThreadPoolExecutorで実行し、REGEX_TIMEOUT_SECONDSでタイムアウトさせる",
      "タイムアウト時はそのルールの結果を空として扱い、警告をstderrに出力",
      "detect_pii()にrulesパラメータがNoneの場合、初回のみload_rules()を呼び出し結果をキャッシュする",
      "worker.pyの_open_pdf()でファイルハンドルをwith文で適切にクローズする",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "detection",
    "description": "マイナンバー・法人番号のチェックデジット検証を追加し誤検出を削減する",
    "steps": [
      "pii_detector.pyにvalidate_my_number(digits)関数を追加：12桁のチェックデジット（mod 11）を検証",
      "pii_detector.pyにvalidate_corporate_number(digits)関数を追加：13桁のチェックデジットを検証",
      "detection_rules.yamlのマイナンバーパターンをカスタムバリデータ付きに変更",
      "detection_rules.yamlの法人番号パターンをカスタムバリデータ付きに変更",
      "PII検出後にバリデーションを実行し、不合格のマッチを除外する処理をdetect_pii()に追加",
      "テストケースを追加：有効・無効なマイナンバー・法人番号の検出確認",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "detection",
    "description": "電話番号パターンの網羅性を向上し、MeCab氏名検出との重複を排除する",
    "steps": [
      "detection_rules.yamlの電話番号パターンにカッコ書き（03）1234-5678、スペース区切り 0120 123 456 を追加",
      "name_detector.pyのhonorificsリストから重複する'氏'を削除",
      "pii_detector.pyのdetect_pii()でMeCab名前検出と正規表現検出の重複排除を追加（IoUベースでbboxが重複する場合は信頼度の高い方を優先）",
      "住所パターンの30文字制限を緩和し、行境界を超えないよう改行文字で区切る",
      "生年月日パターンで99月99日等の不正日付を除外するバリデーションを追加",
      "テストケースを追加：新しい電話番号形式、重複排除、不正日付の確認",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": true
  },
  {
    "category": "detection",
    "description": "回転変換コードを単一実装に統一し、レイアウト解析結果を活用する",
    "steps": [
      "worker.pyの_transform_bbox_for_rotation()をcoord_utils.pyのrotate_bbox()に統合",
      "worker.pyのhandle_finalize_maskingで統合されたrotate_bbox()を使用するように変更",
      "ocr_pipeline.pyのrun_ocr_pipeline()でlayout_regionsの結果をテキスト認識に活用する（表領域のOCR優先度を上げる等）",
      "bbox_normalizer.pyの行マージ閾値に絶対最大ギャップ（例：20pt）を追加し、巨大bboxによる誤統合を防止",
      "行マージ時のテキスト結合にスペース区切りを追加（word1word2 → word1 word2）",
      "テストケースを追加：回転統合、行マージ上限、テキスト結合の確認",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": false
  },
  {
    "category": "detection",
    "description": "レイアウト解析結果がテキスト認識で活用されない問題を修正する",
    "steps": [
      "ocr_pipeline.pyのanalyze_layout()で取得したlayout_regionsをrecognize_text_paddleocr()に渡す",
      "表（table）として検出された領域ではTesseractフォールバックを優先的に使用するよう変更",
      "図・画像として検出された領域ではOCRをスキップし手動マスキング対象としてマークする",
      "layout_regionsの結果を最終的なテキスト抽出結果のメタデータに含める",
      "テストスキャンPDFでレイアウト解析結果がOCR結果に反映されることを確認",
      "cargo clippyとnpm run buildが通ることを確認"
    ],
    "passes": false
  },
  {
    "category": "ux",
    "description": "Undoのページ跨ぎ問題を修正し、一括操作のUndoを追加する",
    "steps": [
      "main.jsのperformUndo()でop.pageNumと現在のcurrentPageが異なる場合、自動的に該当ページに遷移してからUndoを実行する",
      "undo-manager.jsにbeginMacro()/endMacro()を追加し、一括操作（全てON/OFF）を1つのUndoステップとして扱う",
      "サイドバーとツールバーの全てON/OFFボタンでbeginMacro/endMacroを使用する",
      "toggle undoで前のenabled状態を保存し、正確に元に戻せるようにする",
      "loadPdfWithAnalysis()の開始時にundoManagerをclear()する",
      "npm run buildが通ることを確認"
    ],
    "passes": false
  },
  {
    "category": "ux",
    "description": "全モーダルダイアログにARIA属性・フォーカストラップ・Escapeハンドラを追加する",
    "steps": [
      "index.htmlの全モーダルダイアログにrole='dialog', aria-modal='true', aria-labelledbyを追加",
      "メニューバーにrole='menubar', role='menuitem', aria-haspopup, aria-expandedを追加",
      "main.jsにフォーカストラップユーティリティ（trapFocus）を実装し、全モーダルに適用",
      "署名付きPDFダイアログと確定実行者警告ダイアログにEscapeキーハンドラを追加",
      "アイコンのみのボタン（+、-、<<、>>）にaria-labelを追加",
      "npm run buildが通ることを確認"
    ],
    "passes": false
  },
  {
    "category": "ux",
    "description": "alert()を独自トースト通知に置き換え、サイドバー折りたたみ機能を追加する",
    "steps": [
      "main.jsにshowToast(message, type)関数を実装（type: error/warning/info、自動消失3秒）",
      "index.htmlにトースト通知コンテナ（#toast-container）を追加",
      "src/styles.cssにトースト通知のスタイル（画面右上固定、スライドインアニメーション）を追加",
      "全alert()呼び出し（8箇所）をshowToast()に置き換え",
      "サイドバーに折りたたみボタンを追加し、CSSクラスで表示/非表示を切り替え",
      "npm run buildが通ることを確認"
    ],
    "passes": false
  },
  {
    "category": "ux",
    "description": "WCAG AA準拠のフォントサイズとコントラスト比を修正する",
    "steps": [
      "src/styles.cssのステータスバーテキストを11px→12pxに変更",
      "ステータスバッジを10px→11pxに変更",
      "サイドバーのプレースホルダー #999 on #f5f5f5 を #666 on #f5f5f5 に変更してコントラスト4.5:1以上を確保",
      "リージョンメタ情報の #888 on #fff を #666 on #fff に変更",
      "フィルターセレクトのfocusスタイルにoutline: 2px solid #4a90d9を追加し、outline: noneを削除",
      "ボタンにfocus-visibleスタイル（box-shadowによるフォーカスリング）を追加",
      "npm run buildが通ることを確認"
    ],
    "passes": false
  },
  {
    "category": "ux",
    "description": "main.jsを複数モジュールに分割し、重複するキーボードハンドラを統合する",
    "steps": [
      "src/ui/dialogs.jsを新規作成：全モーダルダイアログの表示/非表示/フォーカス管理を移動",
      "src/ui/toast.jsを新規作成：トースト通知機能を移動",
      "src/ui/sidebar.jsを新規作成：サイドバーのレンダリング・フィルタリング・イベントハンドラを移動",
      "src/ui/menu.jsを新規作成：メニューバーのドロップダウン・キーボードナビゲーションを移動",
      "2つのkeydownイベントリスナーを1つに統合",
      "index.htmlで分割後のJSファイルを読み込む",
      "各モジュールファイルが1000行以下であることを確認",
      "npm run buildが通ることを確認"
    ],
    "passes": false
  },
  {
    "category": "ux",
    "description": "PDFビューアのレンダリングキャンセルとfitToWidthのスクロールバー対応を追加する",
    "steps": [
      "pdf-viewer.jsのrenderPage()でPDF.jsのRenderTask.cancel()を使用し、ページ切替時に前のレンダリングをキャンセル",
      "fitToWidth()でスクロールバー幅（約17px）を考慮してズーム計算を行う",
      "masking-overlay.jsでホバー時の全再描画を最適化：変更されたリージョンのみ再描画するdirty-region方式を実装",
      "handle hit detectionでコーナーハンドルとエッジハンドルを視覚的に区別（コーナーは大きく、エッジは小さく）",
      "npm run buildが通ることを確認"
    ],
    "passes": false
  },
  {
    "category": "ux",
    "description": "PDF再オープン機能とbase64メモリ最適化を追加する",
    "steps": [
      "main.jsのopenPdfFile()でドキュメント読込済みの場合に確認ダイアログを表示し、ユーザーが承認した場合のみ新しいPDFを開けるように変更",
      "PDF再オープン時にundoManager.clear()、全グローバル状態のリセット、ウォーターマーク非表示を行う",
      "main.jsのloadPdfWithAnalysis()でbase64文字列→binary string→Uint8Arrayの2段変換を1段に最適化",
      "サイドバーのonSidebarRegionClick()でsetTimeout(200ms)をpdfViewerのonPageChangeコールバックに置き換え",
      "npm run buildが通ることを確認"
    ],
    "passes": false
  },
  {
    "category": "integration",
    "description": "改善内容のエンドツーエンド統合テストを実行する",
    "steps": [
      "デジタルPDF（test-digital-10pages.pdf）で改善後のパイプラインをテスト：ファイル読込→テキスト抽出→PII検出→仮マスキング→確定→安全PDF出力",
      "マイナンバー・法人番号のチェックデジット検証で誤検出が減少していることを確認",
      "100MB相当のPDFでOOMクラッシュが発生しないことを確認（ファイルパスベース通信）",
      "Pythonワーカーをkillした後の自動再起動を確認",
      "全モーダルダイアログでキーボード操作（Tab, Escape, Enter）が完全に機能することを確認",
      "Undoのページ跨ぎ操作が正しく動作することを確認",
      "サイドバーの折りたたみ・展開が正しく動作することを確認",
      "cargo test、cargo clippy、npm run buildが全て通ることを確認"
    ],
    "passes": false
  }
]
```

---

## Agent Instructions

1. Read `activity.md` first to understand current state
2. Find next task with `"passes": false`
3. Complete all steps for that task
4. Verify in browser using agent-browser
5. Update task to `"passes": true`
6. Log completion in `activity.md`
7. Repeat until all tasks pass

**Important:** Only modify the `passes` field. Do not remove or rewrite tasks.

---

## Completion Criteria

All tasks marked with `"passes": true`
