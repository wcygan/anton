package storage

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"

	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/seaweedfs/seaweedfs/weed/stats"
	"github.com/seaweedfs/seaweedfs/weed/storage/backend"
	"github.com/seaweedfs/seaweedfs/weed/storage/needle"
	"github.com/seaweedfs/seaweedfs/weed/storage/super_block"
	"github.com/stretchr/testify/require"
)

type compactionFaultData struct {
	backend.BackendStorageFile
	syncErr, closeErr error
	afterClose        func()
}

func (d *compactionFaultData) Sync() error {
	if d.syncErr != nil {
		return d.syncErr
	}
	return d.BackendStorageFile.Sync()
}
func (d *compactionFaultData) Close() error {
	err := d.BackendStorageFile.Close()
	if d.afterClose != nil {
		d.afterClose()
	}
	return errors.Join(err, d.closeErr)
}

type compactionFaultIndex struct {
	*NeedleMap
	syncErr error
}

func (i *compactionFaultIndex) Sync() error {
	if i.syncErr != nil {
		return i.syncErr
	}
	return i.NeedleMap.Sync()
}
func compactionTestVolume(t *testing.T, kinds ...NeedleMapKind) (*Volume, string) {
	kind := NeedleMapInMemory
	if len(kinds) > 0 {
		kind = kinds[0]
	}
	t.Helper()
	dir := t.TempDir()
	v, err := NewVolume(dir, dir, strings.ReplaceAll(t.Name(), "/", "-"), 1, kind, &super_block.ReplicaPlacement{}, &needle.TTL{}, 0, needle.GetCurrentVersion(), 0, 0)
	require.NoError(t, err)
	t.Cleanup(v.Close)
	for _, id := range []uint64{3, 2, 1} {
		payload := map[uint64]string{1: "retained-one", 2: "retained-two", 3: "old-orphan"}[id]
		_, _, _, err = v.writeNeedle2(fixedNeedle(id, payload), true, true, true)
		require.NoError(t, err)
	}
	_, err = v.deleteNeedle2(fixedNeedle(3, ""))
	require.NoError(t, err)
	return v, dir
}
func compactionAssertRead(t *testing.T, v *Volume) {
	t.Helper()
	for id, want := range map[uint64]string{1: "retained-one", 2: "retained-two"} {
		n := fixedNeedle(id, "")
		_, err := v.readNeedle(n, nil, nil)
		require.NoError(t, err)
		require.Equal(t, want, string(n.Data))
	}
}
func TestCompactionSourceSyncErrors(t *testing.T) {
	for _, mode := range []string{"index-data", "index-map", "data-data", "data-map"} {
		t.Run(mode, func(t *testing.T) {
			v, _ := compactionTestVolume(t)
			d := &compactionFaultData{BackendStorageFile: v.DataBackend}
			i := &compactionFaultIndex{NeedleMap: v.nm.(*NeedleMap)}
			v.DataBackend = d
			v.nm = i
			if mode == "index-data" || mode == "data-data" {
				d.syncErr = syscall.EIO
			} else {
				i.syncErr = syscall.EIO
			}
			var err error
			if mode == "index-data" || mode == "index-map" {
				err = v.CompactByIndex(nil)
			} else {
				err = v.CompactByVolumeData(nil)
			}
			require.ErrorIs(t, err, syscall.EIO)
			compactionAssertRead(t, v)
			for _, ext := range []string{".cpd", ".cpx", ".cpc"} {
				_, err = os.Stat(v.FileName(ext))
				require.True(t, os.IsNotExist(err), ext)
			}
			d.syncErr = nil
			i.syncErr = nil
		})
	}
}
func TestCompactionCloseErrorReopensOriginal(t *testing.T) {
	for name, kind := range map[string]NeedleMapKind{"memory": NeedleMapInMemory, "leveldb": NeedleMapLevelDb} {
		t.Run(name, func(t *testing.T) {
			v, _ := compactionTestVolume(t, kind)
			dat, err := os.ReadFile(v.FileName(".dat"))
			require.NoError(t, err)
			idx, err := os.ReadFile(v.FileName(".idx"))
			require.NoError(t, err)
			before := testutil.ToFloat64(stats.VolumeServerVolumeGauge.WithLabelValues(v.Collection, "volume"))
			require.NoError(t, v.CompactByIndex(nil))
			v.DataBackend = &compactionFaultData{BackendStorageFile: v.DataBackend, closeErr: syscall.EIO}
			require.ErrorIs(t, v.CommitCompact(), syscall.EIO)
			compactionAssertRead(t, v)
			require.Equal(t, before, testutil.ToFloat64(stats.VolumeServerVolumeGauge.WithLabelValues(v.Collection, "volume")))
			after, err := os.ReadFile(v.FileName(".dat"))
			require.NoError(t, err)
			require.Equal(t, dat, after)
			after, err = os.ReadFile(v.FileName(".idx"))
			require.NoError(t, err)
			require.Equal(t, idx, after)
			_, err = os.Stat(v.FileName(".cpc"))
			require.True(t, os.IsNotExist(err))
			_, _, _, err = v.writeNeedle2(fixedNeedle(4, "writable-after-reopen"), true, true, true)
			require.NoError(t, err)
			n := fixedNeedle(4, "")
			_, err = v.readNeedle(n, nil, nil)
			require.NoError(t, err)
			require.Equal(t, "writable-after-reopen", string(n.Data))
		})
	}
}
func TestCompactionCloseRecoveryFailureQuarantines(t *testing.T) {
	v, dir := compactionTestVolume(t)
	saved := filepath.Join(dir, "saved.dat")
	require.NoError(t, v.CompactByIndex(nil))
	v.DataBackend = &compactionFaultData{BackendStorageFile: v.DataBackend, closeErr: syscall.EIO, afterClose: func() { require.NoError(t, os.Rename(v.FileName(".dat"), saved)) }}
	require.ErrorIs(t, v.CommitCompact(), syscall.EIO)
	require.Error(t, v.UnavailableError())
	_, err := v.readNeedle(fixedNeedle(1, ""), nil, nil)
	require.Error(t, err)
	_, _, _, err = v.writeNeedle2(fixedNeedle(4, "must-not-write"), true, true, true)
	require.Error(t, err)
	_, err = os.Stat(saved)
	require.NoError(t, err)
	_, err = os.Stat(v.FileName(".dat"))
	require.True(t, os.IsNotExist(err))
	require.Zero(t, testutil.ToFloat64(stats.VolumeServerVolumeGauge.WithLabelValues(v.Collection, "volume")))
}
