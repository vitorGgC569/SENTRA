//go:build windows

package main

import (
 "fmt"
 "strings"
 "github.com/Microsoft/go-winio"
 "github.com/spiffe/go-spiffe/v2/workloadapi"
 "google.golang.org/grpc"
 "google.golang.org/grpc/credentials/insecure"
)

// Matches SPIRE pkg/common/util/addr_windows.go. Local named pipe only.
func transports(endpoint string) (workloadapi.ClientOption, *grpc.ClientConn, error) {
 if endpoint=="" || strings.Contains(endpoint, "..") || strings.ContainsAny(endpoint, "\x00:\r\n") || strings.HasPrefix(endpoint, `\\`) {
  return nil,nil,fmt.Errorf("local pipe name required")
 }
 target := `passthrough:\\.\pipe\`+strings.TrimLeft(endpoint, `\`)
 conn,err:=grpc.NewClient(target,grpc.WithTransportCredentials(insecure.NewCredentials()),grpc.WithContextDialer(winio.DialPipeContext))
 return workloadapi.WithNamedPipeName(endpoint),conn,err
}
