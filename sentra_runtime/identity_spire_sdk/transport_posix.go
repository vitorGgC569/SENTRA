//go:build !windows

package main

import (
 "fmt"
 "path/filepath"
 "github.com/spiffe/go-spiffe/v2/workloadapi"
 "google.golang.org/grpc"
 "google.golang.org/grpc/credentials/insecure"
)

func transports(endpoint string) (workloadapi.ClientOption, *grpc.ClientConn, error) {
 if !filepath.IsAbs(endpoint) { return nil,nil,fmt.Errorf("absolute Unix socket required") }
 target:="unix://"+endpoint
 conn,err:=grpc.NewClient(target,grpc.WithTransportCredentials(insecure.NewCredentials()))
 return workloadapi.WithAddr(target),conn,err
}
