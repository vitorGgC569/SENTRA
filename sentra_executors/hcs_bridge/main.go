//go:build windows

// Owned SENTRA helper, using hcsshim PUBLIC exported v1 APIs only.
package main

import (
    "bufio"
    "encoding/json"
    "fmt"
    "io"
    "os"
    "sync"
    "strings"
    "time"
    hcs "github.com/Microsoft/hcsshim"
)

type request struct {
    Action string `json:"action"`
    ID string `json:"id"`
    Owner string `json:"owner"`
    Config hcs.ContainerConfig `json:"config"`
    Command *hcs.ProcessConfig `json:"command"`
    TimeoutMS int `json:"timeout_ms"`
    ExpectedIdentity string `json:"expected_identity"`
}
var input=bufio.NewReader(os.Stdin)
func emit(v any) {b,_:=json.Marshal(v);fmt.Println(string(b))}
func checkpoint() error {
    emit(map[string]any{"event":"checkpoint","phase":"hcs"})
    line,err:=input.ReadString('\n');if err!=nil||strings.TrimSpace(line)!="CONTINUE" {return fmt.Errorf("checkpoint denied")};return nil
}
type bounded struct {data []byte; truncated bool}
func (b *bounded) Write(p []byte)(int,error) {
    n:=len(p);remain:=65536-len(b.data);if remain<n {b.truncated=true;p=p[:remain]};b.data=append(b.data,p...);return n,nil
}
func execute(r request)(map[string]any,error) {
    if r.TimeoutMS<1||r.TimeoutMS>115000||r.ID==""||r.Owner=="" {return nil,fmt.Errorf("invalid native profile")}
    if err:=checkpoint();err!=nil{return nil,err}
    properties,err:=hcs.GetContainers(hcs.ComputeSystemQuery{IDs:[]string{r.ID}});if err!=nil{return nil,err}
    var c hcs.Container
    if r.Action=="create" {
        if len(properties)!=0||r.Config.Owner!=r.Owner||!r.Config.HvPartition||r.Config.SystemType!="Container" {return nil,fmt.Errorf("compute system exists or profile invalid")}
        if err=checkpoint();err!=nil{return nil,err};c,err=hcs.CreateContainer(r.ID,&r.Config)
    } else {
        if len(properties)!=1||properties[0].ID!=r.ID||properties[0].Owner!=r.Owner {return nil,fmt.Errorf("HCS native owner mismatch")}
        identity:=fmt.Sprintf("%v|%s",properties[0].RuntimeID,properties[0].SiloGUID)
        if properties[0].SiloGUID==""&&strings.Trim(fmt.Sprint(properties[0].RuntimeID),"0-{} ")=="" {return nil,fmt.Errorf("HCS stable resource identity unavailable")}
        if r.ExpectedIdentity!=""&&r.ExpectedIdentity!=identity{return nil,fmt.Errorf("HCS resource identity replaced")}
        if r.Action=="status" {return map[string]any{"properties":properties[0],"owner_checked":true,"native_identity":identity},nil}
        if r.ExpectedIdentity==""{return nil,fmt.Errorf("HCS identity must be observed before mutation")}
        if err=checkpoint();err!=nil{return nil,err};c,err=hcs.OpenContainer(r.ID)
    }
    if err!=nil{return nil,err};defer c.Close()
    if r.Action=="create" {
        if err=checkpoint();err!=nil{return nil,err}
        list,e:=hcs.GetContainers(hcs.ComputeSystemQuery{IDs:[]string{r.ID}})
        if e!=nil{return nil,e};if len(list)!=1||list[0].Owner!=r.Owner{return nil,fmt.Errorf("HCS create ownership postcondition failed")}
        identity:=fmt.Sprintf("%v|%s",list[0].RuntimeID,list[0].SiloGUID)
        if list[0].SiloGUID==""&&strings.Trim(fmt.Sprint(list[0].RuntimeID),"0-{} ")=="" {return nil,fmt.Errorf("HCS stable resource identity unavailable")}
        return map[string]any{"created":true,"id":r.ID,"native_identity":identity},nil
    }
    if err=checkpoint();err!=nil{return nil,err}
    switch r.Action {
    case "start":err=c.Start()
    case "shutdown","terminate":
        if r.Action=="shutdown" {err=c.Shutdown()} else {err=c.Terminate()}
        if err!=nil&&!hcs.IsPending(err) {return nil,err}
        if err=checkpoint();err!=nil{return nil,err};err=c.WaitTimeout(time.Duration(r.TimeoutMS)*time.Millisecond)
        if err==nil{return map[string]any{"termination_wait_completed":true,"descendant_cleanup_provider_reported":true},nil}
    case "run":
        if r.Command==nil{return nil,fmt.Errorf("bound command required")}
        p,e:=c.CreateProcess(r.Command);if e!=nil{return nil,e};defer p.Close()
        _,stdout,stderr,e:=p.Stdio();if e!=nil{_ = p.Kill();return nil,e}
        out,errors:=&bounded{},&bounded{};var wg sync.WaitGroup
        for _,pair:=range []struct{reader io.ReadCloser;writer *bounded}{{stdout,out},{stderr,errors}} {
            wg.Add(1);go func(reader io.ReadCloser,writer *bounded){defer wg.Done();defer reader.Close();_,_ = io.Copy(writer,reader)}(pair.reader,pair.writer)
        }
        if e=checkpoint();e==nil {e=p.WaitTimeout(time.Duration(r.TimeoutMS)*time.Millisecond)}
        if e!=nil{_ = p.Kill();_ = p.WaitTimeout(3*time.Second);_ = stdout.Close();_ = stderr.Close();wg.Wait();return nil,e}
        code,e:=p.ExitCode();done:=make(chan struct{});go func(){wg.Wait();close(done)}()
        complete:=true
        select {case <-done:case <-time.After(time.Second):complete=false;_ = stdout.Close();_ = stderr.Close();<-done}
        if e!=nil{return nil,e}
        return map[string]any{"pid":p.Pid(),"exit_code":code,"stdout":string(out.data),"stderr":string(errors.data),
                              "stdout_truncated":out.truncated,"stderr_truncated":errors.truncated,"streams_completed":complete},nil
    default:return nil,fmt.Errorf("unsupported HCS action")
    }
    if err!=nil{return nil,err};return map[string]any{"action":r.Action,"native_call_completed":true},nil
}
func main() {
    line,err:=input.ReadString('\n');if err!=nil||len(line)>65536{emit(map[string]any{"event":"result","ok":false,"code":"hcs_request_limit"});return}
    var r request;if err=json.Unmarshal([]byte(line),&r);err!=nil{emit(map[string]any{"event":"result","ok":false,"code":"hcs_request_invalid"});return}
    result,err:=execute(r)
    if err!=nil{emit(map[string]any{"event":"result","ok":false,"code":"hcs_native_call_failed","uncertain":true,
        "evidence":map[string]any{"native_error_type":fmt.Sprintf("%T",err),"timeout":hcs.IsTimeout(err),"not_found":hcs.IsNotExist(err)}});return}
    emit(map[string]any{"event":"result","ok":true,"evidence":result})
}
