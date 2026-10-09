// Client bridge only. Never a NATS/Tessera/immudb-compatible server.
package main

import (
 "bufio"
 "bytes"
 "context"
 "crypto/sha256"
 "crypto/tls"
 "crypto/x509"
 "encoding/hex"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "net/http"
 "os"
 "time"
)

type initial struct { Version int `json:"version"`;Provider string `json:"provider"`;Configuration json.RawMessage `json:"configuration"`;Credentials map[string]string `json:"credentials"` }
type command struct {ID string `json:"id"`;Method string `json:"method"`;Payload json.RawMessage `json:"payload"`}
type tlsPins struct {
 CAFile string `json:"ca_file"`; CASHA256 string `json:"ca_sha256"`; ServerName string `json:"server_name"`; SPKI string `json:"spki_sha256"`
 CertFile string `json:"certificate_file"`;CertSHA256 string `json:"certificate_sha256"`;KeyFile string `json:"key_file"`;KeySHA256 string `json:"key_sha256"`
}
type denied struct {Code string;Evidence any}
func(d denied)Error()string{return d.Code}
func decode(raw []byte,value any)error {d:=json.NewDecoder(bytes.NewReader(raw));d.DisallowUnknownFields();return d.Decode(value)}
func send(value any){if err:=json.NewEncoder(os.Stdout).Encode(value);err!=nil {os.Exit(2)}}
func filePin(path,want string)([]byte,error){
 info,err:=os.Lstat(path);if err!=nil || !info.Mode().IsRegular() {return nil,fmt.Errorf("pinned file absent")}
 if info.Size()>16_000_000 {return nil,fmt.Errorf("pinned file too large")}
 raw,err:=os.ReadFile(path);if err!=nil{return nil,err};sha:=sha256.Sum256(raw)
 if hex.EncodeToString(sha[:])!=want{return nil,fmt.Errorf("file pin mismatch")};return raw,nil
}
func secureTLS(p tlsPins)(*tls.Config,error){
 raw,err:=filePin(p.CAFile,p.CASHA256);if err!=nil{return nil,err}
 roots:=x509.NewCertPool();if !roots.AppendCertsFromPEM(raw)||p.ServerName==""||len(p.SPKI)!=64{return nil,fmt.Errorf("TLS pins missing")}
 config:=&tls.Config{RootCAs:roots,ServerName:p.ServerName,MinVersion:tls.VersionTLS12}
 config.VerifyConnection=func(state tls.ConnectionState)error {
  if len(state.PeerCertificates)==0{return fmt.Errorf("TLS peer absent")};hash:=sha256.Sum256(state.PeerCertificates[0].RawSubjectPublicKeyInfo)
  if hex.EncodeToString(hash[:])!=p.SPKI{return fmt.Errorf("TLS SPKI mismatch")};return nil
 }
 if p.CertFile!=""||p.KeyFile!="" {
  cert,err:=filePin(p.CertFile,p.CertSHA256);if err!=nil{return nil,err};key,err:=filePin(p.KeyFile,p.KeySHA256);if err!=nil{return nil,err}
  pair,err:=tls.X509KeyPair(cert,key);if err!=nil{return nil,err};config.Certificates=[]tls.Certificate{pair}
 }
 return config,nil
}
type boundedTransport struct{base http.RoundTripper}
func(t boundedTransport)RoundTrip(r *http.Request)(*http.Response,error){
 response,err:=t.base.RoundTrip(r);if err!=nil{return nil,err}
 raw,err:=io.ReadAll(io.LimitReader(response.Body,8_000_001));response.Body.Close()
 if err!=nil||len(raw)>8_000_000{return nil,fmt.Errorf("HTTP resource bound")};response.Body=io.NopCloser(bytes.NewReader(raw));return response,nil
}
func httpClient(p tlsPins)(*http.Client,error){
 tlsConfig,err:=secureTLS(p);if err!=nil{return nil,err}
 transport:=&http.Transport{TLSClientConfig:tlsConfig,Proxy:nil}
 return &http.Client{Transport:boundedTransport{transport},Timeout:15*time.Second,CheckRedirect:func(r *http.Request,v []*http.Request)error{return fmt.Errorf("redirect denied")}},nil
}
type provider interface{Call(context.Context,command)(any,error);Close()}
func main(){
 scanner:=bufio.NewScanner(os.Stdin);scanner.Buffer(make([]byte,4096),32_000_000)
 if !scanner.Scan(){return};var config initial
 if err:=decode(scanner.Bytes(),&config);err!=nil||config.Version!=1 {send(map[string]any{"type":"error","code":"INVALID_HOST_PROFILE"});return}
 ctx,cancel:=context.WithCancel(context.Background());defer cancel()
 var client provider;var err error
 switch config.Provider {case "nats":client,err=newNATS(config);case "immudb":client,err=newImmu(config);case "tessera":client,err=newTessera(config);default:err=fmt.Errorf("provider unsupported")}
 if err!=nil {send(map[string]any{"type":"error","code":"REAL_PROVIDER_INITIALIZATION_UNAVAILABLE"});return};defer client.Close()
 send(map[string]any{"type":"ready"})
 for scanner.Scan(){
  var request command;if err:=decode(scanner.Bytes(),&request);err!=nil||request.ID=="" {send(map[string]any{"type":"error","code":"INVALID_REQUEST"});return}
  call,cancel:=context.WithTimeout(ctx,20*time.Second);value,err:=client.Call(call,request);cancel()
  if err!=nil {var proofDenied denied;if errors.As(err,&proofDenied){send(map[string]any{"id":request.ID,"type":"proof_denied","code":proofDenied.Code,"evidence":proofDenied.Evidence})}else{send(map[string]any{"id":request.ID,"type":"error","code":"PROVIDER_COMPLETION_UNKNOWN"})};continue}
  send(map[string]any{"id":request.ID,"type":"result","result":value})
 }
}
