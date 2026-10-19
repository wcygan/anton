package ingester

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	recordwal "github.com/grafana/loki/v3/pkg/ingester/wal"
	"github.com/grafana/loki/v3/pkg/logproto"
	logql "github.com/grafana/loki/v3/pkg/logql/log"
	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/prometheus/prometheus/tsdb/chunks"
	"os"
	"sort"
	"sync"
	"testing"
	"time"

	"github.com/go-kit/log"
	"github.com/grafana/loki/v3/pkg/distributor/writefailures"
	"github.com/grafana/loki/v3/pkg/ingester/client"
	loki_runtime "github.com/grafana/loki/v3/pkg/runtime"
	"github.com/grafana/loki/v3/pkg/storage/chunk"
	"github.com/grafana/loki/v3/pkg/util/constants"
	utilwal "github.com/grafana/loki/v3/pkg/util/wal"
	"github.com/grafana/loki/v3/pkg/validation"
	"github.com/stretchr/testify/require"
)

type forensicRecoverer struct {
	*ingesterRecoverer
	mu         sync.Mutex
	failed     []map[string]any
	all        []map[string]any
	checkpoint []map[string]any
}

func (r *forensicRecoverer) Series(series *Series) error {
	err := r.ingesterRecoverer.Series(series)
	if err != nil {
		return err
	}
	out, _ := r.users.Load(series.UserID)
	stored, _ := out.(*sync.Map).Load(chunks.HeadSeriesRef(series.Fingerprint))
	stream := stored.(*stream)
	it, err := stream.Iterator(context.Background(), nil, time.Unix(0, 0), time.Now().Add(time.Hour), logproto.FORWARD, logql.NewNoopPipeline().ForStream(stream.labels))
	if err != nil {
		return err
	}
	defer it.Close()
	r.mu.Lock()
	defer r.mu.Unlock()
	for it.Next() {
		e := it.At()
		r.checkpoint = append(r.checkpoint, map[string]any{"ref": series.Fingerprint, "timestamp_ns": e.Timestamp.UnixNano(), "sha256": fmt.Sprintf("%x", sha256.Sum256([]byte(e.Line)))})
	}
	return it.Err()
}
func (r *forensicRecoverer) Push(user string, entries recordwal.RefEntries) error {
	r.mu.Lock()
	for _, e := range entries.Entries {
		r.all = append(r.all, map[string]any{"ref": uint64(entries.Ref), "counter": entries.Counter, "timestamp_ns": e.Timestamp.UnixNano(), "sha256": fmt.Sprintf("%x", sha256.Sum256([]byte(e.Line)))})
	}
	r.mu.Unlock()
	err := r.ingesterRecoverer.Push(user, entries)
	if err != nil {
		r.mu.Lock()
		defer r.mu.Unlock()
		for _, e := range entries.Entries {
			r.failed = append(r.failed, map[string]any{"ref": uint64(entries.Ref), "counter": entries.Counter, "timestamp_ns": e.Timestamp.UnixNano(), "sha256": fmt.Sprintf("%x", sha256.Sum256([]byte(e.Line)))})
		}
	}
	return err
}
func TestForensicReplay(t *testing.T) {
	dir := os.Getenv("FORENSIC_WAL")
	require.NotEmpty(t, dir)
	cfg := defaultIngesterTestConfig(t)
	limits, err := validation.NewOverrides(defaultLimitsTestConfig(), nil)
	require.NoError(t, err)
	i, err := New(cfg, client.Config{}, &mockStore{chunks: map[string][]chunk.Chunk{}}, limits, loki_runtime.DefaultTenantConfigs(), nil, writefailures.Cfg{}, constants.Loki, log.NewNopLogger(), nil, mockReadRingWithOneActiveIngester(), nil)
	require.NoError(t, err)
	i.limiter.DisableForWALReplay()
	r := &forensicRecoverer{ingesterRecoverer: newIngesterRecoverer(i)}
	cr, cc, err := newCheckpointReader(dir, log.NewNopLogger())
	require.NoError(t, err)
	ce := RecoverCheckpoint(cr, r)
	cerr := cr.Err()
	require.NoError(t, cc.Close())
	sr, sc, err := utilwal.NewWalReader(dir, -1)
	require.NoError(t, err)
	se := RecoverWAL(context.Background(), sr, r)
	serr := sr.Err()
	require.NoError(t, sc.Close())
	failedKeys := map[string]bool{}
	for _, entry := range r.failed {
		failedKeys[fmt.Sprintf("%d:%d:%s", entry["ref"], entry["timestamp_ns"], entry["sha256"])] = true
	}
	scan, closer, err := utilwal.NewWalReader(dir, -1)
	require.NoError(t, err)
	var locations []map[string]any
	for scan.Next() {
		rec := &recordwal.Record{}
		if recordwal.DecodeRecord(scan.Record(), rec) != nil {
			continue
		}
		for _, batch := range rec.RefEntries {
			count := 0
			for _, e := range batch.Entries {
				if failedKeys[fmt.Sprintf("%d:%d:%x", uint64(batch.Ref), e.Timestamp.UnixNano(), sha256.Sum256([]byte(e.Line)))] {
					count++
				}
			}
			if count > 0 {
				locations = append(locations, map[string]any{"segment": scan.Segment(), "record_end_offset": scan.Offset(), "ref": uint64(batch.Ref), "entries": count})
			}
		}
	}
	scanErr := scan.Err()
	require.NoError(t, closer.Close())
	report := map[string]any{"scan_reader_error": fmt.Sprint(scanErr), "checkpoint_recovery_error": fmt.Sprint(ce), "checkpoint_reader_error": fmt.Sprint(cerr), "segment_recovery_error": fmt.Sprint(se), "segment_recovery_error_type": fmt.Sprintf("%T", se), "segment_reader_error": fmt.Sprint(serr)}
	sort.Slice(r.failed, func(a, b int) bool { return fmt.Sprint(r.failed[a]) < fmt.Sprint(r.failed[b]) })
	sort.Slice(r.all, func(a, b int) bool { return fmt.Sprint(r.all[a]) < fmt.Sprint(r.all[b]) })
	sort.Slice(r.checkpoint, func(a, b int) bool { return fmt.Sprint(r.checkpoint[a]) < fmt.Sprint(r.checkpoint[b]) })
	report["checkpoint_entries"] = r.checkpoint
	report["all_segment_entries"] = r.all
	report["failed_entries"] = r.failed
	report["failed_record_locations"] = locations
	report["recovered_entries"] = testutil.ToFloat64(i.metrics.recoveredEntriesTotal)
	report["duplicate_entries"] = testutil.ToFloat64(i.metrics.duplicateEntriesTotal)
	b, err := json.Marshal(report)
	require.NoError(t, err)
	fmt.Printf("FORENSIC_RESULT %s\n", b)
}
