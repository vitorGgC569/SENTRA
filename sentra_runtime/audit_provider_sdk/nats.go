package main

import (
 "context"
 "encoding/json"
 "errors"
 "fmt"
 "strings"
 "time"
 nats "github.com/nats-io/nats.go"
)
type natsConfig struct {
 Server string `json:"server"`;Stream string `json:"stream"`;Consumer string `json:"consumer"`;Owner string `json:"owner"`;Workspace string `json:"workspace_id"`
 TLS tlsPins `json:"tls"`;Channel string `json:"channel"`;Domain string `json:"domain"`;Prefix string `json:"subject_prefix"`
 MaxMessages int64 `json:"max_messages"`;MaxBytes int64 `json:"max_bytes"`;MaxAge int64 `json:"max_age_seconds"`;DuplicateWindow int64 `json:"duplicate_window_seconds"`
 MaxAckPending int `json:"max_ack_pending"`;MaxDeliver int `json:"max_deliver"`;Backoff []float64 `json:"backoff_seconds"`;Batch int `json:"batch"`;MaxPayload int32 `json:"max_payload_bytes"`;Replicas int `json:"replicas"`
 MaxConsumers int `json:"max_consumers"`
 StartSeq *uint64 `json:"replay_from_sequence"`;StartTime *string `json:"replay_from_time"`
}
type natsClient struct {cfg natsConfig;conn *nats.Conn;js nats.JetStreamContext;sub *nats.Subscription;pending map[string]*nats.Msg;counter uint64}
func newNATS(input initial)(provider,error){
 var cfg natsConfig;if err:=decode(input.Configuration,&cfg);err!=nil{return nil,err}
 if !strings.HasPrefix(cfg.Server,"tls://")||!strings.HasPrefix(cfg.Prefix,"sentra.")||strings.ContainsAny(cfg.Prefix,"*> ") {return nil,fmt.Errorf("scope/TLS missing")}
 if cfg.Batch<1||cfg.Batch>cfg.MaxAckPending||cfg.MaxAckPending>1000||cfg.MaxDeliver<1||cfg.MaxDeliver>100||len(cfg.Backoff)==0||len(cfg.Backoff)>cfg.MaxDeliver||cfg.MaxPayload<1024||cfg.MaxPayload>1_000_000{return nil,fmt.Errorf("JetStream profile bounds")}
 tlsConfig,err:=secureTLS(cfg.TLS);if err!=nil{return nil,err}
 opts:=[]nats.Option{nats.Secure(tlsConfig),nats.Name("SENTRA scoped notifications"),nats.Timeout(5*time.Second),nats.MaxReconnects(0),nats.IgnoreDiscoveredServers()}
 creds:=input.Credentials
 if creds["token"]!="" {opts=append(opts,nats.Token(creds["token"]))} else if creds["username"]!="" {opts=append(opts,nats.UserInfo(creds["username"],creds["password"]))} else if creds["credentials_file"]!="" {
  if _,err:=filePin(creds["credentials_file"],creds["credentials_sha256"]);err!=nil{return nil,err};opts=append(opts,nats.UserCredentials(creds["credentials_file"]))
 } else if len(tlsConfig.Certificates)==0 {return nil,fmt.Errorf("authenticated NATS credentials required")}
 conn,err:=nats.Connect(cfg.Server,opts...);if err!=nil{return nil,err}
 jsOpts:=[]nats.JSOpt{nats.MaxWait(10*time.Second)};if cfg.Domain!=""{jsOpts=append(jsOpts,nats.Domain(cfg.Domain))}
 js,err:=conn.JetStream(jsOpts...);if err!=nil{conn.Close();return nil,err}
 return &natsClient{cfg:cfg,conn:conn,js:js,pending:map[string]*nats.Msg{}},nil
}
func(c *natsClient)streamConfig()*nats.StreamConfig {
 return &nats.StreamConfig{Name:c.cfg.Stream,Subjects:[]string{c.cfg.Prefix+".>"},Storage:nats.FileStorage,Retention:nats.LimitsPolicy,
  Discard:nats.DiscardNew,MaxMsgs:c.cfg.MaxMessages,MaxBytes:c.cfg.MaxBytes,MaxAge:time.Duration(c.cfg.MaxAge)*time.Second,
  Duplicates:time.Duration(c.cfg.DuplicateWindow)*time.Second,MaxMsgSize:c.cfg.MaxPayload,Replicas:c.cfg.Replicas,MaxMsgsPerSubject:1,MaxConsumers:c.cfg.MaxConsumers}
}
func(c *natsClient)consumerConfig()(*nats.ConsumerConfig,error){
 backoff:=[]time.Duration{};for _,delay:=range c.cfg.Backoff{backoff=append(backoff,time.Duration(delay*float64(time.Second)))}
 config:=&nats.ConsumerConfig{Durable:c.cfg.Consumer,AckPolicy:nats.AckExplicitPolicy,AckWait:time.Duration(c.cfg.Backoff[0]*float64(time.Second)),MaxDeliver:c.cfg.MaxDeliver,
  BackOff:backoff,FilterSubject:c.cfg.Prefix+".>",MaxAckPending:c.cfg.MaxAckPending,MaxWaiting:1,MaxRequestBatch:c.cfg.Batch,MaxRequestExpires:5*time.Second,
  MaxRequestMaxBytes:int(c.cfg.MaxPayload)*c.cfg.Batch,DeliverPolicy:nats.DeliverAllPolicy,ReplayPolicy:nats.ReplayInstantPolicy,MemoryStorage:false}
 if c.cfg.StartSeq!=nil{config.DeliverPolicy=nats.DeliverByStartSequencePolicy;config.OptStartSeq=*c.cfg.StartSeq}
 if c.cfg.StartTime!=nil{start,err:=time.Parse(time.RFC3339Nano,*c.cfg.StartTime);if err!=nil{return nil,err};config.DeliverPolicy=nats.DeliverByStartTimePolicy;config.OptStartTime=&start}
 return config,nil
}
func(c *natsClient)checkResources()error{
 info,err:=c.js.StreamInfo(c.cfg.Stream);if err!=nil{return err};want:=c.streamConfig();got:=info.Config
 if got.Storage!=want.Storage||got.Retention!=want.Retention||got.MaxMsgs!=want.MaxMsgs||got.MaxBytes!=want.MaxBytes||got.MaxAge!=want.MaxAge||got.Duplicates!=want.Duplicates||
  got.Replicas!=want.Replicas||got.MaxConsumers!=want.MaxConsumers||got.MaxMsgSize!=want.MaxMsgSize||got.MaxMsgsPerSubject!=1||got.Discard!=nats.DiscardNew||got.NoAck||len(got.Subjects)!=1||got.Subjects[0]!=want.Subjects[0] {return fmt.Errorf("stream pin mismatch")}
 consumer,err:=c.js.ConsumerInfo(c.cfg.Stream,c.cfg.Consumer);if err!=nil{return err};cfg,err:=c.consumerConfig();if err!=nil{return err};actual:=consumer.Config
 if actual.AckPolicy!=cfg.AckPolicy||actual.MaxDeliver!=cfg.MaxDeliver||actual.MaxAckPending!=cfg.MaxAckPending||actual.FilterSubject!=cfg.FilterSubject||actual.DeliverSubject!=""||
  actual.DeliverPolicy!=cfg.DeliverPolicy||actual.OptStartSeq!=cfg.OptStartSeq||actual.MaxWaiting!=1||actual.MaxRequestBatch!=cfg.MaxRequestBatch||actual.MaxRequestExpires!=cfg.MaxRequestExpires||
  actual.MaxRequestMaxBytes!=cfg.MaxRequestMaxBytes||actual.AckWait!=cfg.AckWait||actual.ReplayPolicy!=cfg.ReplayPolicy||actual.MemoryStorage||len(actual.BackOff)!=len(cfg.BackOff){return fmt.Errorf("consumer pin mismatch")}
 for i:=range cfg.BackOff{if actual.BackOff[i]!=cfg.BackOff[i]{return fmt.Errorf("consumer backoff mismatch")}}
 if (actual.OptStartTime==nil)!=(cfg.OptStartTime==nil) || actual.OptStartTime!=nil&&!actual.OptStartTime.Equal(*cfg.OptStartTime){return fmt.Errorf("replay time mismatch")}
 return nil
}
func(c *natsClient)Call(ctx context.Context,request command)(any,error){
 var p struct{Subject string `json:"subject"`;MessageID string `json:"message_id"`;Body json.RawMessage `json:"body"`;Batch int `json:"batch"`;Handle string `json:"handle"`;Delay float64 `json:"delay_seconds"`}
 if err:=decode(request.Payload,&p);err!=nil{return nil,err}
 if request.Method=="configure"{
  if _,err:=c.js.StreamInfo(c.cfg.Stream);errors.Is(err,nats.ErrStreamNotFound){if _,err=c.js.AddStream(c.streamConfig());err!=nil{return nil,err}}else if err!=nil{return nil,err}
  if _,err:=c.js.ConsumerInfo(c.cfg.Stream,c.cfg.Consumer);errors.Is(err,nats.ErrConsumerNotFound){cfg,err:=c.consumerConfig();if err!=nil{return nil,err};if _,err=c.js.AddConsumer(c.cfg.Stream,cfg);err!=nil{return nil,err}}else if err!=nil{return nil,err}
  if err:=c.checkResources();err!=nil{return nil,err};return map[string]any{"configured":true,"changed_existing_resources":false},nil
 }
 if err:=c.checkResources();err!=nil{return nil,err}
 switch request.Method {
 case "status":
  stream,err:=c.js.StreamInfo(c.cfg.Stream);if err!=nil{return nil,err};consumer,err:=c.js.ConsumerInfo(c.cfg.Stream,c.cfg.Consumer);if err!=nil{return nil,err}
  return map[string]any{"connected":c.conn.IsConnected(),"stream":stream,"consumer":consumer,"owned_unacked_handles":len(c.pending),"effect_authority":false},nil
 case "publish":
  if !strings.HasPrefix(p.Subject,c.cfg.Prefix+".")||strings.ContainsAny(p.Subject,"*> ")||len(p.Body)>int(c.cfg.MaxPayload)||p.MessageID=="" {return nil,fmt.Errorf("publish scope/bound")}
  msg:=&nats.Msg{Subject:p.Subject,Data:p.Body,Header:nats.Header{}}
  msg.Header.Set("Nats-Msg-Id",p.MessageID);msg.Header.Set("Nats-Expected-Stream",c.cfg.Stream);msg.Header.Set("Nats-Expected-Last-Subject-Sequence","0")
  ack,err:=c.js.PublishMsg(msg,nats.Context(ctx));if err!=nil{return nil,err};return map[string]any{"stream":ack.Stream,"sequence":ack.Sequence,"duplicate":ack.Duplicate,"domain":ack.Domain},nil
 case "lookup":
  if !strings.HasPrefix(p.Subject,c.cfg.Prefix+"."){return nil,fmt.Errorf("lookup scope")}
  msg,err:=c.js.GetLastMsg(c.cfg.Stream,p.Subject);if errors.Is(err,nats.ErrMsgNotFound){return map[string]any{"found":false},nil};if err!=nil{return nil,err}
  return map[string]any{"found":true,"data":msg.Data,"message_id":msg.Header.Get("Nats-Msg-Id"),"sequence":msg.Sequence},nil
 case "pull":
  if p.Batch<1||p.Batch>c.cfg.Batch||len(c.pending)+p.Batch>c.cfg.MaxAckPending{return nil,fmt.Errorf("pull backpressure")}
  if c.sub==nil {sub,err:=c.js.PullSubscribe(c.cfg.Prefix+".>",c.cfg.Consumer,nats.Bind(c.cfg.Stream,c.cfg.Consumer));if err!=nil{return nil,err};c.sub=sub}
  messages,err:=c.sub.Fetch(p.Batch,nats.MaxWait(3*time.Second));if err!=nil&&!errors.Is(err,nats.ErrTimeout){return nil,err}
  result:=[]map[string]any{}
  for _,msg:=range messages{metadata,err:=msg.Metadata();if err!=nil{return nil,err};c.counter++;handle:=fmt.Sprint(c.counter);c.pending[handle]=msg
   result=append(result,map[string]any{"handle":handle,"subject":msg.Subject,"data":msg.Data,"stream_sequence":metadata.Sequence.Stream,"deliveries":metadata.NumDelivered})}
  return map[string]any{"messages":result},nil
 case "ack","nak","term","progress":
  msg,ok:=c.pending[p.Handle];if !ok{return nil,fmt.Errorf("delivery handle not owned")}
  var err error;confirmed:=false
  switch request.Method{case "ack":err=msg.AckSync(nats.Context(ctx));confirmed=err==nil;case "nak":if p.Delay<=0||p.Delay>86400{return nil,fmt.Errorf("NAK bound")};err=msg.NakWithDelay(time.Duration(p.Delay*float64(time.Second)));case "term":err=msg.Term();case "progress":err=msg.InProgress()}
  if err!=nil{return nil,err};if request.Method!="progress"{delete(c.pending,p.Handle)}
  return map[string]any{"sent":true,"broker_ack_confirmed":confirmed,"method":request.Method,"proves_core_effect":false},nil
 }
 return nil,fmt.Errorf("NATS method denied")
}
func(c *natsClient)Close(){if c.sub!=nil{c.sub.Unsubscribe()};c.conn.Close()}
