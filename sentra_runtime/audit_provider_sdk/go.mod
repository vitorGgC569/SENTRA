module sentra.local/audit-provider-sdk

go 1.27.1

require (
 github.com/nats-io/nats.go v1.53.1
 github.com/codenotary/immudb v0.0.0
 github.com/transparency-dev/tessera v0.0.0
 github.com/golang/protobuf v1.5.4
)

replace github.com/codenotary/immudb => ../../third_party/immudb
replace github.com/transparency-dev/tessera => ../../third_party/tessera
