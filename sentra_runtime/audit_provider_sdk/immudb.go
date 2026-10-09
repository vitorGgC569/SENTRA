package main

import (
 "bytes"
 "context"
 "crypto/ecdsa"
 "crypto/sha256"
 "encoding/binary"
 "fmt"
 "io"
 "net/url"
 "os"
 "strconv"
 "strings"
 "sync"
 "time"
 "github.com/codenotary/immudb/embedded/logger"
 store "github.com/codenotary/immudb/embedded/store"
 "github.com/codenotary/immudb/pkg/api/schema"
 immu "github.com/codenotary/immudb/pkg/client"
 statepkg "github.com/codenotary/immudb/pkg/client/state"
 "github.com/codenotary/immudb/pkg/database"
 "github.com/codenotary/immudb/pkg/signer"
 "github.com/golang/protobuf/proto"
 "google.golang.org/grpc"
 "google.golang.org/grpc/credentials"
)

type immuConfig struct {Endpoint string `json:"endpoint"`;Database string `json:"database"`;ServerUUID string `json:"server_uuid"`;KeyPrefix string `json:"key_prefix"`;TLS tlsPins `json:"tls"`;SigningKeyFile string `json:"signing_key_file"`;SigningKeySHA256 string `json:"signing_key_sha256"`}
type immuClient struct {cfg immuConfig;secrets map[string]string;key *ecdsa.PublicKey}
type anchoredState struct{mu sync.Mutex;value *schema.ImmutableState}
func(s *anchoredState)GetState(ctx context.Context,db string)(*schema.ImmutableState,error){if s.value==nil||s.value.Db!=db{return nil,fmt.Errorf("trusted anchor absent/db mismatch")};return proto.Clone(s.value).(*schema.ImmutableState),nil}
func(s *anchoredState)SetState(db string,value *schema.ImmutableState)error{
 if value.Db!=db||value.TxId<s.value.TxId||value.TxId==s.value.TxId&&!bytes.Equal(value.TxHash,s.value.TxHash){return fmt.Errorf("trusted state regression/fork")};s.value=proto.Clone(value).(*schema.ImmutableState);return nil
}
func(s *anchoredState)CacheLock()error{s.mu.Lock();return nil}
func(s *anchoredState)CacheUnlock()error{s.mu.Unlock();return nil}
func(s *anchoredState)SetServerIdentity(identity string){} // pinned UUID is checked independently, never inferred from caller
func newImmu(input initial)(provider,error){
 var cfg immuConfig;if err:=decode(input.Configuration,&cfg);err!=nil{return nil,err};u,err:=url.Parse(cfg.Endpoint)
 if err!=nil||u.Scheme!="https"||u.Hostname()==""||u.User!=nil||u.Path!=""||u.RawQuery!=""||u.Fragment!=""||cfg.ServerUUID==""||!strings.HasPrefix(cfg.KeyPrefix,"sentra-audit/"){return nil,fmt.Errorf("immudb scope/pins required")}
 if _,err:=secureTLS(cfg.TLS);err!=nil{return nil,err};if _,err:=filePin(cfg.SigningKeyFile,cfg.SigningKeySHA256);err!=nil{return nil,err}
 key,err:=signer.ParsePublicKeyFile(cfg.SigningKeyFile);if err!=nil{return nil,err}
 return &immuClient{cfg:cfg,secrets:input.Credentials,key:key},nil
}
type immuPayload struct {Key []byte `json:"key"`;Value []byte `json:"value"`;Anchor []byte `json:"anchor"`;AtTx uint64 `json:"at_tx"`;Proof []byte `json:"proof"`}
func(c *immuClient)verify(ctx context.Context,service schema.ImmuServiceClient,p immuPayload,wire *schema.VerifiableEntry)(*schema.ImmutableState,error){
 before:=&schema.ImmutableState{};if err:=proto.Unmarshal(p.Anchor,before);err!=nil||before.Db!=c.cfg.Database||len(before.TxHash)!=32{return nil,denied{"IMMUTABLE_ANCHOR_INVALID",nil}}
 if before.TxId>0 {if err:=before.CheckSignature(c.key);err!=nil{return nil,denied{"IMMUTABLE_ANCHOR_SIGNATURE_DENIED",nil}}}
 if wire.Entry==nil||wire.VerifiableTx==nil||wire.VerifiableTx.DualProof==nil||wire.VerifiableTx.Tx==nil||wire.VerifiableTx.Tx.Header==nil||wire.Entry.ReferencedBy!=nil||
  !bytes.Equal(wire.Entry.Key,p.Key)||!bytes.Equal(wire.Entry.Value,p.Value)||wire.Entry.Tx==0||p.AtTx!=0&&wire.Entry.Tx!=p.AtTx{return nil,denied{"IMMUTABLE_ENTRY_BINDING_DENIED",nil}}
 if wire.Entry.Metadata!=nil && wire.Entry.Metadata.Deleted{return nil,denied{"IMMUTABLE_ENTRY_DELETED",nil}}
 dual:=schema.DualProofFromProto(wire.VerifiableTx.DualProof)
 if dual.SourceTxHeader==nil||dual.TargetTxHeader==nil{return nil,denied{"IMMUTABLE_DUAL_PROOF_MISSING",nil}}
 entryDigest,err:=store.EntrySpecDigestFor(int(wire.VerifiableTx.Tx.Header.Version));if err!=nil{return nil,err}
 source,target:=before.TxId,wire.Entry.Tx
 sourceHash,targetHash:=schema.DigestFromProto(before.TxHash),dual.TargetTxHeader.Alh()
 entryRoot:=schema.DigestFromProto(wire.VerifiableTx.DualProof.TargetTxHeader.EH)
 if before.TxId>wire.Entry.Tx {source,target=wire.Entry.Tx,before.TxId;sourceHash=dual.SourceTxHeader.Alh();targetHash=schema.DigestFromProto(before.TxHash);entryRoot=schema.DigestFromProto(wire.VerifiableTx.DualProof.SourceTxHeader.EH)}
 if dual.TargetTxHeader.ID!=target || before.TxId>0 && dual.SourceTxHeader.ID!=source {return nil,denied{"IMMUTABLE_HEADER_ID_DENIED",nil}}
 spec:=database.EncodeEntrySpec(p.Key,schema.KVMetadataFromProto(wire.Entry.Metadata),p.Value)
 if !store.VerifyInclusion(schema.InclusionProofFromProto(wire.InclusionProof),entryDigest(spec),entryRoot){return nil,denied{"IMMUTABLE_INCLUSION_DENIED",nil}}
 if before.TxId>0 {
  if service!=nil {if err:=schema.FillMissingLinearAdvanceProof(ctx,dual,source,target,service);err!=nil{return nil,err};wire.VerifiableTx.DualProof=schema.DualProofToProto(dual)}
  if !store.VerifyDualProof(dual,source,target,sourceHash,targetHash){return nil,denied{"IMMUTABLE_CONSISTENCY_DENIED",nil}}
 }
 after:=&schema.ImmutableState{Db:c.cfg.Database,TxId:target,TxHash:targetHash[:],Signature:wire.VerifiableTx.Signature}
 if err:=after.CheckSignature(c.key);err!=nil{return nil,denied{"IMMUTABLE_STATE_SIGNATURE_DENIED",nil}}
 return after,nil
}
func(c *immuClient)Call(ctx context.Context,request command)(any,error){
 var p immuPayload;if err:=decode(request.Payload,&p);err!=nil{return nil,err}
 if request.Method=="verify_offline" {
  wire:=&schema.VerifiableEntry{};if err:=proto.Unmarshal(p.Proof,wire);err!=nil{return nil,err};after,err:=c.verify(ctx,nil,p,wire);if err!=nil{return nil,err}
  raw,err:=proto.Marshal(after);return map[string]any{"verified":err==nil,"anchor":raw,"verified_by":"immudb official inclusion/dual/linear-advance/state-signature"},err
 }
 u,_:=url.Parse(c.cfg.Endpoint);port,err:=strconv.Atoi(u.Port());if err!=nil{return nil,fmt.Errorf("explicit gRPC TLS port required")}
 tlsConfig,err:=secureTLS(c.cfg.TLS);if err!=nil{return nil,err}
 temporary,err:=os.MkdirTemp("","sentra-immudb-sdk-");if err!=nil{return nil,err};defer os.RemoveAll(temporary)
 client:=immu.NewClient().WithOptions(immu.DefaultOptions().WithAddress(u.Hostname()).WithPort(port).WithDir(temporary).WithMetrics(false).
  WithHealthCheckRetries(0).WithServerSigningPubKey(c.cfg.SigningKeyFile).WithDialOptions([]grpc.DialOption{grpc.WithTransportCredentials(credentials.NewTLS(tlsConfig))})).WithLogger(logger.NewSimpleLogger("sentra",io.Discard))
 if err:=client.OpenSession(ctx,[]byte(c.secrets["username"]),[]byte(c.secrets["password"]),c.cfg.Database);err!=nil{return nil,err}
 defer func(){closing,cancel:=context.WithTimeout(context.Background(),3*time.Second);defer cancel();client.CloseSession(closing)}()
 uuid,err:=statepkg.NewUUIDProvider(client.ServiceClient).CurrentUUID(ctx);if err!=nil||uuid!=c.cfg.ServerUUID{return nil,denied{"IMMUTABLE_SERVER_IDENTITY_DENIED",nil}}
 if request.Method=="status" {state,err:=client.CurrentState(ctx);if err!=nil{return nil,err};if err:=state.CheckSignature(c.key);err!=nil{return nil,denied{"IMMUTABLE_STATE_SIGNATURE_DENIED",nil}};raw,err:=proto.Marshal(state);return map[string]any{"server_uuid":uuid,"database":c.cfg.Database,"signed_state":raw,"trust_initialized":false},err}
 if !strings.HasPrefix(string(p.Key),c.cfg.KeyPrefix)||len(p.Key)>512||len(p.Value)>1_000_000 {return nil,fmt.Errorf("audit key/value scope bound")}
 before:=&schema.ImmutableState{};if err:=proto.Unmarshal(p.Anchor,before);err!=nil||before.Db!=c.cfg.Database||len(before.TxHash)!=32{return nil,fmt.Errorf("operator/previous verified state required")}
 if before.TxId>0 {if err:=before.CheckSignature(c.key);err!=nil{return nil,denied{"IMMUTABLE_ANCHOR_SIGNATURE_DENIED",nil}}}
 client.WithStateService(&anchoredState{value:before})
 switch request.Method {
 case "publish":
  // Native atomic precondition: an audit event key cannot be overwritten,
  // even if a new transport identity is mistakenly submitted elsewhere.
  result,err:=client.ServiceClient.VerifiableSet(ctx,&schema.VerifiableSetRequest{ProveSinceTx:before.TxId,SetRequest:&schema.SetRequest{
   KVs:[]*schema.KeyValue{{Key:p.Key,Value:p.Value}},Preconditions:[]*schema.Precondition{{Precondition:&schema.Precondition_KeyMustNotExist{KeyMustNotExist:&schema.Precondition_KeyMustNotExistPrecondition{Key:p.Key}}}}}})
  if err!=nil{return nil,err};if result.Tx==nil||result.Tx.Header==nil{return nil,fmt.Errorf("commit reference missing")};p.AtTx=result.Tx.Header.Id
 case "observe":
 case "export_tx":
  if p.AtTx==0{return nil,fmt.Errorf("committed transaction ID required")}
  verified,err:=client.VerifiedTxByID(ctx,p.AtTx);if err!=nil{return nil,err}
  stream,err:=client.ExportTx(ctx,&schema.ExportTxRequest{Tx:p.AtTx,AllowPreCommitted:false,SkipIntegrityCheck:false});if err!=nil{return nil,err}
  var output bytes.Buffer
  for {chunk,err:=stream.Recv();if err==io.EOF{break};if err!=nil{return nil,err};output.Write(chunk.Content);if output.Len()>16_000_000{return nil,fmt.Errorf("transaction export bound")}}
  data:=output.Bytes();if err:=verifyExport(data,verified,p);err!=nil{return nil,err};sha:=sha256.Sum256(data)
  return map[string]any{"tx_id":p.AtTx,"export":data,"export_sha256":fmt.Sprintf("%x",sha),"verified_header":verified.Header,"raw_export_independently_verified":true,
   "replication_executed":false},nil
 default:return nil,fmt.Errorf("immudb method denied")
 }
 wire,err:=client.ServiceClient.VerifiableGet(ctx,&schema.VerifiableGetRequest{ProveSinceTx:before.TxId,KeyRequest:&schema.KeyRequest{Key:p.Key,AtTx:p.AtTx}});if err!=nil{return nil,err}
 after,err:=c.verify(ctx,client.ServiceClient,p,wire);if err!=nil{return nil,err}
 proof,err:=proto.Marshal(wire);if err!=nil{return nil,err};anchor,err:=proto.Marshal(after);if err!=nil{return nil,err}
 return map[string]any{"verified":true,"tx_id":wire.Entry.Tx,"anchor":anchor,"proof":proof,"server_uuid":uuid,"database":c.cfg.Database,
  "verified_by":"immudb official inclusion/dual/linear-advance/state-signature"},nil
}
func(c *immuClient)Close(){}

// Native ExportTx codec, restricted to this provider's one-entry audit
// transactions. No Replica/ReplicateTx call is made and no general DB restore
// is claimed. Header and value are checked against SDK VerifiedTxByID.
func verifyExport(raw []byte,verified *schema.Tx,p immuPayload)error{
 if verified.Header==nil||verified.Header.Nentries!=1||len(verified.Entries)!=1{return fmt.Errorf("only one-entry immutable audit transaction export supported")}
 offset:=0
 take:=func(n int)([]byte,error){if n<0||offset+n>len(raw){return nil,fmt.Errorf("export codec bounds")};value:=raw[offset:offset+n];offset+=n;return value,nil}
 length,err:=take(4);if err!=nil{return err};headerBytes,err:=take(int(binary.BigEndian.Uint32(length)));if err!=nil{return err}
 header:=&store.TxHeader{};if err:=header.ReadFrom(headerBytes);err!=nil{return err}
 if header.ID!=p.AtTx||header.Alh()!=schema.TxFromProto(verified).Header().Alh(){return denied{"EXPORTED_HEADER_DENIED",nil}}
 keyLength,err:=take(2);if err!=nil{return err};key,err:=take(int(binary.BigEndian.Uint16(keyLength)));if err!=nil{return err}
 if !bytes.Equal(key,database.EncodeKey(p.Key))||!bytes.Equal(key,verified.Entries[0].Key){return denied{"EXPORTED_KEY_DENIED",nil}}
 mdLength,err:=take(2);if err!=nil{return err};md,err:=take(int(binary.BigEndian.Uint16(mdLength)));if err!=nil{return err}
 metadata:=schema.KVMetadataFromProto(verified.Entries[0].Metadata);expectedMD:=[]byte{};if metadata!=nil{expectedMD=metadata.Bytes()}
 if !bytes.Equal(md,expectedMD){return denied{"EXPORTED_METADATA_DENIED",nil}}
 valueLength,err:=take(4);if err!=nil{return err};value,err:=take(int(binary.BigEndian.Uint32(valueLength)));if err!=nil{return err};hash:=sha256.Sum256(value)
 if !bytes.Equal(value,p.Value)||!bytes.Equal(hash[:],verified.Entries[0].HValue){return denied{"EXPORTED_VALUE_HASH_DENIED",nil}}
 flagLength,err:=take(2);if err!=nil{return err};flag,err:=take(int(binary.BigEndian.Uint16(flagLength)));if err!=nil{return err}
 if offset!=len(raw)||len(flag)!=1||flag[0]!=0{return denied{"EXPORTED_TRUNCATED_OR_EXTRA_DATA",nil}}
 return nil
}
