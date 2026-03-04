## ディレクトリ構成

```
test/
├── e2e/          # AWS IoT実環境へ接続するE2Eテスト
│   ├── common.py
│   ├── test_mqtt.py
│   ├── test_pubsub.py
│   ├── test_jobs.py
│   ├── test_classic_shadow.py
│   └── test_named_shadow.py
└── unit/         # mockを使ったユニットテスト
    ├── test_mqtt.py
    ├── test_pubsub.py
    ├── test_shadow.py
    ├── test_shadow_callbacks.py
    ├── test_classic_shadow.py
    ├── test_named_shadow.py
    ├── test_jobs.py
    ├── test_jobs_callbacks.py
    └── test_dictdiff.py
```

## テスト一覧

### unit

| ファイル | テストクラス | テストケース |
| --- | --- | --- |
| test_dictdiff.py | DictdiffTestCase | test_dictdiff_no_difference |
| | | test_dictdiff_from_empty |
| | | test_dictdiff_to_empty |
| | | test_dictdiff_add_items |
| | | test_dictdiff_remove_items |
| | | test_dictdiff_update_items |
| | | test_dictdiff_update_dict |
| test_mqtt.py | TestConnectionParams | test_defaults |
| | | test_expands_home |
| | TestInit | test_mtls |
| | | test_websocket |
| | TestCallbacks | test_on_resubscribe_complete_raises_on_rejected |
| | | test_on_resubscribe_complete_succeeds |
| | TestConnectionCallbacks | test_on_connection_interrupted |
| | | test_on_connection_resumed_resubscribes_when_session_not_present |
| | | test_on_connection_resumed_skips_resubscribe_when_session_present |
| | TestWebsocketProxy | test_init_websocket_with_proxy_options |
| test_pubsub.py | TestSubscriber | test_subscribes_to_topic |
| | | test_callback_parses_json |
| | TestPublisher | test_publishes_payload |
| | | test_empty_payload_does_not_publish |
| test_shadow.py | TestDocumentTracker | test_get_set |
| | | test_update_same_value_returns_none |
| | | test_update_diff_only |
| | | test_update_full_doc |
| | TestShadowData | test_update_reported |
| | | test_update_desired |
| | | test_update_both |
| test_classic_shadow.py | TestClassicShadowClient | test_subscribes_on_init |
| | | test_publishes_get_shadow_on_init |
| | | test_update_shadow_request_publishes |
| | | test_update_noop_when_both_none |
| test_named_shadow.py | TestNamedShadowClient | test_subscribes_with_shadow_name |
| | | test_publishes_get_named_shadow_on_init |
| | | test_update_shadow_request_publishes |
| | | test_label_returns_shadow_name |
| | | test_update_noop_when_both_none |
| | | test_get_accepted_uses_full_document |
| test_jobs.py | TestJobsClient | test_subscribes_on_init |
| | | test_try_start_next_job_publishes |
| | | test_try_start_next_job_skips_when_already_working |
| | | test_job_thread_fn_calls_job_func_and_reports_succeeded |
| | | test_job_thread_fn_reports_failed_on_exception |
| test_shadow_callbacks.py | TestShadowCallbacks | test_delta_ignored_when_state_is_none |
| | | test_delta_deleted_property_resets_reported |
| | | test_delta_invalid_request_resets_desired |
| | | test_delta_unexpected_exception_is_reraised |
| | | test_get_shadow_accepted_uses_reported_state |
| | | test_get_shadow_accepted_ignores_when_delta_present |
| | | test_get_shadow_accepted_sets_default_when_property_missing |
| | | test_get_shadow_accepted_returns_early_when_reported_already_set |
| | | test_get_shadow_accepted_reraises_unexpected_errors |
| | | test_get_shadow_rejected_404_sets_default |
| | | test_get_shadow_rejected_non_404_raises |
| | | test_update_shadow_accepted_sets_desired_and_calls_callback |
| | | test_update_shadow_accepted_reraises_when_desired_callback_fails |
| | | test_update_shadow_rejected_raises |
| | | test_on_publish_update_shadow_raises_when_future_fails |
| | | test_change_both_values_publishes_update |
| | | test_change_desired_value_publishes_update |
| test_jobs_callbacks.py | TestJobsCallbacks | test_try_start_next_job_skips_when_disconnect_called |
| | | test_init_wraps_subscription_failure |
| | | test_done_working_on_job_retries_when_waiting |
| | | test_on_next_job_execution_changed_none |
| | | test_on_next_job_execution_changed_sets_wait_flag_while_working |
| | | test_on_next_job_execution_changed_starts_now_when_idle |
| | | test_on_next_job_execution_changed_wraps_unexpected_error |
| | | test_on_publish_start_next_pending_job_execution_raises |
| | | test_start_next_pending_job_accepted_spawns_thread |
| | | test_start_next_pending_job_accepted_wraps_thread_creation_error |
| | | test_start_next_pending_job_accepted_without_execution_marks_done |
| | | test_start_next_pending_job_rejected_raises |
| | | test_job_thread_user_defined_failure_sets_status_details |
| | | test_on_publish_update_job_execution_raises |
| | | test_on_update_job_execution_accepted_calls_done |
| | | test_on_update_job_execution_accepted_wraps_done_error |
| | | test_on_update_job_execution_rejected_raises |

### e2e

| ファイル | テストクラス | テストケース |
| --- | --- | --- |
| test_mqtt.py | TestMqtt | test_mqtt_setup |
| test_pubsub.py | TestPubSub | test_pubsub |
| test_jobs.py | TestJobs | test_jobs |
| test_classic_shadow.py | TestClassicShadow | test_classic_shadow_reported |
| | | test_classic_shadow_reported_value_delta |
| | | test_classic_shadow_desired_matches_with_reported |
| test_named_shadow.py | TestNamedShadow | test_named_shadow_reported |
| | | test_named_shadow_reported_value_delta |
| | | test_named_shadow_desired_matches_with_reported |

## テストの実行

```bash
# ユニットテストのみ
PYTHONPATH=src pytest test/unit -v

# E2Eテスト（要AWS認証情報）
source ./test/env.sh
PYTHONPATH=src pytest test/e2e -v

# 全テスト
source ./test/env.sh
PYTHONPATH=src pytest test -v

# ユニットテストのカバレッジ確認（推奨: pytest-cov）
PYTHONPATH=src pytest -q test/unit \
  --cov=awsiotclient \
  --cov-branch \
  --cov-report=term-missing \
  --cov-fail-under=95

# 補助: pytest-cov が利用できない環境では trace を使用
# (pytest-cov は Python 3.8+ で利用可能)
PYTHONPATH=src python -m trace --count --missing --summary --module pytest -q test/unit
```

`awsiotclient` がグローバル環境にもインストールされている場合、`PYTHONPATH=src` を付けないと `src/` ではなく `site-packages` の実装を参照する可能性があります。

## E2Eテストの準備

```bash
# モノの作成
aws iot create-thing --thing-name awsiotclient-test

# 証明書の作成
aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile ./test/certs/certificate.pem.crt \
  --public-key-outfile ./test/certs/public.pem.key \
  --private-key-outfile ./test/certs/private.pem.key > ./test/certs/cert.json

# 証明書へのモノのアタッチ
aws iot attach-thing-principal \
  --principal "$(jq -r .certificateArn < ./test/certs/cert.json)" \
  --thing-name awsiotclient-test

# 証明書へのポリシーのアタッチ
aws iot attach-policy \
    --target "$(jq -r .certificateArn < ./test/certs/cert.json)" \
    --policy-name <policy>
```
