package filer

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/seaweedfs/seaweedfs/weed/pb/filer_pb"
	"github.com/seaweedfs/seaweedfs/weed/wdclient"
)

type qualificationMaster struct {
	stale, fresh string
	invalidated  atomic.Bool
}

func (m *qualificationMaster) GetLookupFileIdFunction() wdclient.LookupFileIdFunctionType {
	return func(ctx context.Context, id string) ([]string, error) {
		if m.invalidated.Load() {
			return []string{m.fresh}, nil
		}
		return []string{m.stale}, nil
	}
}

func (m *qualificationMaster) InvalidateCache(id string) { m.invalidated.Store(true) }

// Exercise the actual filer streaming path with a cached dead URL and a live
// replacement supplied only after cache invalidation. Both versions already
// repair this streaming case; it is not a production latency benchmark.
func TestQualificationStaleCacheRecovery(t *testing.T) {
	payload := bytes.Repeat([]byte("exact numbered replacement data\n"), 2048)
	var hits atomic.Int32
	live := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		_, _ = w.Write(payload)
	}))
	defer live.Close()
	dead := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	deadURL := dead.URL
	dead.Close()
	master := &qualificationMaster{stale: deadURL + "/1,abcd", fresh: live.URL + "/1,abcd"}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	started := time.Now()
	stream, err := PrepareStreamContentWithThrottler(ctx, master, func(string) string { return "" },
		[]*filer_pb.FileChunk{{FileId: "1,abcd", Size: uint64(len(payload)), ModifiedTsNs: 1}}, 0, int64(len(payload)), 0)
	var output bytes.Buffer
	if err == nil {
		err = stream(&output)
	}
	if err != nil || !bytes.Equal(output.Bytes(), payload) || hits.Load() == 0 || !master.invalidated.Load() {
		t.Fatalf("recovery: err=%v bytes=%d hits=%d invalidated=%v", err, output.Len(), hits.Load(), master.invalidated.Load())
	}
	t.Logf("exact=%v error=%v replacementHits=%d invalidated=%v elapsed=%s", bytes.Equal(output.Bytes(), payload), err, hits.Load(), master.invalidated.Load(), time.Since(started))
}

func TestQualificationBufferedStaleCacheRecovery(t *testing.T) {
	version := os.Getenv("QUALIFICATION_VERSION")
	if version != "4.40" && version != "4.48" {
		t.Fatal("set QUALIFICATION_VERSION to 4.40 or 4.48")
	}
	payload := bytes.Repeat([]byte("buffered replacement bytes\n"), 2048)
	var hits atomic.Int32
	live := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		_, _ = w.Write(payload)
	}))
	defer live.Close()
	dead := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	deadURL := dead.URL
	dead.Close()
	master := &qualificationMaster{stale: deadURL + "/1,abcd", fresh: live.URL + "/1,abcd"}
	cache := NewReaderCache(4, nil, master.GetLookupFileIdFunction(), master)
	defer cache.destroy()
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	output := make([]byte, len(payload))
	started := time.Now()
	n, err := cache.ReadChunkAt(ctx, output, "1,abcd", nil, false, 0, len(payload), false)
	elapsed := time.Since(started)
	if err != nil || n != len(payload) || !bytes.Equal(output, payload) || hits.Load() != 1 || !master.invalidated.Load() {
		t.Fatalf("buffered recovery: n=%d err=%v hits=%d invalidated=%v", n, err, hits.Load(), master.invalidated.Load())
	}
	if version == "4.48" {
		if elapsed >= time.Second {
			t.Fatalf("new retry incurred backoff: %s", elapsed)
		}
	} else if elapsed < 10*time.Second {
		t.Fatalf("baseline did not exercise retry-before-refresh: %s", elapsed)
	}
	t.Logf("exact=true replacementHits=%d invalidated=%v elapsed=%s", hits.Load(), master.invalidated.Load(), elapsed)
}
