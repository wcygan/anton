package storage

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/seaweedfs/seaweedfs/weed/storage/backend"
	"github.com/seaweedfs/seaweedfs/weed/storage/needle"
	"github.com/seaweedfs/seaweedfs/weed/storage/super_block"
	"github.com/seaweedfs/seaweedfs/weed/storage/types"
	"github.com/stretchr/testify/require"
)

type durableData struct {
	backend.BackendStorageFile
	image []byte
	fail  bool
	once  bool
}

func (d *durableData) Sync() error {
	if d.fail {
		if d.once {
			d.fail = false
		}
		return errors.New("injected data sync EIO")
	}
	if err := d.BackendStorageFile.Sync(); err != nil {
		return err
	}
	var err error
	d.image, err = os.ReadFile(d.Name())
	return err
}

type durableIndex struct {
	*NeedleMap
	image []byte
	fail  bool
	once  bool
}

func (d *durableIndex) Sync() error {
	if d.fail {
		if d.once {
			d.fail = false
		}
		return errors.New("injected index sync EIO")
	}
	if err := d.NeedleMap.Sync(); err != nil {
		return err
	}
	var err error
	d.image, err = os.ReadFile(d.indexFile.Name())
	return err
}
func durableVolume(t *testing.T) (*Volume, *durableData, *durableIndex) {
	t.Helper()
	dir := t.TempDir()
	v, e := NewVolume(dir, dir, "", 1, NeedleMapInMemory, &super_block.ReplicaPlacement{}, &needle.TTL{}, 0, needle.GetCurrentVersion(), 0, 0)
	require.NoError(t, e)
	d := &durableData{BackendStorageFile: v.DataBackend}
	i := &durableIndex{NeedleMap: v.nm.(*NeedleMap)}
	v.DataBackend = d
	v.nm = i
	require.NoError(t, d.Sync())
	require.NoError(t, i.Sync())
	t.Cleanup(v.Close)
	return v, d, i
}
func crashImage(t *testing.T, d *durableData, i *durableIndex) *Volume {
	t.Helper()
	dir := t.TempDir()
	require.NoError(t, os.WriteFile(filepath.Join(dir, "1.dat"), d.image, 0600))
	require.NoError(t, os.WriteFile(filepath.Join(dir, "1.idx"), i.image, 0600))
	v, e := NewVolume(dir, dir, "", 1, NeedleMapInMemory, &super_block.ReplicaPlacement{}, &needle.TTL{}, 0, needle.GetCurrentVersion(), 0, 0)
	require.NoError(t, e)
	t.Cleanup(v.Close)
	return v
}
func assertDurablePayload(t *testing.T, v *Volume, id uint64, want string) {
	t.Helper()
	n := &needle.Needle{Id: types.Uint64ToNeedleId(id)}
	_, e := v.readNeedle(n, nil, nil)
	require.NoError(t, e)
	require.Equal(t, want, string(n.Data))
}
func TestQualificationDurableAcknowledgement(t *testing.T) {
	for _, inline := range []bool{false, true} {
		t.Run(map[bool]string{false: "batch", true: "inline"}[inline], func(t *testing.T) {
			v, d, i := durableVolume(t)
			_, _, _, e := v.writeNeedle2(fixedNeedle(1, "acknowledged-payload"), true, true, inline)
			require.NoError(t, e)
			recovered := crashImage(t, d, i)
			assertDurablePayload(t, recovered, 1, "acknowledged-payload")
			_, _, _, e = v.writeNeedle2(fixedNeedle(1, "acknowledged-payload"), true, true, inline)
			require.NoError(t, e)
			assertDurablePayload(t, crashImage(t, d, i), 1, "acknowledged-payload")
		})
	}
}
func TestQualificationDiscardsUnflushedWrites(t *testing.T) {
	v, d, i := durableVolume(t)
	_, _, _, e := v.writeNeedle2(fixedNeedle(1, "durable-positive-control"), true, false, true)
	require.NoError(t, e)
	require.NoError(t, d.Sync())
	require.NoError(t, i.Sync())
	_, _, _, e = v.writeNeedle2(fixedNeedle(2, "volatile-negative-control"), true, false, true)
	require.NoError(t, e)
	recovered := crashImage(t, d, i)
	assertDurablePayload(t, recovered, 1, "durable-positive-control")
	_, e = recovered.readNeedle(fixedNeedle(2, ""), nil, nil)
	require.Error(t, e)
}
func TestQualificationSyncFailure(t *testing.T) {
	for _, overwrite := range []bool{false, true} {
		for _, inline := range []bool{false, true} {
			for _, which := range []string{"data", "index"} {
				for _, once := range []bool{false, true} {
					name := map[bool]string{false: "new", true: "overwrite"}[overwrite] + "/" + map[bool]string{false: "batch", true: "inline"}[inline] + "/" + which + "/" + map[bool]string{false: "persistent", true: "once"}[once]
					t.Run(name, func(t *testing.T) {
						v, d, i := durableVolume(t)
						_, _, _, e := v.writeNeedle2(fixedNeedle(1, "previous-ack"), true, false, true)
						require.NoError(t, e)
						require.NoError(t, d.Sync())
						require.NoError(t, i.Sync())
						if which == "data" {
							d.fail = true
							d.once = once
						} else {
							i.fail = true
							i.once = once
						}
						id := uint64(2)
						if overwrite {
							id = 1
						}
						_, _, _, e = v.writeNeedle2(fixedNeedle(id, "must-not-ack"), true, true, inline)
						require.Error(t, e, "sync error must reach caller")
						assertDurablePayload(t, crashImage(t, d, i), 1, "previous-ack")
						if !once {
							d.fail = false
							i.fail = false
							_, _, _, next := v.writeNeedle2(fixedNeedle(77, "must-be-fenced"), true, true, inline)
							require.Error(t, next)
						}
					})
				}
			}
		}
	}
}
