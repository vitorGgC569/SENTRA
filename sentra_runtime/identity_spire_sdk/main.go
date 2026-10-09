// Real SPIFFE Workload API client, not a service or an attestation proxy.
// The agent attests THIS owned process from socket/pipe peer credentials.
package main

import (
 "bytes"
 "bufio"
 "context"
 "crypto/x509"
 "encoding/json"
 "fmt"
 "os"
 "sync"
 "time"
 "github.com/spiffe/go-spiffe/v2/proto/spiffe/workload"
 "github.com/spiffe/go-spiffe/v2/svid/x509svid"
 "github.com/spiffe/go-spiffe/v2/workloadapi"
 "google.golang.org/grpc/metadata"
)

type config struct {
 Version int `json:"version"`
 Endpoint string `json:"endpoint"`
 ExpectedIDs []string `json:"expected_ids"`
 Audiences []string `json:"audiences"`
 MaxTTL int64 `json:"max_ttl_seconds"`
}
type command struct { ID string `json:"id"`; Method string `json:"method"`; SPIFFEID string `json:"spiffe_id"`; Audience string `json:"audience"` }
var outputMu sync.Mutex
func emit(value any) { outputMu.Lock();defer outputMu.Unlock(); if err:=json.NewEncoder(os.Stdout).Encode(value);err!=nil {os.Exit(2)} }
func failure(id string, code string) { emit(map[string]any{"type":"error","id":id,"code":code}) }
func contains(values []string,value string) bool {for _,v:=range values {if v==value{return true}};return false}

type watcher struct { cfg config }
func (w *watcher) OnX509ContextWatchError(err error) { emit(map[string]any{"type":"watch_error","stream":"x509","code":"WORKLOAD_UNAVAILABLE"}) }
func (w *watcher) OnX509ContextUpdate(update *workloadapi.X509Context) {
 identities:=[]map[string]any{}
 bundles:=map[string][][]byte{}
 for _,bundle:=range update.Bundles.Bundles() {
  certificates:=[][]byte{}
  for _,cert:=range bundle.X509Authorities() {certificates=append(certificates,cert.Raw)}
  bundles[bundle.TrustDomain().Name()]=certificates
 }
 for _,svid:=range update.SVIDs {
  if !contains(w.cfg.ExpectedIDs,svid.ID.String()) {continue}
  id,chains,err:=x509svid.Verify(svid.Certificates,update.Bundles)
  if err!=nil || id!=svid.ID || len(svid.Certificates)==0 {failure("","X509_VERIFICATION_FAILED");return}
  leaf:=svid.Certificates[0]
  verificationExpiry:=leaf.NotAfter.Unix()
  if len(chains)==0 {failure("","X509_CHAIN_UNAVAILABLE");return}
  // A valid credential cannot outlive the verified intermediate/root path.
  for _,cert:=range chains[0] {if cert.NotAfter.Unix()<verificationExpiry {verificationExpiry=cert.NotAfter.Unix()}}
  if int64(leaf.NotAfter.Sub(leaf.NotBefore).Seconds())>w.cfg.MaxTTL || !time.Now().Before(leaf.NotAfter) {failure("","X509_TTL_DENIED");return}
  key,err:=x509.MarshalPKCS8PrivateKey(svid.PrivateKey)
  if err!=nil {failure("","X509_KEY_UNAVAILABLE");return}
  chain:=[][]byte{}
  for _,cert:=range svid.Certificates {chain=append(chain,cert.Raw)}
  identities=append(identities,map[string]any{"spiffe_id":svid.ID.String(),"expires_at":leaf.NotAfter.Unix(),"verification_expires_at":verificationExpiry,"not_before":leaf.NotBefore.Unix(),
   "certificates":chain,"private_key_pkcs8":key,"verified_by":"go-spiffe.x509svid.Verify"})
 }
 emit(map[string]any{"type":"x509_context","identities":identities,"bundles":bundles})
}

func watchJWT(ctx context.Context, client workload.SpiffeWorkloadAPIClient) {
 for ctx.Err()==nil {
  watchJWTStream(ctx,client)
  select {case <-ctx.Done(): return; case <-time.After(2*time.Second):}
 }
}
func watchJWTStream(ctx context.Context, client workload.SpiffeWorkloadAPIClient) {
 stream,err:=client.FetchJWTBundles(ctx,&workload.JWTBundlesRequest{})
 if err!=nil {emit(map[string]any{"type":"watch_error","stream":"jwt_bundles","code":"WORKLOAD_UNAVAILABLE"});return}
 for {
  response,err:=stream.Recv()
  if err!=nil {emit(map[string]any{"type":"watch_error","stream":"jwt_bundles","code":"WORKLOAD_UNAVAILABLE"});return}
  emit(map[string]any{"type":"jwt_bundles","bundles":response.Bundles})
 }
}

func fetchJWT(ctx context.Context,client workload.SpiffeWorkloadAPIClient,cfg config,request command) {
 if !contains(cfg.ExpectedIDs,request.SPIFFEID) || !contains(cfg.Audiences,request.Audience) {failure(request.ID,"JWT_SCOPE_DENIED");return}
 call,cancel:=context.WithTimeout(ctx,5*time.Second);defer cancel()
 response,err:=client.FetchJWTSVID(call,&workload.JWTSVIDRequest{Audience:[]string{request.Audience},SpiffeId:request.SPIFFEID})
 if err!=nil {failure(request.ID,"JWT_FETCH_UNAVAILABLE");return}
 for _,svid:=range response.Svids {
  if svid.SpiffeId!=request.SPIFFEID {continue}
  verified,err:=client.ValidateJWTSVID(call,&workload.ValidateJWTSVIDRequest{Audience:request.Audience,Svid:svid.Svid})
  if err!=nil || verified.SpiffeId!=request.SPIFFEID {failure(request.ID,"JWT_VERIFICATION_FAILED");return}
  claims:=verified.Claims.AsMap()
  expiry,ok:=claims["exp"].(float64)
  if !ok || expiry<=float64(time.Now().Unix()) || expiry-float64(time.Now().Unix())>float64(cfg.MaxTTL) {failure(request.ID,"JWT_TTL_DENIED");return}
  emit(map[string]any{"type":"jwt_svid","id":request.ID,"spiffe_id":svid.SpiffeId,"audience":request.Audience,"expires_at":int64(expiry),
    "token":svid.Svid,"verified_by":"SPIRE.ValidateJWTSVID"})
  return
 }
 failure(request.ID,"JWT_IDENTITY_NOT_ISSUED")
}

func main() {
 scanner:=bufio.NewScanner(os.Stdin); scanner.Buffer(make([]byte,4096),1_000_000)
 if !scanner.Scan() {return}
 var cfg config
 decoder:=json.NewDecoder(bytes.NewReader(scanner.Bytes()));decoder.DisallowUnknownFields()
 if err:=decoder.Decode(&cfg);err!=nil || cfg.Version!=1 || len(cfg.ExpectedIDs)==0 || cfg.MaxTTL<30 || cfg.MaxTTL>86400 {failure("","INVALID_HOST_CONFIG");return}
 option,conn,err:=transports(cfg.Endpoint)
 if err!=nil {failure("","WORKLOAD_TRANSPORT_UNAVAILABLE");return};defer conn.Close()
 ctx,cancel:=context.WithCancel(context.Background());defer cancel()
 rawctx:=metadata.NewOutgoingContext(ctx,metadata.Pairs("workload.spiffe.io","true"))
 client:=workload.NewSpiffeWorkloadAPIClient(conn)
 go func(){if err:=workloadapi.WatchX509Context(ctx,&watcher{cfg:cfg},option);err!=nil {emit(map[string]any{"type":"watch_error","stream":"x509","code":"WORKLOAD_UNAVAILABLE"})}}()
 go watchJWT(rawctx,client)
 for scanner.Scan() {
  var request command
  decoder:=json.NewDecoder(bytes.NewReader(scanner.Bytes()));decoder.DisallowUnknownFields()
  decoderErr:=decoder.Decode(&request)
  if decoderErr!=nil || request.ID=="" {failure("","INVALID_COMMAND");continue}
  if request.Method=="close" {return}
  if request.Method!="fetch_jwt" {failure(request.ID,"METHOD_DENIED");continue}
  fetchJWT(rawctx,client,cfg,request)
 }
 if scanner.Err()!=nil {fmt.Fprintln(os.Stderr,"bounded IPC input unavailable")}
}
