package ingester

import (
	"io"
	"log/slog"
	"os"
	"testing"
	"time"

	recordwal "github.com/grafana/loki/v3/pkg/ingester/wal"
	"github.com/grafana/loki/v3/pkg/logproto"
	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/tsdb/record"
	"github.com/prometheus/prometheus/tsdb/wlog"
	"github.com/prometheus/prometheus/util/compression"
	"github.com/stretchr/testify/require"
)

func TestForensicWriteMissingReference(t *testing.T) {
	dir := os.Getenv("FORENSIC_SYNTHETIC_WAL")
	if dir == "" {
		t.Skip("synthetic fixture generation requires an explicit output directory")
	}
	require.NoError(t, os.MkdirAll(dir, 0755))
	w, err := wlog.New(slog.New(slog.NewTextHandler(io.Discard, nil)), nil, dir, compression.None)
	require.NoError(t, err)
	r := &recordwal.Record{UserID: "fake", Series: []record.RefSeries{{Ref: 1, Labels: labels.FromStrings("test", "synthetic")}}, RefEntries: []recordwal.RefEntries{{Ref: 999, Counter: 1, Entries: []logproto.Entry{{Timestamp: time.Unix(1792368000, 0), Line: "synthetic missing-reference control"}}}}}
	require.NoError(t, w.Log(r.EncodeSeries(nil), r.EncodeEntries(recordwal.CurrentEntriesRec, nil)))
	require.NoError(t, w.Close())
}
