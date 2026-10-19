package ingester

import (
	"context"
	"testing"
	"time"

	"github.com/go-kit/log"
	"github.com/grafana/loki/v3/pkg/distributor/writefailures"
	"github.com/grafana/loki/v3/pkg/ingester/client"
	recordwal "github.com/grafana/loki/v3/pkg/ingester/wal"
	"github.com/grafana/loki/v3/pkg/logproto"
	logql "github.com/grafana/loki/v3/pkg/logql/log"
	loki_runtime "github.com/grafana/loki/v3/pkg/runtime"
	"github.com/grafana/loki/v3/pkg/storage/chunk"
	"github.com/grafana/loki/v3/pkg/util/constants"
	"github.com/grafana/loki/v3/pkg/validation"
	"github.com/prometheus/common/model"
	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/tsdb/chunks"
	"github.com/stretchr/testify/require"
)

func TestForensicFlushedStreamCheckpoint(t *testing.T) {
	// The iterator retained this stream pointer before a successful flush removed its chunks.
	s := &stream{fp: model.Fingerprint(123), labels: labels.FromStrings("app", "forensic"), entryCt: 1, highestTs: time.Unix(1, 0)}
	s.lastLine.ts = time.Unix(1, 0)
	s.lastLine.content = "already-stored"
	it := &streamIterator{instances: []streamInstance{{id: "fake", streams: []*stream{s}}}}
	var checkpointRecords [][]byte
	if it.Next() {
		require.Empty(t, it.Stream().Chunks)
		encoded, err := encodeWithTypeHeader(it.Stream(), recordwal.CheckpointRecord, nil)
		require.NoError(t, err)
		checkpointRecords = append(checkpointRecords, encoded)
	}
	cfg := defaultIngesterTestConfig(t)
	limits, err := validation.NewOverrides(defaultLimitsTestConfig(), nil)
	require.NoError(t, err)
	i, err := New(cfg, client.Config{}, &mockStore{chunks: map[string][]chunk.Chunk{}}, limits, loki_runtime.DefaultTenantConfigs(), nil, writefailures.Cfg{}, constants.Loki, log.NewNopLogger(), nil, mockReadRingWithOneActiveIngester(), nil)
	require.NoError(t, err)
	i.limiter.DisableForWALReplay()
	r := newIngesterRecoverer(i)
	require.NoError(t, RecoverCheckpoint(&MemoryWALReader{xs: checkpointRecords}, r))
	old := recordwal.Record{UserID: "fake", RefEntries: []recordwal.RefEntries{{Ref: chunks.HeadSeriesRef(123), Counter: 1, Entries: []logproto.Entry{{Timestamp: time.Unix(1, 0), Line: "already-stored"}}}}}
	require.NoError(t, RecoverWAL(context.Background(), &MemoryWALReader{xs: [][]byte{old.EncodeEntries(recordwal.CurrentEntriesRec, nil)}}, r))
	newer := recordwal.Record{UserID: "fake", RefEntries: []recordwal.RefEntries{{Ref: chunks.HeadSeriesRef(123), Counter: 2, Entries: []logproto.Entry{{Timestamp: time.Unix(2, 0), Line: "not-yet-stored"}}}}}
	require.NoError(t, RecoverWAL(context.Background(), &MemoryWALReader{xs: [][]byte{newer.EncodeEntries(recordwal.CurrentEntriesRec, nil)}}, r))
	inst := i.getInstances()[0]
	require.NoError(t, inst.forAllStreams(context.Background(), func(s *stream) error {
		it, err := s.Iterator(context.Background(), nil, time.Unix(0, 0), time.Unix(10, 0), logproto.FORWARD, logql.NewNoopPipeline().ForStream(s.labels))
		require.NoError(t, err)
		var lines []string
		for it.Next() {
			lines = append(lines, it.At().Line)
		}
		require.NoError(t, it.Err())
		require.NoError(t, it.Close())
		require.Equal(t, []string{"not-yet-stored"}, lines)
		return nil
	}))
	missing := recordwal.Record{UserID: "fake", RefEntries: []recordwal.RefEntries{{Ref: chunks.HeadSeriesRef(999), Counter: 1, Entries: []logproto.Entry{{Timestamp: time.Unix(3, 0), Line: "unknown-reference"}}}}}
	require.ErrorContains(t, RecoverWAL(context.Background(), &MemoryWALReader{xs: [][]byte{missing.EncodeEntries(recordwal.CurrentEntriesRec, nil)}}, r), "stream (999) not set")
}
