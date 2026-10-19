package filer

import (
	"bytes"
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/seaweedfs/seaweedfs/weed/pb/filer_pb"
	util_http "github.com/seaweedfs/seaweedfs/weed/util/http"
)

const recoveryFileID = "1,abcd"

func TestPodIPAddressDoesNotRecoverAfterReplacement(t *testing.T) {
	payload := []byte("replacement volume bytes")
	old, replacement, closeOld, requestSeen := makeStaleAndReplacement(t, payload)
	defer old.Close()
	defer replacement.Close()
	defer closeOld()

	url := old.URL + "/" + recoveryFileID
	master := &testMasterClient{urls: map[string][]string{recoveryFileID: {url}}}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	readDone := make(chan error, 1)
	started := time.Now()
	go func() {
		_, err := readOneRecoveryChunk(ctx, master, len(payload))
		readDone <- err
	}()
	<-requestSeen
	registeredAt := time.Now()
	closeOld()
	if err := <-readDone; err == nil {
		t.Fatal("read from the departed Pod IP unexpectedly succeeded")
	}

	if got, err := readOneRecoveryChunk(ctx, master, len(payload)); err == nil {
		t.Fatalf("stale Pod IP recovered without a changed address: %q", got)
	}
	t.Logf("replacement registered after %s; stale Pod-IP reads still failed %s later", registeredAt.Sub(started), time.Since(registeredAt))
}

func TestStableVolumeHostnameReconnectsToReplacementAddress(t *testing.T) {
	payload := []byte("replacement volume bytes")
	old, replacement, closeOld, requestSeen := makeStaleAndReplacement(t, payload)
	defer old.Close()
	defer replacement.Close()
	defer closeOld()

	client := util_http.GetGlobalHttpClient()
	client.Close()
	originalDialContext := client.Transport.DialContext
	defer func() {
		client.Transport.DialContext = originalDialContext
		client.Close()
	}()

	var currentAddress atomic.Value
	currentAddress.Store(old.Listener.Addr().String())
	client.Transport.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		if strings.HasPrefix(address, "volume.test:") {
			address = currentAddress.Load().(string)
		}
		return (&net.Dialer{}).DialContext(ctx, network, address)
	}

	stableURL := "http://volume.test:80/" + recoveryFileID
	master := &testMasterClient{urls: map[string][]string{recoveryFileID: {stableURL}}}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	readDone := make(chan error, 1)
	go func() {
		_, err := readOneRecoveryChunk(ctx, master, len(payload))
		readDone <- err
	}()
	<-requestSeen
	currentAddress.Store(replacement.Listener.Addr().String())
	registeredAt := time.Now()
	closeOld()
	if err := <-readDone; err == nil {
		t.Fatal("read over the old connection unexpectedly succeeded")
	}

	got, err := readOneRecoveryChunk(ctx, master, len(payload))
	if err != nil {
		t.Fatalf("read after stable hostname resolved to replacement: %v", err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatalf("downloaded bytes = %q, want %q", got, payload)
	}
	if elapsed := time.Since(registeredAt); elapsed > time.Second {
		t.Fatalf("replacement read took %s, want under 1s", elapsed)
	}
	t.Logf("exact replacement bytes downloaded %s after hostname resolution changed", time.Since(registeredAt))
}

func makeStaleAndReplacement(t *testing.T, payload []byte) (*httptest.Server, *httptest.Server, func(), <-chan struct{}) {
	t.Helper()
	requestSeen := make(chan struct{}, 1)
	old := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestSeen <- struct{}{}
		<-r.Context().Done()
	}))
	replacement := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(payload)
	}))
	withdrawOld := func() {
		old.CloseClientConnections()
		old.Close()
	}
	return old, replacement, withdrawOld, requestSeen
}

func readOneRecoveryChunk(ctx context.Context, master *testMasterClient, size int) ([]byte, error) {
	chunks := []*filer_pb.FileChunk{{
		FileId: recoveryFileID, Offset: 0, Size: uint64(size), ModifiedTsNs: 1,
	}}
	stream, err := PrepareStreamContentWithThrottler(ctx, master, noopJwt, chunks, 0, int64(size), 0)
	if err != nil {
		return nil, err
	}
	var got bytes.Buffer
	if err := stream(&got); err != nil {
		return nil, err
	}
	return got.Bytes(), nil
}
