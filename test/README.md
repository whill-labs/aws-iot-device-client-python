## 準備

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

## テストの実行

```bash
source ./test/env.sh
python3 -m unittest
```
