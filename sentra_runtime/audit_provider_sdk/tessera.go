package main

import (
 "bytes"
 "context"
 "encoding/base64"
 "fmt"
 "io"
 "net/http"
 "net/url"
 "strconv"
 "strings"
 "github.com/transparency-dev/formats/log"
 f_note "github.com/transparency-dev/formats/note"
 "github.com/transparency-dev/merkle/proof"
 "github.com/transparency-dev/merkle/rfc6962"
 "github.com/transparency-dev/tessera/api/layout"
 "github.com/transparency-dev/tessera/client"
 "golang.org/x/mod/sumdb/note"
)

type witnessPin struct {Key string `json:"key"`;URL string `json:"url"`}
type tesseraConfig struct {ReadURL string `json:"read_url"`;WriteURL string `json:"write_url"`;APIProfile string `json:"api_profile"`;Origin string `json:"origin"`;LogKey string `json:"log_key"`;Witnesses []witnessPin `json:"witnesses"`;Quorum int `json:"witness_quorum"`;TLS tlsPins `json:"tls"`;MaxLeaf int `json:"max_leaf_bytes"`}
type tesseraClient struct {cfg tesseraConfig;http *http.Client;fetch *client.HTTPFetcher;log note.Verifier;witness []note.Verifier;bearer string}
func newTessera(input initial)(provider,error){
 var cfg tesseraConfig;if err:=decode(input.Configuration,&cfg);err!=nil{return nil,err}
 if cfg.APIProfile!="tessera-conformance-add-tiles-v1"||cfg.Quorum<1||cfg.Quorum>len(cfg.Witnesses)||cfg.MaxLeaf<1||cfg.MaxLeaf>65535{return nil,fmt.Errorf("explicit real API/witness quorum required")}
 read,err:=url.Parse(cfg.ReadURL);if err!=nil||read.Scheme!="https"||read.User!=nil||read.Host==""||read.RawQuery!=""||read.Fragment!=""{return nil,fmt.Errorf("read TLS origin")}
 write,err:=url.Parse(cfg.WriteURL);if err!=nil||write.Scheme!="https"||write.User!=nil||write.Host!=read.Host||write.RawQuery!=""||write.Fragment!=""{return nil,fmt.Errorf("pinned same-origin write TLS required")}
 verifier,err:=note.NewVerifier(cfg.LogKey);if err!=nil {verifier,err=f_note.NewMLDSAVerifier(cfg.LogKey)};if err!=nil{return nil,err}
 witnesses:=[]note.Verifier{};seen:=map[string]bool{}
 logParts:=strings.SplitN(cfg.LogKey,"+",3);if len(logParts)!=3{return nil,fmt.Errorf("log verifier format")};logMaterial,err:=base64.StdEncoding.DecodeString(logParts[2]);if err!=nil||len(logMaterial)<2{return nil,fmt.Errorf("log verifier material")}
 seen[string(logMaterial[1:])]=true
 for _,pin:=range cfg.Witnesses{
  u,err:=url.Parse(pin.URL);if err!=nil||u.Scheme!="https"||u.User!=nil{return nil,fmt.Errorf("witness origin invalid")}
  v,err:=f_note.NewMLDSAVerifier(pin.Key);if err!=nil{v,err=f_note.NewVerifierForCosignatureV1(pin.Key)};if err!=nil{return nil,err}
  parts:=strings.SplitN(pin.Key,"+",3);if len(parts)!=3{return nil,fmt.Errorf("witness verifier format")};material,err:=base64.StdEncoding.DecodeString(parts[2]);if err!=nil||len(material)<2{return nil,fmt.Errorf("witness verifier material")}
  if seen[string(material[1:])]{return nil,fmt.Errorf("witness public keys must be distinct from each other and log")};seen[string(material[1:])]=true;witnesses=append(witnesses,v)
 }
 hc,err:=httpClient(cfg.TLS);if err!=nil{return nil,err};fetch,err:=client.NewHTTPFetcher(read,hc);if err!=nil{return nil,err}
 if input.Credentials["bearer"]!=""{fetch.SetAuthorizationHeader("Bearer "+input.Credentials["bearer"])}
 return &tesseraClient{cfg:cfg,http:hc,fetch:fetch,log:verifier,witness:witnesses,bearer:input.Credentials["bearer"]},nil
}
func(c *tesseraClient)checkpoint(raw []byte)(*log.Checkpoint,error){
 cp,_,_,err:=log.ParseCheckpoint(raw,c.cfg.Origin,c.log);if err!=nil{return nil,denied{"CHECKPOINT_LOG_SIGNATURE_DENIED",map[string]any{"checkpoint":raw}}}
 verifiers:=append([]note.Verifier{c.log},c.witness...);opened,err:=note.Open(raw,note.VerifierList(verifiers...));if err!=nil{return nil,denied{"CHECKPOINT_SIGNATURE_DENIED",map[string]any{"checkpoint":raw}}}
 valid:=map[string]bool{};for _,signature:=range opened.Sigs{valid[fmt.Sprintf("%s-%08x",signature.Name,signature.Hash)]=true}
 count:=0;for _,verifier:=range c.witness{if valid[fmt.Sprintf("%s-%08x",verifier.Name(),verifier.KeyHash())]{count++}}
 if count<c.cfg.Quorum{return nil,denied{"WITNESS_QUORUM_NOT_MET",map[string]any{"checkpoint":raw,"valid_witnesses":count,"required":c.cfg.Quorum}}}
 return cp,nil
}
type tesseraEvidence struct {Checkpoint []byte `json:"checkpoint"`;Previous []byte `json:"previous_checkpoint"`;Index uint64 `json:"index"`;Leaf []byte `json:"leaf"`;Inclusion [][]byte `json:"inclusion"`;Consistency [][]byte `json:"consistency"`}
type tesseraPayload struct {Leaf []byte `json:"leaf"`;Index uint64 `json:"index"`;Previous []byte `json:"previous_checkpoint"`;Evidence *tesseraEvidence `json:"evidence"`;StartIndex uint64 `json:"start_index"`;MaxScan uint64 `json:"max_scan"`}
func(c *tesseraClient)verify(e tesseraEvidence)(*log.Checkpoint,error){
 cp,err:=c.checkpoint(e.Checkpoint);if err!=nil{return nil,err}
 if e.Index>=cp.Size||len(e.Leaf)>c.cfg.MaxLeaf{return nil,denied{"CHECKPOINT_DOES_NOT_COMMIT_LEAF",e}}
 if err:=proof.VerifyInclusion(rfc6962.DefaultHasher,e.Index,cp.Size,rfc6962.DefaultHasher.HashLeaf(e.Leaf),e.Inclusion,cp.Hash);err!=nil{return nil,denied{"TESSERA_INCLUSION_DENIED",e}}
 if len(e.Previous)>0 {
  previous,err:=c.checkpoint(e.Previous);if err!=nil{return nil,err}
  if cp.Size<previous.Size||cp.Size==previous.Size&&!bytes.Equal(cp.Hash,previous.Hash){return nil,denied{"TESSERA_ROLLBACK_OR_SPLIT_VIEW",e}}
  if err:=proof.VerifyConsistency(rfc6962.DefaultHasher,previous.Size,cp.Size,e.Consistency,previous.Hash,cp.Hash);err!=nil{return nil,denied{"TESSERA_CONSISTENCY_DENIED",e}}
 }
 return cp,nil
}
func(c *tesseraClient)observe(ctx context.Context,p tesseraPayload)(any,error){
 raw,err:=c.fetch.ReadCheckpoint(ctx);if err!=nil{return nil,err};cp,err:=c.checkpoint(raw);if err!=nil{return nil,err}
 if p.Index>=cp.Size{return map[string]any{"status":"PENDING_INCLUSION","index":p.Index,"checkpoint_size":cp.Size},nil}
 builder,err:=client.NewProofBuilder(ctx,cp.Size,c.fetch.ReadTile);if err!=nil{return nil,err}
 inclusion,err:=builder.InclusionProof(ctx,p.Index);if err!=nil{return nil,err}
 var consistency [][]byte
 if len(p.Previous)>0 {previous,err:=c.checkpoint(p.Previous);if err!=nil{return nil,err};if cp.Size<previous.Size||cp.Size==previous.Size&&!bytes.Equal(cp.Hash,previous.Hash){return nil,denied{"TESSERA_ROLLBACK_OR_SPLIT_VIEW",map[string]any{"checkpoint":raw,"previous_checkpoint":p.Previous}}};consistency,err=builder.ConsistencyProof(ctx,previous.Size,cp.Size);if err!=nil{return nil,err}}
 bundle,err:=client.GetEntryBundle(ctx,c.fetch.ReadEntryBundle,p.Index/layout.EntryBundleWidth,cp.Size);if err!=nil{return nil,err}
 offset:=p.Index%layout.EntryBundleWidth;if offset>=uint64(len(bundle.Entries))||!bytes.Equal(bundle.Entries[offset],p.Leaf){return nil,denied{"TESSERA_LOG_ENTRY_BINDING_DENIED",map[string]any{"checkpoint":raw,"index":p.Index}}}
 evidence:=tesseraEvidence{raw,p.Previous,p.Index,p.Leaf,inclusion,consistency};verified,err:=c.verify(evidence);if err!=nil{return nil,err}
 return map[string]any{"status":"VERIFIED","index":p.Index,"tree_size":verified.Size,"root_hash":verified.Hash,"evidence":evidence,"verified_by":"Tessera tiles + official RFC6962 proof + signed note/witness quorum","witness_quorum":c.cfg.Quorum},nil
}
func(c *tesseraClient)Call(ctx context.Context,request command)(any,error){
 var p tesseraPayload;if err:=decode(request.Payload,&p);err!=nil{return nil,err}
 switch request.Method {
 case "verify_checkpoint":
  cp,err:=c.checkpoint(p.Previous);if err!=nil{return nil,err};return map[string]any{"verified":true,"tree_size":cp.Size,"root_hash":cp.Hash},nil
 case "status":raw,err:=c.fetch.ReadCheckpoint(ctx);if err!=nil{return nil,err};cp,err:=c.checkpoint(raw);if err!=nil{return nil,err};return map[string]any{"verified_checkpoint":raw,"tree_size":cp.Size,"root_hash":cp.Hash,"witness_quorum":c.cfg.Quorum},nil
 case "verify_offline":if p.Evidence==nil{return nil,fmt.Errorf("raw retained proof required")};cp,err:=c.verify(*p.Evidence);if err!=nil{return nil,err};return map[string]any{"verified":true,"tree_size":cp.Size,"root_hash":cp.Hash,"offline":true},nil
 case "observe":return c.observe(ctx,p)
 case "find":
  if p.MaxScan<1||p.MaxScan>4096{return nil,fmt.Errorf("bounded reconciliation scan required")}
  raw,err:=c.fetch.ReadCheckpoint(ctx);if err!=nil{return nil,err};cp,err:=c.checkpoint(raw);if err!=nil{return nil,err}
  end:=min(cp.Size,p.StartIndex+p.MaxScan)
  for index:=p.StartIndex;index<end; {
   bundle,err:=client.GetEntryBundle(ctx,c.fetch.ReadEntryBundle,index/layout.EntryBundleWidth,cp.Size);if err!=nil{return nil,err}
   if index%layout.EntryBundleWidth>=uint64(len(bundle.Entries)){return nil,denied{"TESSERA_ENTRY_BUNDLE_TRUNCATED",map[string]any{"checkpoint":raw,"index":index}}}
   for offset:=index%layout.EntryBundleWidth;offset<uint64(len(bundle.Entries))&&index<end;offset++ {
    if bytes.Equal(bundle.Entries[offset],p.Leaf){p.Index=index;return c.observe(ctx,p)};index++
   }
  }
  return map[string]any{"status":"UNCERTAIN","scan_end":end,"checkpoint_size":cp.Size,"append_repeated":false},nil
 case "publish":
  if len(p.Leaf)>c.cfg.MaxLeaf{return nil,fmt.Errorf("audit leaf bound")}
  request,err:=http.NewRequestWithContext(ctx,http.MethodPost,strings.TrimRight(c.cfg.WriteURL,"/")+"/add",bytes.NewReader(p.Leaf));if err!=nil{return nil,err}
  request.Header.Set("Content-Type","application/octet-stream");if c.bearer!=""{request.Header.Set("Authorization","Bearer "+c.bearer)}
  response,err:=c.http.Do(request);if err!=nil{return nil,err};defer response.Body.Close();data,err:=io.ReadAll(io.LimitReader(response.Body,129));if err!=nil||response.StatusCode!=http.StatusOK||len(data)>128{return nil,fmt.Errorf("real Tessera add response unavailable")}
  index,err:=strconv.ParseUint(string(data),10,64);if err!=nil{return nil,err}
  // Preserve the commit reference before separate checkpoint/proof polling.
  return map[string]any{"status":"PENDING_INCLUSION","index":index,"append_ack":"Tessera conformance POST /add decimal index","cryptographic_inclusion_verified":false},nil
 }
 return nil,fmt.Errorf("Tessera method denied")
}
func(c *tesseraClient)Close(){c.http.CloseIdleConnections()}
