// corplink-vpn-helper: connects or disconnects CorpLink VPN via its local gRPC API.
// Must be ad-hoc code-signed so the gRPC server's getProcLeafCertificateSubject check passes.
//
// Usage:
//   corplink-vpn-helper status
//   corplink-vpn-helper connect
//   corplink-vpn-helper disconnect
//
// Exit codes: 0=success, 1=error, 2=already in desired state

package main

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"time"

	pb "corplink-vpn-helper/proto"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
)

const (
	grpcAddr = "127.0.0.1:31055"
	rpcConf  = "/usr/local/corplink/rpc.conf"
	tokenKey = "corplink-token"
	userKey  = "corplink-user"
	timeout  = 15 * time.Second
)

func loadToken() (string, error) {
	data, err := os.ReadFile(rpcConf)
	if err != nil {
		return "", fmt.Errorf("cannot read %s: %w", rpcConf, err)
	}
	s := string(data)
	for len(s) > 0 && (s[len(s)-1] == '\n' || s[len(s)-1] == '\r' || s[len(s)-1] == ' ') {
		s = s[:len(s)-1]
	}
	return s, nil
}

func currentUser() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return "unknown"
	}
	return url.QueryEscape(filepath.Base(home))
}

func isConnected(status pb.VpnStatus) bool {
	return status == pb.VpnStatus_Connected || status == pb.VpnStatus_Reasserting
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "usage: %s <status|connect|disconnect>\n", os.Args[0])
		os.Exit(1)
	}

	token, err := loadToken()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	conn, err := grpc.Dial(grpcAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		fmt.Fprintln(os.Stderr, "grpc dial:", err)
		os.Exit(1)
	}
	defer conn.Close()

	stub := pb.NewCorpLinkClient(conn)

	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	md := metadata.Pairs(tokenKey, token, userKey, currentUser())
	ctx = metadata.NewOutgoingContext(ctx, md)

	cmd := os.Args[1]

	// Get current VPN status
	statusResp, statusErr := stub.GetVpnStatus(ctx, &pb.EmptyRequest{})

	switch cmd {
	case "status":
		if statusErr != nil {
			fmt.Fprintln(os.Stderr, "getVpnStatus:", statusErr)
			os.Exit(1)
		}
		var statusStr string
		if statusResp.Data != nil {
			statusStr = statusResp.Data.Status.String()
		}
		connected := statusResp.Data != nil && isConnected(statusResp.Data.Status)
		fmt.Printf("connected=%v status=%s\n", connected, statusStr)

	case "connect":
		if statusErr == nil && statusResp.Data != nil && isConnected(statusResp.Data.Status) {
			fmt.Println("VPN already connected")
			os.Exit(2)
		}

		// Get VPN list
		listResp, err := stub.GetVpnList(ctx, &pb.EmptyRequest{})
		if err != nil {
			fmt.Fprintln(os.Stderr, "getVpnList:", err)
			os.Exit(1)
		}

		var serverID int32 = -1
		mode := pb.VpnMode_Split
		if len(listResp.SplitList) > 0 {
			serverID = listResp.SplitList[0].Id
			mode = pb.VpnMode_Split
		} else if len(listResp.FullList) > 0 {
			serverID = listResp.FullList[0].Id
			mode = pb.VpnMode_Full
		}

		resp, err := stub.ConnectVpn(ctx, &pb.ConnectVpnRequest{
			Server: serverID,
			Mode:   mode,
		})
		if err != nil {
			fmt.Fprintln(os.Stderr, "connectVpn:", err)
			os.Exit(1)
		}
		if resp.Code != 0 {
			fmt.Fprintf(os.Stderr, "connectVpn error %d: %s\n", resp.Code, resp.Message)
			os.Exit(1)
		}
		fmt.Printf("VPN connecting (server=%d mode=%s)\n", serverID, mode)

	case "disconnect":
		if statusErr == nil && statusResp.Data != nil && !isConnected(statusResp.Data.Status) {
			fmt.Println("VPN already disconnected")
			os.Exit(2)
		}

		resp, err := stub.DisconnectVpn(ctx, &pb.EmptyRequest{})
		if err != nil {
			fmt.Fprintln(os.Stderr, "disconnectVpn:", err)
			os.Exit(1)
		}
		if resp.Code != 0 {
			fmt.Fprintf(os.Stderr, "disconnectVpn error %d: %s\n", resp.Code, resp.Message)
			os.Exit(1)
		}
		fmt.Println("VPN disconnecting")

	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", cmd)
		os.Exit(1)
	}
}
