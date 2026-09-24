# テスト

## 構成

```
test/
├── unit/                 # AWS に接続しないテスト（CI で実行）
│   ├── fakes.py          # MQTT 接続と AWS IoT（Shadow / Jobs）の in-memory fake
│   ├── conftest.py
│   ├── test_dictdiff.py  # 差分計算とマージ（性質テストを含む）
│   ├── test_shadow.py    # classic / named shadow の振る舞い
│   ├── test_jobs.py      # jobs の実行・失敗報告・復帰・並行性
│   ├── test_mqtt.py      # 接続パラメータ、接続の組み立て、再接続
│   └── test_pubsub.py
└── e2e/                  # 実際の AWS IoT に接続するテスト（手元でのみ実行）
```

### unit テストの考え方

- ライブラリは公開 API だけを通して操作します。内部のメソッドやコールバックを直接呼ぶテストは書きません。
- AWS との境界は `awscrt.mqtt.Connection` 1 か所です。`FakeConnection` がこれを置き換え、`FakeShadowService` と `FakeJobsService` が `$aws/things/...` のトピックに応答します。`awsiot` SDK 自体は本物が動くため、トピック名や JSON の組み立ても検証されます。
- 検証は fake 側の状態で行います。たとえば「`change_reported_value` を呼んだあと、クラウドの reported がその値になっているか」を確かめます。
- `mqtt.init()` は本物の builder で接続オブジェクトを作り、その属性を確認します。接続（`connect()`）はしないので、ネットワークには出ません。
- すべてのテストで次の 2 点を自動で確認します。
  - DEBUG ログが正しく整形できること
  - サブスクライバーのコールバックで想定外の例外が起きていないこと（例外を想定するテストは `broker.take_callback_errors()` で明示的に受け取る）

## 実行

```bash
poetry install

# unit テスト
poetry run pytest test/unit

# カバレッジ付き（90% 未満で失敗）
poetry run pytest test/unit --cov --cov-report=term-missing

# lint / 型チェック（CI と同じ）
poetry run black --check src test
poetry run isort --check-only src test
poetry run flake8 src test
poetry run mypy src
```

`pytest` を引数なしで実行すると e2e も対象になりますが、下記の環境変数がなければ自動でスキップされます。

## E2E テスト

公開リポジトリのため、CI では実行しません。手元で AWS の認証情報を用意して実行してください。

### 準備

```bash
# モノの作成
aws iot create-thing --thing-name awsiotclient-test

# 証明書の作成
aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile ./test/e2e/certs/certificate.pem.crt \
  --public-key-outfile ./test/e2e/certs/public.pem.key \
  --private-key-outfile ./test/e2e/certs/private.pem.key > ./test/e2e/certs/cert.json

# 証明書へのモノのアタッチ
aws iot attach-thing-principal \
  --principal "$(jq -r .certificateArn < ./test/e2e/certs/cert.json)" \
  --thing-name awsiotclient-test

# 証明書へのポリシーのアタッチ
aws iot attach-policy \
    --target "$(jq -r .certificateArn < ./test/e2e/certs/cert.json)" \
    --policy-name <policy>
```

`test/e2e/certs/` には `AmazonRootCA1.pem` 以外をコミットしないでください（`.gitignore` で除外しています）。

### 実行

```bash
source ./test/env.sh   # AWSIOT_ENDPOINT, AWS_REGION, AWS_ACCOUNT_ID
poetry run pytest test/e2e -v
```

## ROS 環境で実行する場合

ROS 2 の環境を `source` したシェルでは、ROS の pytest プラグインが読み込まれてテストの邪魔をします。`pyproject.toml` の `addopts` で主なプラグインを無効にしています。
